"""
Raffle Campaign Execution
Memory-efficient implementation with DB-side winner selection
"""
import asyncio
import logging

from aiogram import Bot

from database import bot_methods
from .utils import send_message_with_retry, notify_admins
import config

logger = logging.getLogger(__name__)


async def execute_raffle(
    bot: Bot,
    bot_id: int,
    campaign_id: int,
    content: dict,
    shutdown_event: asyncio.Event,
):
    """
    Execute raffle with:
    1. DB-side weighted random selection (memory efficient)
    2. Winner persistence for resume capability
    3. Paginated loser notification
    4. Graceful shutdown with progress saving
    """
    prizes = content.get("prizes")
    if not prizes:
         # Backward compatibility
         prizes = [{"name": content.get("prize", "Приз"), "count": int(content.get("count", 1))}]
    
    is_final = content.get("is_final", False)
    raffle_type = "FINAL" if is_final else "regular"
    total_count = sum(p['count'] for p in prizes)
    logger.info(f"🎁 Raffle #{campaign_id} ({raffle_type}): {total_count} winners, {len(prizes)} prize types")
    
    # Check cancellation start
    if await bot_methods.is_campaign_cancelled(campaign_id):
        logger.info(f"Raffle #{campaign_id}: Cancelled at start")
        return

    # 1. Check if winners already exist (resume case)
    existing_winners = await bot_methods.get_campaign_winners(campaign_id)
    
    if not existing_winners:
        # Selection phase
        logger.info(f"Raffle #{campaign_id}: Selecting winners via DB...")
        
        all_winners_data = []
        exclude_ids = []
        
        for p in prizes:
            p_name = p['name']
            p_count = int(p['count'])
            if p_count <= 0: continue
            
            # Select winners for this prize
            # Note: select_random_winners_db uses weighted logic
            selected = await bot_methods.select_random_winners_db(p_count, p_name, exclude_user_ids=exclude_ids)
            
            if not selected:
                logger.warning(f"Raffle #{campaign_id}: Not enough participants for prize '{p_name}'")
                continue
                
            for w in selected:
                exclude_ids.append(w['user_id'])
                all_winners_data.append({
                    "user_id": w['user_id'],
                    "telegram_id": w['telegram_id'],
                    "prize_name": p_name,
                    "full_name": w.get('full_name'),
                    "username": w.get('username')
                })
        
        if not all_winners_data:
            logger.warning(f"Raffle #{campaign_id}: No winners selected at all")
            await bot_methods.mark_campaign_completed(campaign_id)
            return
        
        await bot_methods.save_winners_atomic(campaign_id, all_winners_data)
        logger.info(f"Raffle #{campaign_id}: Selected and saved {len(all_winners_data)} winners")
        existing_winners = await bot_methods.get_campaign_winners(campaign_id)

    # 2. Notify Winners (only those not yet notified)
    
    sent_win = 0
    for i, w in enumerate(existing_winners):
        if i % 5 == 0 and await bot_methods.is_campaign_cancelled(campaign_id):
            logger.info(f"Raffle #{campaign_id}: Cancelled during winner notification")
            return
            
        if shutdown_event.is_set():
            logger.info(f"Raffle #{campaign_id}: Paused during winner notification")
            return
            
        if w['notified']:
            sent_win += 1
            continue
            
        msg = None
        # 1. Get prize-specific message
        if prizes:
             for p in prizes:
                 if p['name'] == w.get('prize_name'):
                     # Effective text (fallback to hardcoded default)
                     raw_text = p.get('msg') 
                     if not raw_text:
                         raw_text = f"🎉 Поздравляем! Вы выиграли: {w.get('prize_name', 'Приз')}!"
                     
                     # Effective photo
                     final_path = p.get('photo_path')
                     
                     if final_path:
                         msg = {"photo_path": final_path, "caption": raw_text}
                     else:
                         msg = {"text": raw_text}
                     break
        
        # 2. Fallback (should not be reached if prize found, but for safety)
        if not msg:
             msg = {"text": f"🎉 Поздравляем! Вы выиграли: {w.get('prize_name', 'Приз')}!"}
        
        if await send_message_with_retry(
            bot,
            w['telegram_id'],
            msg,
            db_user_id=w.get('user_id'),
            bot_db_id=bot_id,
        ):
            await bot_methods.mark_winner_notified(w['id'])
            sent_win += 1
            
    # 3. Notify Losers (Progressive/Paginated)
    lose_msg = content.get("lose_msg")
    sent_lose = 0
    failed_lose = 0
    
    if lose_msg:
        # Use broadcast_progress to track loser notifications
        progress = await bot_methods.get_broadcast_progress(campaign_id)
        last_id = progress['last_user_id'] if progress else 0
        sent_lose = progress['sent_count'] if progress else 0
        failed_lose = progress['failed_count'] if progress else 0
        
        batch_size = config.BROADCAST_BATCH_SIZE
        
        while True:
            if await bot_methods.is_campaign_cancelled(campaign_id):
                logger.info(f"Raffle #{campaign_id}: Cancelled during loser notification")
                await bot_methods.delete_broadcast_progress(campaign_id)
                return

            losers = await bot_methods.get_raffle_losers_paginated(campaign_id, last_id, batch_size)
            if not losers:
                break
                
            for loser in losers:
                if shutdown_event.is_set():
                    # Save progress before exit!
                    await bot_methods.save_broadcast_progress(campaign_id, last_id, sent_lose, failed_lose)
                    logger.info(f"Raffle #{campaign_id}: Paused at loser {last_id}, sent={sent_lose}")
                    return
                    
                success = await send_message_with_retry(
                    bot,
                    loser['telegram_id'],
                    lose_msg,
                    db_user_id=loser.get('id'),
                    bot_db_id=bot_id,
                )
                if success:
                    sent_lose += 1
                else:
                    failed_lose += 1
                
                last_id = loser['id']
                await asyncio.sleep(config.MESSAGE_DELAY_SECONDS)
                
            # Update progress after each batch
            await bot_methods.save_broadcast_progress(campaign_id, last_id, sent_lose, failed_lose)

    # 4. Cleanup and Report
    await bot_methods.mark_campaign_completed(campaign_id, sent_win + sent_lose, failed_lose)
    if lose_msg:
        await bot_methods.delete_broadcast_progress(campaign_id)
    
    # 5. Burn tickets for intermediate raffles
    burn_tickets = content.get("burn_tickets", False)
    if burn_tickets:
        await bot_methods.burn_all_tickets()
        logger.info(f"🔥 Raffle #{campaign_id}: Tickets burned (intermediate raffle)")
    
    logger.info(f"✅ Raffle #{campaign_id} finished. Winners notified: {sent_win}, Losers: {sent_lose}")
    
    # Admin Report
    raffle_type_str = "Финальный" if is_final else "Промежуточный"
    burn_info = "\n🔥 Билеты сброшены" if burn_tickets else ""
    report = (f"🎁 Розыгрыш #{campaign_id} завершен\n"
              f"📋 Тип: {raffle_type_str}\n"
              f"🏆 Победителей: {len(existing_winners)}\n"
              f"📢 Уведомлено: {sent_win} (побед) + {sent_lose} (остальных){burn_info}")
    
    await notify_admins(bot, bot_id, report)
