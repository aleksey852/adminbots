"""
Single Message Campaign Execution
"""
import logging

from aiogram import Bot

from database import bot_methods
from database.bot_methods import get_user_detail
from .utils import send_message_with_retry

logger = logging.getLogger(__name__)


async def execute_single_message(
    bot: Bot,
    bot_id: int,
    campaign_id: int,
    content: dict,
):
    """Send message to a single user"""
    # Fix: content might have user_id (local DB primary key) instead of telegram_id
    user_id = content.get("user_id")
    telegram_id = content.get("telegram_id")
    
    # If we only have user_id, we MUST fetch telegram_id from the DB
    if user_id and not telegram_id:
        user_data = await get_user_detail(user_id)
        if user_data:
            telegram_id = user_data['telegram_id']
        else:
            logger.error(f"Single message #{campaign_id} failed: User #{user_id} not found")
            await bot_methods.mark_campaign_completed(campaign_id, 0, 1)
            return

    if telegram_id:
        success = await send_message_with_retry(
            bot,
            telegram_id,
            content,
            db_user_id=user_id,
            bot_db_id=bot_id,
        )
        await bot_methods.mark_campaign_completed(campaign_id, 1 if success else 0, 0 if success else 1)
    else:
        logger.error(f"Single message #{campaign_id} failed: No recipient ID")
        await bot_methods.mark_campaign_completed(campaign_id, 0, 1)
