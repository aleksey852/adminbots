import logging
import asyncio
from typing import Dict, List, Optional
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from database import methods

logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        self.bots: Dict[int, Bot] = {}  # db_bot_id -> Bot instance
        self.bot_tokens: Dict[int, str] = {} # db_bot_id -> token
        self.bot_types: Dict[int, str] = {} # db_bot_id -> type (receipt/promo)
        self.bot_mapping: Dict[int, int] = {} # telegram_bot_id -> db_bot_id

    async def load_bots(self):
        """Load active bots from database"""
        rows = await methods.get_active_bots()
        logger.info(f"Found {len(rows)} active bots in database")
        
        current_ids = set(self.bots.keys())
        new_ids = set()
        
        for row in rows:
            bot_id = row['id']
            token = row['token']
            bot_type = row.get('type', 'receipt')
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
            
            await self.start_bot(bot_id, token, bot_type)
        
        # Stop removed bots
        for bot_id in current_ids - new_ids:
            logger.info(f"Bot {bot_id} is no longer active, stopping...")
            await self.stop_bot(bot_id)

    async def start_bot(self, bot_id: int, token: str, bot_type: str = 'receipt'):
        try:
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
        if bot_id in self.bots:
            bot = self.bots[bot_id]
            try:
                await bot.session.close()
                # Remove from mapping
                # We need to find the key for this value, simplified since we have bot object
                # But better to iterate or store reverse mapping if needed. 
                # For now just clear if valid.
                pass 
            except Exception as e:
                logger.error(f"Error closing bot {bot_id}: {e}")
            del self.bots[bot_id]
            del self.bot_tokens[bot_id]
            if bot_id in self.bot_types:
                del self.bot_types[bot_id]

    def get_bots(self) -> List[Bot]:
        return list(self.bots.values())

    def get_bot_id_by_token(self, token: str) -> Optional[int]:
        for bid, t in self.bot_tokens.items():
            if t == token:
                return bid
        return None

    def get_db_id(self, telegram_bot_id: int) -> Optional[int]:
        return self.bot_mapping.get(telegram_bot_id)

bot_manager = BotManager()
