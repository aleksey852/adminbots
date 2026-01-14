"""
Bot Manager - Manages bot instances and their databases
Uses panel registry for bot configuration, per-bot databases for data
"""
import logging
import asyncio
from typing import Dict, List, Optional
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from database.bot_db import BotDatabase, bot_db_manager

logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self):
        self.bots: Dict[int, Bot] = {}  # db_bot_id -> Bot instance
        self.bot_tokens: Dict[int, str] = {}  # db_bot_id -> token
        self.bot_types: Dict[int, str] = {}  # db_bot_id -> type (receipt/promo)
        self.bot_mapping: Dict[int, int] = {}  # telegram_bot_id -> db_bot_id
        self.bot_db_urls: Dict[int, str] = {}  # db_bot_id -> database_url

    async def load_bots_from_registry(self):
        """Load active bots from panel registry and connect to their databases"""
        from database.panel_db import get_active_bots
        
        rows = await get_active_bots()
        logger.info(f"Found {len(rows)} active bots in panel registry")
        
        current_ids = set(self.bots.keys())
        new_ids = set()
        
        for row in rows:
            bot_id = row['id']
            token = row['token']
            bot_type = row.get('type', 'receipt')
            database_url = row['database_url']
            new_ids.add(bot_id)
            
            if bot_id in self.bots:
                # Check if token changed
                if self.bot_tokens.get(bot_id) != token:
                    logger.info(f"Token changed for bot {bot_id}, reloading...")
                    await self.stop_bot(bot_id)
                else:
                    # Update type just in case
                    self.bot_types[bot_id] = bot_type
                    continue
            
            await self.start_bot(bot_id, token, bot_type, database_url)
        
        # Stop removed bots
        for bot_id in current_ids - new_ids:
            logger.info(f"Bot {bot_id} is no longer active, stopping...")
            await self.stop_bot(bot_id)

    async def start_bot(self, bot_id: int, token: str, bot_type: str = 'receipt', database_url: str = None):
        """Start a bot and connect to its database"""
        try:
            # Create and connect to bot's database
            if database_url:
                bot_db_manager.register(bot_id, database_url)
                await bot_db_manager.connect(bot_id)
                self.bot_db_urls[bot_id] = database_url
            
            # Create bot instance
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            me = await bot.get_me()
            
            self.bots[bot_id] = bot
            self.bot_tokens[bot_id] = token
            self.bot_types[bot_id] = bot_type
            self.bot_mapping[me.id] = bot_id
            
            logger.info(f"Started bot {bot_id} (@{me.username}) [Type: {bot_type}]")
        except Exception as e:
            logger.error(f"Failed to start bot {bot_id}: {e}")

    async def stop_bot(self, bot_id: int):
        """Stop a bot and close its database connection"""
        if bot_id not in self.bots:
            return
        
        bot = self.bots[bot_id]
        
        try:
            # Try to remove from mapping using get_me
            try:
                me = await bot.get_me()
                if me.id in self.bot_mapping:
                    del self.bot_mapping[me.id]
            except Exception as e:
                logger.warning(f"Could not get bot info for {bot_id}: {e}")
                # Try to find mapping by iterating
                for tg_id, db_id in list(self.bot_mapping.items()):
                    if db_id == bot_id:
                        del self.bot_mapping[tg_id]
                        break
            
            # Close bot session
            try:
                await bot.session.close()
                logger.info(f"Stopped bot {bot_id}")
            except Exception as e:
                logger.error(f"Error closing bot session {bot_id}: {e}")
        finally:
            # Always clean up - even if errors occurred above
            # Close database connection
            try:
                db = bot_db_manager.get(bot_id)
                if db:
                    await db.close()
            except Exception as e:
                logger.error(f"Error closing database for bot {bot_id}: {e}")
            
            # Clean up all attributes
            self.bots.pop(bot_id, None)
            self.bot_tokens.pop(bot_id, None)
            self.bot_types.pop(bot_id, None)
            self.bot_db_urls.pop(bot_id, None)


    def get_bots(self) -> List[Bot]:
        return list(self.bots.values())

    def get_bot_id_by_token(self, token: str) -> Optional[int]:
        for bid, t in self.bot_tokens.items():
            if t == token:
                return bid
        return None

    def get_db_id(self, telegram_bot_id: int) -> Optional[int]:
        return self.bot_mapping.get(telegram_bot_id)

    def get_database(self, bot_id: int) -> Optional[BotDatabase]:
        """Get the database instance for a bot"""
        return bot_db_manager.get(bot_id)

    async def close_all(self):
        """Stop all bots and close all database connections"""
        for bot_id in list(self.bots.keys()):
            await self.stop_bot(bot_id)
        await bot_db_manager.close_all()


bot_manager = BotManager()


class PollingManager:
    """
    Manages polling tasks for multiple bots dynamically.
    Allows adding/removing bots without restarting the process.
    """
    
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.polling_tasks: Dict[int, asyncio.Task] = {}  # bot_id -> polling task
        self._shutdown = False
    
    async def start_polling_for_bot(self, bot_id: int, bot: Bot):
        """Start polling for a single bot"""
        if bot_id in self.polling_tasks:
            logger.warning(f"Polling already running for bot {bot_id}")
            return
        
        async def poll_bot():
            try:
                logger.info(f"🚀 Starting polling for bot {bot_id}")
                await self.dispatcher.start_polling(bot, polling_timeout=30)
            except asyncio.CancelledError:
                logger.info(f"🛑 Polling cancelled for bot {bot_id}")
            except Exception as e:
                logger.error(f"Polling error for bot {bot_id}: {e}")
        
        task = asyncio.create_task(poll_bot())
        self.polling_tasks[bot_id] = task
    
    async def stop_polling_for_bot(self, bot_id: int):
        """Stop polling for a single bot"""
        if bot_id not in self.polling_tasks:
            return
        
        task = self.polling_tasks.pop(bot_id)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info(f"Polling stopped for bot {bot_id}")
    
    async def start_all(self):
        """Start polling for all registered bots"""
        for bot_id, bot in bot_manager.bots.items():
            await self.start_polling_for_bot(bot_id, bot)
    
    async def add_new_bot(self, bot_id: int, bot: Bot):
        """Add a new bot to polling without restart"""
        await self.start_polling_for_bot(bot_id, bot)
        logger.info(f"✅ Bot {bot_id} added to polling dynamically")
    
    async def reload_bots(self):
        """Reload bots from registry and update polling"""
        old_ids = set(self.polling_tasks.keys())
        
        # Refresh bot manager
        await bot_manager.load_bots_from_registry()
        
        new_ids = set(bot_manager.bots.keys())
        
        # Stop removed bots
        for bot_id in old_ids - new_ids:
            await self.stop_polling_for_bot(bot_id)
        
        # Start new bots
        for bot_id in new_ids - old_ids:
            bot = bot_manager.bots.get(bot_id)
            if bot:
                await self.start_polling_for_bot(bot_id, bot)
                logger.info(f"🆕 New bot {bot_id} added to polling")
    
    async def stop_all(self):
        """Stop polling for all bots"""
        self._shutdown = True
        for bot_id in list(self.polling_tasks.keys()):
            await self.stop_polling_for_bot(bot_id)
    
    async def wait(self):
        """Wait for all polling tasks to complete"""
        if self.polling_tasks:
            await asyncio.gather(*self.polling_tasks.values(), return_exceptions=True)
