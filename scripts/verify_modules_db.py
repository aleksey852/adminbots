import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database.bot_db import bot_db_manager
from database import bot_methods
from modules.base import module_loader
from modules.core import core_module
from modules.registration import registration_module
from modules.receipts import receipts_module
from modules.promo import promo_module
from modules.admin import admin_module

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY")

async def main():
    logger.info("Starting verification...")
    
    # 1. Verify Imports
    logger.info("✅ Modules imported successfully")
    
    # 2. Verify DB Connection
    test_bot_id = 99999
    # Use the main DB URL for testing connectivity
    db_url = config.DATABASE_URL
    
    logger.info(f"Connecting to DB for Test Bot ID: {test_bot_id}...")
    
    try:
        # Register and connect
        bot_db_manager.register(test_bot_id, db_url)
        await bot_db_manager.connect(test_bot_id)
        logger.info("✅ BotDatabase connected")
        
        # 3. Verify Context and Methods
        async with bot_methods.bot_db_context(test_bot_id):
            logger.info("Entered bot_db_context")
            
            # Try a simple read operation
            stats = await bot_methods.get_stats()
            logger.info(f"✅ bot_methods.get_stats() success: {stats}")
            
            # Try a write operation (rollback afterwards if possible, or use benign update)
            # We'll just check if we can read settings
            settings = await bot_methods.get_all_settings()
            logger.info(f"✅ bot_methods.get_all_settings() success: {len(settings)} items")
            
    except Exception as e:
        logger.error(f"❌ DB Verification Failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await bot_db_manager.close_all()
        logger.info("DB closed")

    logger.info("🎉 Verification Complete!")

if __name__ == "__main__":
    asyncio.run(main())
