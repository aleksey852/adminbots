import logging
import os
import asyncio
from pathlib import Path
from database import add_promo_codes_bulk
from bot_manager import bot_manager
from aiogram import Bot
import config

logger = logging.getLogger(__name__)

async def process_promo_import(file_path: str, bot_id: int):
    """
    Background task to process promo code import.
    """
    logger.info(f"Starting background import for Bot {bot_id} from {file_path}")
    count = 0
    try:
        # 1. Process with generator
        def file_line_generator(path):
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    yield line.strip()

        count = await add_promo_codes_bulk(bot_id, file_line_generator(file_path))
        logger.info(f"Import finished. Added {count} codes.")
        
        # 2. Notify Admins
        bot_instance = bot_manager.bots.get(bot_id)
        if bot_instance:
            msg = f"✅ <b>Импорт завершен!</b>\n\nДобавлено кодов: {count}"
            for admin_id in config.ADMIN_IDS:
                try:
                    await bot_instance.send_message(admin_id, msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Import failed: {e}")
        # Notify failure
        bot_instance = bot_manager.bots.get(bot_id)
        if bot_instance:
            error_msg = f"❌ <b>Ошибка импорта</b>\n\n{str(e)}"
            for admin_id in config.ADMIN_IDS:
                try:
                    await bot_instance.send_message(admin_id, error_msg, parse_mode="HTML")
                except:
                    pass
    finally:
        # 3. Cleanup
        try:
            os.remove(file_path)
            logger.info(f"Deleted temp file {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete temp file: {e}")
