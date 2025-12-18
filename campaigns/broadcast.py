"""
Broadcast Campaign Execution
"""
import asyncio
import logging

from aiogram import Bot

from database import bot_methods
from .utils import send_message_with_retry, notify_admins
import config

logger = logging.getLogger(__name__)


async def execute_broadcast(
    bot: Bot,
    bot_id: int,
    campaign_id: int,
    content: dict,
    shutdown_event: asyncio.Event,
):
    """Execute broadcast with pagination and progress tracking"""
    progress = await bot_methods.get_broadcast_progress(campaign_id)
    last_id = progress['last_user_id'] if progress else 0
    sent = progress['sent_count'] if progress else 0
    failed = progress['failed_count'] if progress else 0
    
    logger.info(f"📢 Broadcast #{campaign_id} started/resumed from {last_id}")
    
    batch_size = config.BROADCAST_BATCH_SIZE
    
    while True:
        # Check cancellation
        if await bot_methods.is_campaign_cancelled(campaign_id):
            logger.info(f"Broadcast #{campaign_id}: Cancelled by user")
            await bot_methods.delete_broadcast_progress(campaign_id)
            return

        users = await bot_methods.get_user_ids_paginated(last_id, batch_size)
        if not users:
            break
            
        for user in users:
            if shutdown_event.is_set():
                # Save progress before exit!
                await bot_methods.save_broadcast_progress(campaign_id, last_id, sent, failed)
                logger.info(f"Broadcast #{campaign_id}: Paused at user {last_id}, sent={sent}")
                return
                
            success = await send_message_with_retry(
                bot,
                user['telegram_id'],
                content,
                db_user_id=user.get('id'),
                bot_db_id=bot_id,
            )
            if success:
                sent += 1
            else:
                failed += 1
            
            last_id = user['id']
            await asyncio.sleep(config.MESSAGE_DELAY_SECONDS)
        
        # Checkpoint
        await bot_methods.save_broadcast_progress(campaign_id, last_id, sent, failed)
        
    await bot_methods.mark_campaign_completed(campaign_id, sent, failed)
    await bot_methods.delete_broadcast_progress(campaign_id)
    
    logger.info(f"✅ Broadcast #{campaign_id} finished. Sent: {sent}, Failed: {failed}")
    
    # Notify admins
    report = f"✅ Рассылка #{campaign_id} завершена\n\nОтправлено: {sent}\nОшибок: {failed}"
    await notify_admins(bot, bot_id, report)
