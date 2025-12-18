import asyncio
import logging
import sys
import os
from unittest.mock import AsyncMock, patch
from typing import Dict, List

# Add project root to path
sys.path.append(os.getcwd())

from modules.workflow import workflow_manager
from modules.base import BotModule, module_loader

# Setup dummy modules
class ModA(BotModule):
    name = "mod_a"
    def _setup_handlers(self): pass

class ModB(BotModule):
    name = "mod_b"
    def _setup_handlers(self): pass

async def test():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("tester")
    
    # Store mocked DB state
    db_state = {
        "pipeline_config": {}, # bot_id_chain -> list
        "module_settings": {}  # bot_id_mod -> dict
    }
    
    # Register dummy modules
    module_loader.register(ModA())
    module_loader.register(ModB())
    
    # Register steps
    chain = "test_chain"
    workflow_manager.register_step(chain, "step1", order=10, module_name="mod_a")
    workflow_manager.register_step(chain, "step2", order=20, module_name="mod_b")
    workflow_manager.register_step(chain, "step3", order=30, module_name="mod_a")
    
    bot_id = 999
    
    # Mock DB functions
    async def mock_get_pipeline_config(bid, cname):
        return db_state["pipeline_config"].get(f"{bid}_{cname}", [])
        
    async def mock_set_pipeline_config(bid, cname, steps):
        db_state["pipeline_config"][f"{bid}_{cname}"] = steps

    async def mock_get_module_settings(bid, mname):
        return db_state["module_settings"].get(f"{bid}_{mname}", {})

    async def mock_set_module_settings(bid, mname, settings):
        db_state["module_settings"][f"{bid}_{mname}"] = settings

    # Apply patches
    with patch("database.panel_db.get_pipeline_config", side_effect=mock_get_pipeline_config), \
         patch("database.panel_db.get_pipeline_config", side_effect=mock_get_pipeline_config), \
         patch("database.panel_db.get_module_settings", side_effect=mock_get_module_settings), \
         patch("database.panel_db.set_module_settings", side_effect=mock_set_module_settings), \
         patch("modules.base.BotModule.save_settings", side_effect=lambda bid, s: mock_set_module_settings(bid, "mod_a", s)): # imperfect mock but ok

        # also need to patch the imports inside the functions if they import locally
        # but in my code I did `from database.panel_db import ...` inside execution methods?
        # Check workflow.py:
        # async def get_next_step(...):
        #    from database.panel_db import get_pipeline_config
        
        # Since they are imported inside function, patching 'database.panel_db.get_pipeline_config' globally works 
        # IF sys.modules has it.
        
        # Actually, `patch` works on where it is looked up.
        # Inside `workflow.py`, it does `from database.panel_db import get_pipeline_config`.
        # So we need to patch `database.panel_db.get_pipeline_config`.
        
        # NOTE: Since `workflow.py` imports it inside the function, we can patch the source `database.panel_db`.
        pass

    # Re-doing mocks to be sure they apply to the lazy imports
    # The clean way: mock the module in sys.modules or use patch(target)
    
    # Let's try simpler: directly patch the functions in database.panel_db module
    import database.panel_db
    database.panel_db.get_pipeline_config = mock_get_pipeline_config
    database.panel_db.set_pipeline_config = mock_set_pipeline_config
    database.panel_db.get_module_settings = mock_get_module_settings
    database.panel_db.set_module_settings = mock_set_module_settings

    # 1. Test Default Order
    # Mock enabled modules logic
    module_loader.set_enabled_modules(bot_id, {"mod_a", "mod_b"})
    
    step = await workflow_manager.get_first_step(chain, bot_id)
    assert step['name'] == "step1", f"Expected step1, got {step['name']}"
    
    step = await workflow_manager.get_next_step(chain, "step1", bot_id)
    assert step['name'] == "step2", f"Expected step2, got {step['name']}"
    
    logger.info("✅ Default order passed")

    # 2. Test Custom Order
    new_order = ["step3", "step1", "step2"]
    await database.panel_db.set_pipeline_config(bot_id, chain, new_order)
    
    # Verify workflow manager respects it
    step = await workflow_manager.get_first_step(chain, bot_id)
    assert step['name'] == "step3", f"Expected step3 (custom order), got {step['name']}"
    
    step = await workflow_manager.get_next_step(chain, "step3", bot_id)
    assert step['name'] == "step1", f"Expected step1 next, got {step['name']}"
    
    logger.info("✅ Custom order passed")

    # 3. Test Module Settings
    settings = {"key": "value", "number": 123}
    await database.panel_db.set_module_settings(bot_id, "mod_a", settings)
    
    # Test merge in module
    mod_a = module_loader.get_module("mod_a")
    mod_a.default_settings = {"default": "true", "key": "old"}
    
    effective = await mod_a.get_settings(bot_id)
    assert effective['key'] == "value", "DB should override default"
    assert effective['default'] == "true", "Default should remain"
    
    logger.info("✅ Settings merge passed")

    logger.info("🚀 All logic verified!")

if __name__ == "__main__":
    asyncio.run(test())
