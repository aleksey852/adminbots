"""
Admin Bots Platform - Main Entry Point
Features: PostgreSQL, Redis FSM, Rate limiting, Broadcasts, Raffles
+ PostgreSQL NOTIFY/LISTEN for instant campaign execution
+ Multi-Bot Support with per-bot databases
"""
import asyncio
import logging
import signal
import sys

from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

import config
from database.panel_db import init_panel_db, close_panel_db
from database.bot_db import bot_db_manager
from bot_manager import bot_manager, PollingManager
from core.module_loader import module_loader
from utils.bot_middleware import BotMiddleware, get_enabled_modules
from utils.rate_limiter import init_rate_limiter, close_rate_limiter
from scheduler import scheduler

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global Dispatcher
redis = Redis.from_url(config.REDIS_URL)
storage = RedisStorage(redis=redis)
dp = Dispatcher(storage=storage)

shutdown_event = asyncio.Event()
notification_queue = asyncio.Queue()
polling_manager = None  # Will be initialized in on_startup


async def on_startup():
    """Initialize databases, modules, and bot manager"""
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
    module_loader.discover_modules()
    
    # Include Routers from modules
    for module in module_loader.get_all_modules():
        dp.include_router(module.get_router())
    
    # Add Middleware
    dp.update.middleware(BotMiddleware())
    
    # Preload enabled modules for all bots (populates cache for middleware)
    for bot_id in bot_manager.bots.keys():
        await get_enabled_modules(bot_id)
        logger.info(f"Preloaded modules for bot {bot_id}")
    
    # Initialize Polling Manager
    global polling_manager
    polling_manager = PollingManager(dp)
    # Attach to bot_manager so routers can access it
    bot_manager.polling_manager = polling_manager
    
    logger.info("Bot started")


async def on_shutdown():
    """Cleanup all resources"""
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
    """Main entry point"""
    # Signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown()))

    try:
        await on_startup()
        bots = bot_manager.get_bots()
        
        if bots:
            # Start scheduler as background task
            asyncio.create_task(scheduler(shutdown_event, notification_queue, polling_manager))
            
            # Use PollingManager for dynamic bot management
            await polling_manager.start_all()
            await polling_manager.wait()
        else:
            logger.warning("No bots found. Starting scheduler and waiting for new bots...")
            # Start scheduler to listen for new bots
            asyncio.create_task(scheduler(shutdown_event, notification_queue, polling_manager))
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
