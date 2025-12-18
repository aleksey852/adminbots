"""
Campaign Utilities - Shared functions for campaign execution
"""
import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from database import bot_methods
from database.panel_db import get_bot_by_id
import config

logger = logging.getLogger(__name__)


async def send_message_with_retry(
    bot: Bot,
    telegram_id: int,
    content: dict,
    *,
    db_user_id: Optional[int] = None,
    bot_db_id: Optional[int] = None,
    max_retries: int = 3,
) -> bool:
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
                text = str(content.get("text") or "")
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
            await asyncio.sleep(0.5 * (2 ** attempt))  # Exponential backoff
    return False


async def notify_admins(bot: Bot, bot_id: int, report: str):
    """Send report to all admins (bot-specific plus global)"""
    bot_info = await get_bot_by_id(bot_id) if bot_id else None
    bot_admins = bot_info.get('admin_ids', []) if bot_info else []
    all_admins = set(config.ADMIN_IDS) | set(bot_admins or [])
    
    for admin_id in all_admins:
        try:
            await bot.send_message(admin_id, report)
        except Exception:
            pass
