"""
Workflow Manager
Handles dynamic chains of steps for various processes (e.g. registration).
"""
import logging
from typing import Dict, List, Optional, Any
from copy import deepcopy

logger = logging.getLogger(__name__)

class WorkflowManager:
    """
    Manages workflows with a "Lake" of steps.
    Steps are registered globally and can be used in different chains.
    """
    
    def __init__(self):
        # Global registry of all available steps
        # step_id -> step_definition
        self.step_registry: Dict[str, Dict[str, Any]] = {}
        
        # Default configurations for chains (fallback if not in DB)
        # chain_name -> list of step_ids
        self.default_chains: Dict[str, List[str]] = {}
    
    def register_step(self, 
                      step_id: str,
                      name: str,
                      module_name: str,
                      state_name: str = None,
                      description: str = "",
                      meta: Dict = None):
        """
        Register a step definition in the global pool.
        :param step_id: Unique identifier (e.g., 'registration.phone')
        :param name: Human readable name
        :param module_name: Module owning this step
        :param state_name: FSM state associated with this step
        :param description: Short description for UI
        """
        self.step_registry[step_id] = {
            "id": step_id,
            "name": name,
            "module_name": module_name,
            "state": state_name,
            "description": description,
            "meta": meta or {}
        }
        logger.info(f"Registered step definition '{step_id}' ({name}) from module {module_name}")

    def register_default_chain(self, chain_name: str, step_ids: List[str]):
        """Define default sequence for a chain"""
        self.default_chains[chain_name] = step_ids
        
    def get_all_steps(self) -> List[Dict]:
        """Get list of all registered steps"""
        return list(self.step_registry.values())
        
    def get_chain_steps_sync(self, chain_name: str) -> List[Dict]:
        """Get default steps for a chain (sync helper for initial load)"""
        step_ids = self.default_chains.get(chain_name, [])
        steps = []
        for sid in step_ids:
            if sid in self.step_registry:
                steps.append(self.step_registry[sid])
        return steps

    async def get_next_step(self, chain_name: str, current_step_id: str, bot_id: int) -> Optional[Dict]:
        """
        Get the next ENABLED step ID in the chain for a specific bot.
        """
        from database.panel_db import get_pipeline_config
        from modules.base import module_loader
        
        # 1. Get effective pipeline config
        # Default
        step_ids = self.default_chains.get(chain_name, [])
        
        # Custom override
        custom_ids = await get_pipeline_config(bot_id, chain_name)
        if custom_ids:
            step_ids = custom_ids
            
        # 2. Find current position
        if current_step_id not in step_ids:
            # Current step is not in the active pipeline? 
            # Could be it was removed. Fallback or exit?
            # Let's try to find it in the registry to see if it makes sense to continue?
            # For robustness, we can't really guess where we are if we are off-track.
            # But maybe we just started? If current_step_id is None?
            pass
            
        idx = -1
        try:
            idx = step_ids.index(current_step_id)
        except ValueError:
            pass
            
        # 3. Search for next ENABLED step
        for i in range(idx + 1, len(step_ids)):
            next_sid = step_ids[i]
            step_def = self.step_registry.get(next_sid)
            
            if not step_def:
                continue
                
            # Check module enabled status
            mod_name = step_def.get("module_name")
            if mod_name and not module_loader.is_enabled(bot_id, mod_name):
                continue
                
            return step_def
            
        return None

# Global instance
workflow_manager = WorkflowManager()
