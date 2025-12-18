import logging
import os
import asyncio
import json
from pathlib import Path
import sys

# Ensure root path is in sys.path for standalone imports if needed
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from database.bot_methods import add_promo_codes, create_job, update_job, bot_db_context
from bot_manager import bot_manager
from aiogram import Bot
import config

logger = logging.getLogger(__name__)

async def process_promo_import(file_path: str, bot_id: int, job_id: int = None):
    """
    Background task to process promo code import with job tracking.
    """
    logger.info(f"Starting background import for Bot {bot_id} from {file_path}")
    
    # We need to get bot info to connect to DB if not connected
    from database.bot_db import bot_db_manager
    from database.panel_db import get_bot_by_id
    
    # Ensure database connection exists
    if not bot_db_manager.get(bot_id):
        bot_info = await get_bot_by_id(bot_id)
        if not bot_info:
            logger.error(f"Bot {bot_id} not found for import")
            return
        bot_db_manager.register(bot_id, bot_info['database_url'])
        await bot_db_manager.connect(bot_id)

    async with bot_db_context(bot_id):
        if not job_id:
            job_id = await create_job('import_promo', {"file": os.path.basename(file_path)})
        
        await update_job(job_id, status='processing', progress=0)
        
        count = 0
        total_lines = 0
        processed_lines = 0
        
        try:
            # Count lines for progress
            with open(file_path, 'rb') as f:
                total_lines = sum(1 for _ in f)
            
            await update_job(job_id, details={"total_lines": total_lines})

            # Process in chunks
            CHUNK_SIZE = 50000
            current_chunk = []
            
            def chunk_generator():
                nonlocal processed_lines, current_chunk
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        if line.strip():
                            current_chunk.append(line.strip())
                        processed_lines += 1
                        
                        if len(current_chunk) >= CHUNK_SIZE:
                            yield current_chunk
                            current_chunk = []
                    
                    if current_chunk:
                        yield current_chunk

            for chunk_codes in chunk_generator():
                added = await add_promo_codes(chunk_codes)
                count += added
                
                # Update progress
                progress = int((processed_lines / total_lines) * 100) if total_lines else 0
                await update_job(job_id, progress=progress, details={"processed": processed_lines, "added": count})
                # Sleep briefly to yield event loop if needed
                await asyncio.sleep(0.01)

            # Success
            await update_job(job_id, status='completed', progress=100, details={"processed": processed_lines, "added": count})
            logger.info(f"Import finished. Added {count} codes.")
            
            # Notify Admins
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
            await update_job(job_id, status='failed', details={"error": str(e)})
            
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
            # Cleanup
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Failed to delete temp file: {e}")
