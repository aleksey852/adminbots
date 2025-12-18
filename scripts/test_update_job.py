
import asyncio
import sys
import os
sys.path.append(os.getcwd())

import config
from database.bot_db import bot_db_manager
from database import bot_methods
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TEST")

async def test():
    test_bot_id = 99999
    db_url = config.DATABASE_URL
    bot_db_manager.register(test_bot_id, db_url)
    await bot_db_manager.connect(test_bot_id)
    
    async with bot_methods.bot_db_context(test_bot_id):
        # Create dummy job
        job_id = await bot_methods.create_job("test_job", {"test": True})
        logger.info(f"Created job {job_id}")
        
        # Test update_job
        await bot_methods.update_job(job_id, status="processing", progress=50, details={"more": "data"})
        logger.info("Updated job")
        
        # Verify
        job = await bot_methods.get_job(job_id)
        logger.info(f"Job state: {job['status']} {job['progress']} {job['details']}")

    await bot_db_manager.close_all()

if __name__ == "__main__":
    asyncio.run(test())
