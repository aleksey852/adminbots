"""
Subscription Check Utility
Handles logic for verifying if a user is subscribed to a required Telegram channel.
"""
import logging
from typing import Optional, Tuple
from aiogram import Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from utils.config_manager import config_manager

logger = logging.getLogger(__name__)

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
    subscription_required = config_manager.get_setting('SUBSCRIPTION_REQUIRED', 'false', bot_id=bot_id)
    
    if subscription_required.lower() != 'true':
        return True, None, None
        
    channel_id = config_manager.get_setting('SUBSCRIPTION_CHANNEL_ID', '', bot_id=bot_id)
    channel_url = config_manager.get_setting('SUBSCRIPTION_CHANNEL_URL', '', bot_id=bot_id)
    
    if not channel_id:
        # Configured to require subscription but no channel ID set
        logger.warning(f"Bot {bot_id}: SUBSCRIPTION_REQUIRED is true but CHANNEL_ID is missing")
        return True, None, None

    try:
        member = await bot.get_chat_member(chat_id=int(channel_id), user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True, channel_id, channel_url
    except Exception as e:
        logger.warning(f"Bot {bot_id}: Subscription check failed for user {user_id}: {e}")
        # If we can't check (e.g. bot not admin), we might default to allowing or blocking.
        # Safest for user experience is to allow or show specific error, but here we return False to enforce check if possible.
        # However, if bot is not admin in channel, this will always fail.
        pass
        
    return False, channel_id, channel_url

def get_subscription_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    """Get keyboard for subscription enforcement."""
    buttons = []
    if channel_url:
        buttons.append([InlineKeyboardButton(text="📢 Подписаться", url=channel_url)])
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
