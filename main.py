"""
Admin Bots Platform - Main Entry Point
Features: PostgreSQL, Redis FSM, Rate limiting, Broadcasts, Raffles
+ PostgreSQL NOTIFY/LISTEN for instant campaign execution
+ Multi-Bot Support with per-bot databases
"""
import asyncio
import logging
import os
import signal
import sys
import random
import time
from datetime import datetime
from typing import Dict, List, Optional
import orjson
from aiogram import Dispatcher
from aiogram.types import FSInputFile
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.bot import Bot
from redis.asyncio import Redis

import config
from database.panel_db import init_panel_db, close_panel_db, get_panel_connection, get_active_bots, get_bot_by_id
from database.bot_db import bot_db_manager
from database import bot_methods
from bot_manager import bot_manager, PollingManager
from modules.base import module_loader
from modules.core import core_module
from modules.registration import registration_module
from modules.receipts import receipts_module
from modules.promo import promo_module
from modules.admin import admin_module
from utils.bot_middleware import BotMiddleware
from utils.config_manager import config_manager
from utils.rate_limiter import init_rate_limiter, close_rate_limiter

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global Dispatcher
redis = Redis.from_url(config.REDIS_URL)
storage = RedisStorage(redis=redis)
dp = Dispatcher(storage=storage)

shutdown_event = asyncio.Event()
notification_queue = asyncio.Queue()
polling_manager = None  # Will be initialized in on_startup


# === Helper Functions ===

async def send_message_with_retry(
    bot: Bot,
    telegram_id: int,
    content: dict,
    *,
    db_user_id: Optional[int] = None,
    bot_db_id: Optional[int] = None,
    max_retries: int = 3,
):
    """Send message with exponential backoff. Supports photos by file_id or local path."""
    for attempt in range(max_retries):
        try:
            if "photo" in content:
                await bot.send_photo(telegram_id, content["photo"], caption=content.get("caption"))
            elif "photo_path" in content:
                await bot.send_photo(
                    telegram_id,
                    FSInputFile(content["photo_path"]),
                    caption=content.get("caption"),
                )
            else:
                text = content.get("text") or ""
                if not text.strip():
                    raise ValueError("Empty text message")
                await bot.send_message(telegram_id, text)
            return True
        except Exception as e:
            if "blocked" in str(e).lower():
                try:
                    if db_user_id is not None:
                        await bot_methods.block_user(db_user_id)
                    elif bot_db_id is not None:
                        await bot_methods.block_user_by_telegram_id(telegram_id)
                except Exception as block_err:
                    logger.warning(f"Failed to mark user blocked ({telegram_id}): {block_err}")
                return False
            if attempt == max_retries - 1:
                logger.error(f"Failed to send to {telegram_id}: {e}")
                return False
            await asyncio.sleep(0.5 * (2 ** attempt)) # Exponential backoff


# === Campaign Processor ===

async def pg_listener():
    """Listen for notifications from PostgreSQL (uses panel DB)"""
    try:
        async with get_panel_connection() as db:
            conn = db.conn
            # Define callback
            def notify_handler(conn, pid, channel, payload):
                notification_queue.put_nowait((channel, payload))
            
            await conn.add_listener("new_bot", notify_handler)
            logger.info("🔊 PostgreSQL Listener attached to 'new_bot'")
            
            while not shutdown_event.is_set():
                try:
                    # Wait for notification
                    await asyncio.wait_for(notification_queue.get(), timeout=5.0)
                    
                    while not notification_queue.empty():
                        channel, payload = await notification_queue.get()
                        try:
                            if channel == "new_bot":
                                logger.info("🔔 Notification: New Bot added. Reloading dynamically...")
                                # Use PollingManager to add new bots without restart
                                if polling_manager:
                                    await polling_manager.reload_bots()
                                    logger.info("✅ Bots reloaded dynamically")
                                else:
                                    logger.warning("⚠️ PollingManager not initialized, cannot reload")
                                
                        except Exception as e:
                            logger.error(f"Error processing notification {channel}: {e}")
                        finally:
                            notification_queue.task_done()
                            
                except asyncio.TimeoutError:
                    continue
    except Exception as e:
        logger.critical(f"PG Listener failed: {e}")


async def process_campaign(campaign: dict):
    """Process a single campaign (with per-bot database context)"""
    cid = campaign['id']
    ctype = campaign['type']
    content = campaign['content'] if isinstance(campaign['content'], dict) else {}
    
    # Campaigns now stored per-bot, bot_id passed via _bot_id from scheduler
    bot_id = campaign.get('_bot_id') or campaign.get('bot_id')
    
    if not bot_id:
        logger.error(f"Campaign #{cid} has no bot_id. Skipping.")
        return
    
    # Get Bot instance
    bot = bot_manager.bots.get(bot_id)
    if not bot:
        logger.error(f"Bot {bot_id} not found for campaign #{cid}. Skipping.")
        return
    
    logger.info(f"🚀 Starting campaign #{cid} ({ctype}) for Bot #{bot_id}")
    
    # Use context manager for safe database context management
    try:
        async with bot_methods.bot_db_context(bot_id):
            if ctype == "broadcast":
                await execute_broadcast(bot, bot_id, cid, content)
            elif ctype == "message":
                await execute_single_message(bot, bot_id, cid, content)
            elif ctype == "raffle":
                await execute_raffle(bot, bot_id, cid, content)
            else:
                logger.error(f"Unknown campaign type: {ctype}")
    except RuntimeError as e:
        logger.error(f"Campaign #{cid} database context error: {e}")
    except Exception as e:
        logger.error(f"Campaign #{cid} failed: {e}", exc_info=True)


async def scheduler():
    """Background scheduler - processes notifications + periodic fallback check"""
    # Start PG Listener task
    listener_task = asyncio.create_task(pg_listener())
    
    logger.info("⏰ Scheduler started")
    while not shutdown_event.is_set():
        try:
            # 1. Check pending campaigns for each bot
            for bot_id, bot in bot_manager.bots.items():
                try:
                    bot_db = bot_db_manager.get(bot_id)
                    if not bot_db:
                        continue
                    
                    async with bot_db.get_connection() as conn:
                        pending = await conn.fetch("""
                            SELECT * FROM campaigns 
                            WHERE is_completed = FALSE 
                            AND (scheduled_for IS NULL OR scheduled_for <= NOW())
                            ORDER BY id
                        """)
                    
                    for campaign in pending:
                        campaign_dict = dict(campaign)
                        campaign_dict['_bot_id'] = bot_id  # Add bot_id for processing
                        await process_campaign(campaign_dict)
                except Exception as e:
                    logger.error(f"Scheduler error for bot {bot_id}: {e}")
            
            # 2. Wait
            await asyncio.wait_for(shutdown_event.wait(), timeout=config.SCHEDULER_INTERVAL)
            
        except asyncio.TimeoutError:
            pass  # Continue loop
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(5)
    
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass


async def execute_broadcast(bot: Bot, bot_id: int, campaign_id: int, content: dict):
    """Execute broadcast with pagination and progress tracking"""
    progress = await bot_methods.get_broadcast_progress(campaign_id)
    last_id = progress['last_user_id'] if progress else 0
    sent = progress['sent_count'] if progress else 0
    failed = progress['failed_count'] if progress else 0
    
    logger.info(f"📢 Broadcast #{campaign_id} started/resumed from {last_id}")
    
    batch_size = config.BROADCAST_BATCH_SIZE
    
    while True:
        users = await bot_methods.get_user_ids_paginated(last_id, batch_size)
        if not users:
            break
            
        for user in users:
            if shutdown_event.is_set():
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
    
    # Notify admins (bot-specific plus global)
    report = f"✅ Рассылка #{campaign_id} завершена\n\nОтправлено: {sent}\nОшибок: {failed}"
    bot_info = await get_bot_by_id(bot_id) if bot_id else None
    bot_admins = bot_info.get('admin_ids', []) if bot_info else []
    all_admins = set(config.ADMIN_IDS) | set(bot_admins or [])
    for admin_id in all_admins:
        try:
            await bot.send_message(admin_id, report)
        except Exception:
            pass


async def execute_single_message(bot: Bot, bot_id: int, campaign_id: int, content: dict):
    """Send message to a single user"""
    telegram_id = content.get("user_id") or content.get("telegram_id")
    if telegram_id:
        success = await send_message_with_retry(
            bot,
            telegram_id,
            content,
            bot_db_id=bot_id,
        )
        await bot_methods.mark_campaign_completed(campaign_id, 1 if success else 0, 0 if success else 1)


async def execute_raffle(bot: Bot, bot_id: int, campaign_id: int, content: dict):
    """Execute raffle with winner persistence"""
    count = int(content.get("count", 1))
    prize = content.get("prize", "Приз")
    is_final = content.get("is_final", False)
    
    raffle_type = "FINAL" if is_final else "regular"
    logger.info(f"🎁 Raffle #{campaign_id} ({raffle_type}): {count} winners for '{prize}'")
    
    # 1. Select winners (Weighted random by tickets)
    # For final raffle: use ALL tickets ever assigned (receipts + manual + promo)
    # For regular raffle: use only active tickets from receipts
    if is_final:
        participants = await bot_methods.get_all_tickets_for_final_raffle()
    else:
        participants = await bot_methods.get_participants_with_tickets()
    
    if not participants:
        logger.warning(f"Raffle #{campaign_id}: No participants")
        await bot_methods.mark_campaign_completed(campaign_id)
        return

    # Weighted selection
    weighted_pool = []
    for p in participants:
         tickets = p['total_tickets']
         if tickets > 0:
             weighted_pool.extend([p] * tickets)
    
    if not weighted_pool:
         logger.warning("No tickets found")
         await bot_methods.mark_campaign_completed(campaign_id)
         return

    winners_data = []
    selected_users = set()
    
    actual_count = min(count, len(participants))
    
    while len(winners_data) < actual_count:
        if not weighted_pool:
            break
        
        winner = random.choice(weighted_pool)
        if winner['user_id'] in selected_users:
            weighted_pool = [x for x in weighted_pool if x['user_id'] != winner['user_id']]
            continue
            
        selected_users.add(winner['user_id'])
        winners_data.append({
            "user_id": winner['user_id'],
            "telegram_id": winner['telegram_id'],
            "prize_name": prize,
            "full_name": winner.get('full_name'),
            "username": winner.get('username')
        })
        weighted_pool = [x for x in weighted_pool if x['user_id'] != winner['user_id']]

    # 2. Save winners atomically
    saved_count = await bot_methods.save_winners_atomic(campaign_id, winners_data)
    logger.info(f"Raffle #{campaign_id}: Saved {saved_count} winners")
    
    # 3. Notify Winners
    win_msg_template = content.get("win_msg", {})
    sent_win = 0
    notified_user_ids = set()  # Track actually notified users
    
    for w in winners_data:
        msg = win_msg_template.copy() if isinstance(win_msg_template, dict) else {}
        if not msg:
            msg = {"text": f"🎉 Поздравляем! Вы выиграли: {prize}!"}
        
        if await send_message_with_retry(
            bot,
            w['telegram_id'],
            msg,
            db_user_id=w.get('user_id'),
            bot_db_id=bot_id,
        ):
            sent_win += 1
            notified_user_ids.add(w['user_id'])
    
    # Mark only actually notified winners
    db_winners = await bot_methods.get_campaign_winners(campaign_id)
    for w in db_winners:
        if w['user_id'] in notified_user_ids:
            await bot_methods.mark_winner_notified(w['id'])


    # 4. Notify Losers
    lose_msg = content.get("lose_msg")
    sent_lose = 0
    if lose_msg:
        losers = await bot_methods.get_raffle_losers(campaign_id)
        for loser in losers:
             if shutdown_event.is_set(): break
             if await send_message_with_retry(
                 bot,
                 loser['telegram_id'],
                 lose_msg,
                 bot_db_id=bot_id,
             ):
                 sent_lose += 1
             await asyncio.sleep(config.MESSAGE_DELAY_SECONDS)
    
    await bot_methods.mark_campaign_completed(campaign_id, sent_win + sent_lose, 0)
    
    # Admin Report (bot-specific plus global admins)
    report = (f"🎁 Розыгрыш #{campaign_id} завершен\n"
              f"🏆 Победителей: {len(winners_data)}\n"
              f"📢 Уведомлено: {sent_win} (побед) + {sent_lose} (остальных)")
    
    bot_info = await get_bot_by_id(bot_id) if bot_id else None
    bot_admins = bot_info.get('admin_ids', []) if bot_info else []
    all_admins = set(config.ADMIN_IDS) | set(bot_admins or [])
    for admin_id in all_admins:
        try:
            await bot.send_message(admin_id, report)
        except Exception:
            pass


# === Startup/Shutdown ===

async def on_startup():
    # Initialize panel database
    await init_panel_db(config.PANEL_DATABASE_URL)
    
    try:
        await init_rate_limiter()
    except Exception as e:
        logger.warning(f"Rate limiter init failed: {e}")
    
    # Load bots from panel registry (this also connects to their individual DBs)
    await bot_manager.load_bots_from_registry()
    bots = bot_manager.get_bots()
    
    if not bots:
        logger.warning("No bots found in database! Please add a bot via Admin Panel or check invalid token.")
    
    # Validate config
    errors = config.validate_config()
    if errors:
        logger.error(f"Config Validation Error: {errors}")
    
    # Setup Modules
    module_loader.register(core_module)
    module_loader.register(registration_module)
    module_loader.register(receipts_module)
    module_loader.register(promo_module)
    module_loader.register(admin_module)
    
    # Include Routers from modules
    for module in module_loader.get_all_modules():
        dp.include_router(module.get_router())
    
    # Add Middleware
    dp.update.middleware(BotMiddleware())
    
    # Preload enabled modules for all bots (populates cache for middleware)
    from utils.bot_middleware import get_enabled_modules
    for bot_id in bot_manager.bots.keys():
        await get_enabled_modules(bot_id)
        logger.info(f"Preloaded modules for bot {bot_id}")
    
    # Initialize Polling Manager
    global polling_manager
    polling_manager = PollingManager(dp)
    
    logger.info("Bot started")


async def on_shutdown():
    shutdown_event.set()
    
    # Close all bot connections
    await bot_manager.close_all()
    
    # Close panel database
    await close_panel_db()
    await redis.close()
    
    # Close API client
    try:
        from utils.api import close_api_client
        await close_api_client()
    except Exception:
        pass
    
    try:
        await close_rate_limiter()
    except Exception:
        pass
    logger.info("Bot stopped")


async def main():
    # Signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown()))

    try:
        await on_startup()
        bots = bot_manager.get_bots()
        
        if bots:
            # Start scheduler as background task
            asyncio.create_task(scheduler())
            
            # Use PollingManager for dynamic bot management
            await polling_manager.start_all()
            await polling_manager.wait()
        else:
            logger.warning("No bots found. Starting scheduler and waiting for new bots...")
            # Start scheduler to listen for new bots
            asyncio.create_task(scheduler())
            await shutdown_event.wait()
            
    except Exception as e:
        logger.critical(f"Main loop error: {e}")
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
