import logging
import os
import asyncio
import json
from pathlib import Path
from database import add_promo_codes_bulk, create_job, update_job
from bot_manager import bot_manager
from aiogram import Bot
import config

logger = logging.getLogger(__name__)

async def process_promo_import(file_path: str, bot_id: int):
    """
    Background task to process promo code import with job tracking.
    """
    logger.info(f"Starting background import for Bot {bot_id} from {file_path}")
    
    # 1. Create Job
    job_id = await create_job(bot_id, 'import_promo', {"file": os.path.basename(file_path)})
    
    await update_job(job_id, status='processing', progress=0)
    
    count = 0
    total_lines = 0
    
    try:
        # 2. Count lines for progress
        with open(file_path, 'rb') as f:
            total_lines = sum(1 for _ in f)
        
        await update_job(job_id, details={"total_lines": total_lines})

        # 3. Process in chunks
        CHUNK_SIZE = 50000
        processed_lines = 0
        current_chunk = []
        
        def chunk_generator():
            nonlocal processed_lines, current_chunk, count
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    current_chunk.append(line.strip())
                    processed_lines += 1
                    
                    if len(current_chunk) >= CHUNK_SIZE:
                        yield current_chunk
                        current_chunk = []
                
                if current_chunk:
                    yield current_chunk

        for chunk_codes in chunk_generator():
            added = await add_promo_codes_bulk(bot_id, chunk_codes)
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
