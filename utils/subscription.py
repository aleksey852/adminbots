"""
Subscription Check Utility
Handles logic for verifying if a user is subscribed to a required Telegram channel.
Settings are read from the Registration module's configuration.
"""
import logging
from typing import Optional, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


async def get_subscription_settings(bot_id: int) -> dict:
    """
    Get subscription settings from the registration module.
    Settings are stored in the module's settings in the database.
    """
    from database.panel_db import get_module_settings
    
    settings = await get_module_settings(bot_id, "registration")
    return {
        "required": settings.get("subscription_required", "false").lower() == "true",
        "channel_id": settings.get("subscription_channel_id", ""),
        "channel_url": settings.get("subscription_channel_url", ""),
    }


async def check_subscription(
    user_id: int, 
    bot: Bot, 
    bot_id: int
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if user is subscribed to the required channel.
    
    Returns:
        Tuple[bool, Optional[str], Optional[str]]: 
        (is_subscribed, channel_id, channel_url)
    """
    sub_settings = await get_subscription_settings(bot_id)
    
    if not sub_settings["required"]:
        return True, None, None
        
    channel_id = sub_settings["channel_id"]
    channel_url = sub_settings["channel_url"]
    
    if not channel_id:
        # Configured to require subscription but no channel ID set
        logger.warning(f"Bot {bot_id}: subscription_required is true but channel_id is missing")
        return True, None, None

    try:
        member = await bot.get_chat_member(chat_id=int(channel_id), user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True, channel_id, channel_url
        # User is not subscribed
        return False, channel_id, channel_url
    except Exception as e:
        # Fail-open: if we can't check (bot not admin in channel, network error),
        # allow user through to avoid blocking everyone due to misconfiguration
        logger.warning(f"Bot {bot_id}: Subscription check failed for user {user_id}, allowing through: {e}")
        return True, channel_id, channel_url


def get_subscription_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    """Get keyboard for subscription enforcement."""
    buttons = []
    if channel_url:
        buttons.append([InlineKeyboardButton(text="📢 Подписаться", url=channel_url)])
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

