"""
Admin Bots Platform - Main Entry Point
Features: PostgreSQL, Redis FSM, Rate limiting, Broadcasts, Raffles
+ PostgreSQL NOTIFY/LISTEN for instant campaign execution
+ Multi-Bot Support
"""
import asyncio
import logging
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
from database.db import init_db, close_db, get_connection
from database import methods
from handlers import registration, user, receipts, admin, promo
from bot_manager import bot_manager
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
                        await methods.block_user(db_user_id)
                    elif bot_db_id is not None:
                        await methods.block_user_by_telegram_id(telegram_id, bot_db_id)
                except Exception as block_err:
                    logger.warning(f"Failed to mark user blocked ({telegram_id}): {block_err}")
                return False
            if attempt == max_retries - 1:
                logger.error(f"Failed to send to {telegram_id}: {e}")
                return False
            await asyncio.sleep(0.5 * (2 ** attempt)) # Exponential backoff


# === Campaign Processor ===

async def pg_listener():
    """Listen for campaign notifications from PostgreSQL"""
    try:
        async with get_connection() as db:
            conn = db.conn
            # Define callback
            def notify_handler(conn, pid, channel, payload):
                notification_queue.put_nowait((channel, payload))
            
            await conn.add_listener("new_campaign", notify_handler)
            await conn.add_listener("new_bot", notify_handler)
            logger.info("🔊 PostgreSQL Listener attached to 'new_campaign' and 'new_bot'")
            
            while not shutdown_event.is_set():
                try:
                    # Wait for notification
                    await asyncio.wait_for(notification_queue.get(), timeout=5.0)
                    
                    while not notification_queue.empty():
                        channel, payload = await notification_queue.get()
                        try:
                            if channel == "new_campaign":
                                campaign_id = int(payload)
                                logger.info(f"🔔 Notification: Campaign #{campaign_id}")
                                campaign = await methods.get_campaign(campaign_id)
                                if campaign:
                                    scheduled_for = campaign.get("scheduled_for")
                                    if scheduled_for and isinstance(scheduled_for, datetime):
                                        now_local = config.get_now().replace(tzinfo=None)
                                        if scheduled_for > now_local:
                                            logger.info(
                                                f"⏳ Campaign #{campaign_id} scheduled for {scheduled_for}, skipping notification run"
                                            )
                                            continue
                                    await process_campaign(campaign)
                            
                            elif channel == "new_bot":
                                logger.info("🔔 Notification: New Bot added. reloading...")
                                await bot_manager.load_bots()
                                # Add new bots to existing polling loop?
                                # aiogram 3 polling is usually blocking or uses start_polling.
                                # If we are in start_polling, we can't easily add bots without restart or complex task management.
                                # But we can try to just run tasks for new bots if not using dp.start_polling helper?
                                # Actually dp.start_polling takes *bots. If we call it again? No.
                                # If we want dynamic bots, we should run polling manually (Dispatcher.start_polling is a wrapper).
                                # Given complexity, simplest is to just LOG "Please restart to apply".
                                # OR: if we use a runner.
                                # For now, load_bots() updates the manager state.
                                # If we want to start polling for new bot, we need to add it to the polling loop.
                                # This requires implementing a custom PollingManager or restarting the process.
                                # Since I cannot easily restart process from here (unless I exit), I will just Log.
                                logger.warning("⚠️ New bot loaded to Manager. Restart required to start polling! (Dynamic polling not implemented)")
                                # Ideally: os.execv(sys.executable, ['python'] + sys.argv)
                                # But that kills connections abruptly.
                                
                        except Exception as e:
                            logger.error(f"Error processing notification {channel}: {e}")
                        finally:
                            notification_queue.task_done()
                            
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if not shutdown_event.is_set():
                        # logger.error(f"Listener loop error: {e}") # Reduce log noise
                        await asyncio.sleep(5)
    except Exception as e:
        logger.critical(f"PG Listener failed: {e}")


async def process_campaign(campaign: dict):
    """Process a single campaign"""
    cid = campaign['id']
    ctype = campaign['type']
    content = campaign['content']
    bot_id = campaign.get('bot_id')
    
    # Get Bot instance
    bot = bot_manager.bots.get(bot_id)
    if not bot:
        logger.error(f"Bot {bot_id} not found for campaign #{cid}. Skipping.")
        return

    logger.info(f"🚀 Starting campaign #{cid} ({ctype}) for Bot #{bot_id}")
    
    try:
        if ctype == "broadcast":
            await execute_broadcast(bot, cid, content)
        elif ctype == "message":
            await execute_single_message(bot, cid, content)
        elif ctype == "raffle":
            await execute_raffle(bot, cid, content)
        else:
            logger.error(f"Unknown campaign type: {ctype}")
    except Exception as e:
        logger.error(f"Campaign #{cid} failed: {e}")


async def scheduler():
    """Background scheduler - processes notifications + periodic fallback check"""
    # Start PG Listener task
    listener_task = asyncio.create_task(pg_listener())
    
    logger.info("⏰ Scheduler started")
    while not shutdown_event.is_set():
        try:
            # 1. Check pending campaigns (Fallback for missed notifications)
            pending = await methods.get_pending_campaigns()
            for campaign in pending:
                await process_campaign(campaign)
            
            # 2. Wait
            await asyncio.wait_for(shutdown_event.wait(), timeout=config.SCHEDULER_INTERVAL)
            
        except asyncio.TimeoutError:
            pass # Continue loop
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(5)
    
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass


async def execute_broadcast(bot: Bot, campaign_id: int, content: dict):
    """Execute broadcast with pagination and progress tracking"""
    bot_id = bot_manager.get_db_id(bot.id)
    progress = await methods.get_broadcast_progress(campaign_id)
    last_id = progress['last_user_id'] if progress else 0
    sent = progress['sent_count'] if progress else 0
    failed = progress['failed_count'] if progress else 0
    
    logger.info(f"📢 Broadcast #{campaign_id} started/resumed from {last_id}")
    
    batch_size = config.BROADCAST_BATCH_SIZE
    
    while True:
        users = await methods.get_user_ids_paginated(bot_id, last_id, batch_size)
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
        await methods.save_broadcast_progress(campaign_id, last_id, sent, failed)
        
    await methods.mark_campaign_completed(campaign_id, sent, failed)
    await methods.delete_broadcast_progress(campaign_id)
    
    logger.info(f"✅ Broadcast #{campaign_id} finished. Sent: {sent}, Failed: {failed}")
    
    # Notify admin
    report = f"✅ Рассылка #{campaign_id} завершена\n\nОтправлено: {sent}\nОшибок: {failed}"
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report)
        except:
            pass


async def execute_single_message(bot: Bot, campaign_id: int, content: dict):
    """Send message to a single user"""
    telegram_id = content.get("user_id")
    if telegram_id:
        success = await send_message_with_retry(
            bot,
            telegram_id,
            content,
            bot_db_id=bot_manager.get_db_id(bot.id),
        )
        await methods.mark_campaign_completed(campaign_id, 1 if success else 0, 0 if success else 1)


async def execute_raffle(bot: Bot, campaign_id: int, content: dict):
    """Execute raffle with winner persistence"""
    bot_id = bot_manager.get_db_id(bot.id)
    count = int(content.get("count", 1))
    prize = content.get("prize", "Приз")
    
    logger.info(f"🎁 Raffle #{campaign_id}: {count} winners for '{prize}'")
    
    # 1. Select winners (Weighted random by tickets)
    participants = await methods.get_participants_with_tickets(bot_id)
    
    if not participants:
        logger.warning(f"Raffle #{campaign_id}: No participants")
        await methods.mark_campaign_completed(campaign_id)
        return

    # Weighted selection
    weighted_pool = []
    for p in participants:
         tickets = p['total_tickets']
         if tickets > 0:
             weighted_pool.extend([p] * tickets)
    
    if not weighted_pool:
         logger.warning("No tickets found")
         await methods.mark_campaign_completed(campaign_id)
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
    saved_count = await methods.save_winners_atomic(campaign_id, winners_data, bot_id)
    logger.info(f"Raffle #{campaign_id}: Saved {saved_count} winners")
    
    # 3. Notify Winners
    win_msg_template = content.get("win_msg", {})
    sent_win = 0
    for w in winners_data:
        msg = win_msg_template.copy()
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
    
    db_winners = await methods.get_campaign_winners(campaign_id)
    for w in db_winners:
        if sent_win > 0:
             await methods.mark_winner_notified(w['id'])


    # 4. Notify Losers
    lose_msg = content.get("lose_msg")
    sent_lose = 0
    if lose_msg:
        losers = await methods.get_raffle_losers(campaign_id)
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
    
    await methods.mark_campaign_completed(campaign_id, sent_win + sent_lose, 0)
    
    # Admin Report
    report = (f"🎁 Розыгрыш #{campaign_id} завершен\n"
              f"🏆 Победителей: {len(winners_data)}\n"
              f"📢 Уведомлено: {sent_win} (побед) + {sent_lose} (остальных)")
    
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report)
        except:
            pass


# === Startup/Shutdown ===

async def on_startup():
    await init_db()
    try:
        await config_manager.load()
        await init_rate_limiter()
    except Exception as e:
        logger.warning(f"Config/ratelimiter init failed: {e}")
    
    # Load bots
    await bot_manager.load_bots()
    bots = bot_manager.get_bots()
    
    if not bots:
        logger.warning("No bots found in database! Please add a bot via Admin Panel or check invalid token.")
    
    # Validate config
    errors = config.validate_config()
    if errors:
        logger.error(f"Config Validation Error: {errors}")
    
    # Setup Handlers
    dp.include_router(registration.router)
    dp.include_router(user.router)
    dp.include_router(receipts.router)
    dp.include_router(promo.router)
    dp.include_router(admin.router)
    
    # Add Middleware
    dp.update.middleware(BotMiddleware())
    
    # Preload enabled modules for all bots (populates cache for middleware)
    from utils.bot_middleware import get_enabled_modules
    for bot_id in bot_manager.bots.keys():
        await get_enabled_modules(bot_id)
        logger.info(f"Preloaded modules for bot {bot_id}")
    
    # Start Scheduler
    asyncio.create_task(scheduler())
    
    logger.info("Bot started")


async def on_shutdown():
    shutdown_event.set()
    await bot_manager.stop_bot(0) 
    for bot in bot_manager.get_bots():
        try:
            await bot.session.close()
        except:
            pass

    await close_db()
    await redis.close()
    try:
        await close_rate_limiter()
    except:
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
            # Pass all bots to poller
            await dp.start_polling(*bots)
        else:
            logger.error("No bots to poll. Waiting for signal...")
            # If no bots, we should just wait for shutdown or new bots (reloading NYI efficiently here without restart)
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
