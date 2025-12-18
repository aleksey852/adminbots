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
    count = int(content.get("count", 1))
    prize = content.get("prize", "Приз")
    is_final = content.get("is_final", False)
    
    raffle_type = "FINAL" if is_final else "regular"
    logger.info(f"🎁 Raffle #{campaign_id} ({raffle_type}): {count} winners for '{prize}'")
    
    # 1. Check if winners already exist (resume case)
    existing_winners = await bot_methods.get_campaign_winners(campaign_id)
    
    if not existing_winners:
        # Selection phase - use DB-side selection (memory efficient!)
        logger.info(f"Raffle #{campaign_id}: Selecting {count} winners via DB...")
        
        # Use memory-efficient DB-side weighted random selection
        selected = await bot_methods.select_random_winners_db(count, prize, exclude_user_ids=[])
        
        if not selected:
            logger.warning(f"Raffle #{campaign_id}: No participants")
            await bot_methods.mark_campaign_completed(campaign_id)
            return
        
        # Convert to winner format and save atomically
        winners_to_save = [
            {
                "user_id": w['user_id'],
                "telegram_id": w['telegram_id'],
                "prize_name": prize,
                "full_name": w.get('full_name'),
                "username": w.get('username')
            }
            for w in selected
        ]
        
        await bot_methods.save_winners_atomic(campaign_id, winners_to_save)
        logger.info(f"Raffle #{campaign_id}: Selected and saved {len(winners_to_save)} winners")
        existing_winners = await bot_methods.get_campaign_winners(campaign_id)

    # 2. Notify Winners (only those not yet notified)
    win_msg_template = content.get("win_msg", {})
    if not isinstance(win_msg_template, dict):
        win_msg_template = {"text": win_msg_template}
    
    sent_win = 0
    for w in existing_winners:
        if shutdown_event.is_set():
            logger.info(f"Raffle #{campaign_id}: Paused during winner notification")
            return
            
        if w['notified']:
            sent_win += 1
            continue
            
        msg = win_msg_template.copy() if win_msg_template else {"text": f"🎉 Поздравляем! Вы выиграли: {prize}!"}
        
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
    
    logger.info(f"✅ Raffle #{campaign_id} finished. Winners notified: {sent_win}, Losers: {sent_lose}")
    
    # Admin Report
    report = (f"🎁 Розыгрыш #{campaign_id} завершен\n"
              f"🏆 Победителей: {len(existing_winners)}\n"
              f"📢 Уведомлено: {sent_win} (побед) + {sent_lose} (остальных)")
    
    await notify_admins(bot, bot_id, report)
