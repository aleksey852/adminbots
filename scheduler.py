"""
Scheduler Module - PostgreSQL Listener and Campaign Processing
"""
import asyncio
import logging
import json

from aiogram import Bot

from database.panel_db import get_panel_connection
from database.bot_db import bot_db_manager
from database import bot_methods
from bot_manager import bot_manager
from campaigns import execute_broadcast, execute_raffle, execute_single_message
import config

logger = logging.getLogger(__name__)


async def pg_listener(
    shutdown_event: asyncio.Event,
    notification_queue: asyncio.Queue,
    polling_manager,
):
    """Listen for notifications from PostgreSQL (uses panel DB)"""
    try:
        logger.info(f"🔊 Starting PG Listener. PollingManager: {'Active' if polling_manager else 'None'}")
        async with get_panel_connection() as db:
            conn = db.conn
            
            # Define callback
            def notify_handler(conn, pid, channel, payload):
                # logger.debug(f"Received notification: {channel} -> {payload}")
                notification_queue.put_nowait((channel, payload))
            
            await conn.add_listener("new_bot", notify_handler)
            await conn.add_listener("restart_bot", notify_handler)
            await conn.add_listener("reload_config", notify_handler)
            logger.info("🔊 PostgreSQL Listener attached to 'new_bot', 'restart_bot', 'reload_config'")
            
            while not shutdown_event.is_set():
                try:
                    # Wait for notification and save it (don't discard!)
                    first_notification = await asyncio.wait_for(notification_queue.get(), timeout=5.0)
                    
                    # Process the first notification we just received
                    notifications_to_process = [first_notification]
                    
                    # Also grab any additional notifications that arrived
                    while not notification_queue.empty():
                        notifications_to_process.append(await notification_queue.get())
                    
                    for channel, payload in notifications_to_process:
                        try:
                            if channel == "new_bot":
                                logger.info("🔔 Notification: New Bot added. Reloading dynamically...")
                                # Use PollingManager to add new bots without restart
                                if polling_manager:
                                    await polling_manager.reload_bots()
                                    logger.info("✅ Bots reloaded dynamically")
                                else:
                                    logger.warning("⚠️ PollingManager not initialized, cannot reload")
                            
                            elif channel == "reload_config":
                                logger.info(f"🔔 Notification: Reload Config for Bot #{payload}")
                                try:
                                    bot_id = int(payload)
                                    # Reload config for this bot
                                    from utils.config_manager import config_manager
                                    # Use DB context manager to ensure connection
                                    try:
                                        # Manually invoke load_for_single_bot logic
                                        # But config_manager.load_for_bot expects to run inside a request/context where get_current_bot_db() works?
                                        # No, wait. config_manager.load_for_bot uses get_current_bot_db().
                                        # We need to set the context variable or pass the db explicitly?
                                        # load_for_bot source:
                                        # async with db.get_connection() as conn:
                                        # It gets db from bot_methods.get_current_bot_db()
                                        
                                        # We need to set context manually here
                                        from database.bot_methods import bot_context
                                        token = bot_context.set(bot_id)
                                        try:
                                            await config_manager.load_for_bot(bot_id)
                                            logger.info(f"✅ Config reloaded for bot {bot_id}")
                                        finally:
                                            bot_context.reset(token)
                                            
                                    except Exception as e:
                                        logger.error(f"Failed to reload config for bot {bot_id}: {e}")
                                        
                                except ValueError:
                                    logger.error(f"Invalid payload for reload_config: {payload}")

                            elif channel == "restart_bot":
                                logger.info(f"🔔 Notification: Restart Bot #{payload}")
                                if polling_manager:
                                    try:
                                        bot_id = int(payload)
                                        # 1. Stop polling
                                        await polling_manager.stop_polling_for_bot(bot_id)
                                        
                                        # 2. Stop bot instance
                                        await bot_manager.stop_bot(bot_id)
                                        
                                        # 3. Reload from registry to get fresh config
                                        from database.panel_db import get_bot_by_id
                                        bot_info = await get_bot_by_id(bot_id)
                                        
                                        if bot_info:
                                            # 4. Start bot
                                            await bot_manager.start_bot(
                                                bot_info['id'], 
                                                bot_info['token'], 
                                                bot_info.get('type', 'receipt'), 
                                                bot_info['database_url']
                                            )
                                            # 5. Start polling
                                            new_bot = bot_manager.bots.get(bot_id)
                                            if new_bot:
                                                await polling_manager.start_polling_for_bot(bot_id, new_bot)
                                                logger.info(f"✅ Bot {bot_id} restarted successfully")
                                            else:
                                                logger.error(f"❌ Failed to restart bot {bot_id}: Bot instance not created")
                                            
                                        else:
                                            logger.error(f"❌ Failed to restart bot {bot_id}: Not found in registry")
                                            
                                        # Clear middleware cache
                                        from utils.bot_middleware import clear_modules_cache
                                        clear_modules_cache(bot_id)
                                        
                                    except ValueError:
                                        logger.error(f"Invalid payload for restart_bot: {payload}")
                                    except Exception as e:
                                        logger.error(f"Restart bot failed: {e}", exc_info=True)
                                else:
                                    logger.warning("⚠️ PollingManager not initialized, cannot restart")

                        except Exception as e:
                            logger.error(f"Error processing notification {channel}: {e}", exc_info=True)
                        finally:
                            notification_queue.task_done()
                            
                except asyncio.TimeoutError:
                    continue
    except Exception as e:
        logger.critical(f"PG Listener failed: {e}", exc_info=True)


async def process_campaign(campaign: dict, shutdown_event: asyncio.Event):
    """Process a single campaign (with per-bot database context)"""
    cid = campaign['id']
    ctype = campaign['type']
    content = campaign['content']
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            content = {}
    elif not isinstance(content, dict):
         content = {}
    
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
                await execute_broadcast(bot, bot_id, cid, content, shutdown_event)
            elif ctype == "message":
                await execute_single_message(bot, bot_id, cid, content)
            elif ctype == "raffle":
                await execute_raffle(bot, bot_id, cid, content, shutdown_event)
            else:
                logger.error(f"Unknown campaign type: {ctype}")
    except RuntimeError as e:
        logger.error(f"Campaign #{cid} database context error: {e}")
    except Exception as e:
        logger.error(f"Campaign #{cid} failed: {e}", exc_info=True)


async def scheduler(
    shutdown_event: asyncio.Event,
    notification_queue: asyncio.Queue,
    polling_manager,
):
    """Background scheduler - processes notifications + periodic fallback check"""
    # Start PG Listener task
    listener_task = asyncio.create_task(
        pg_listener(shutdown_event, notification_queue, polling_manager)
    )
    
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
                        await process_campaign(campaign_dict, shutdown_event)
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
