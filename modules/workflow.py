"""
Workflow Manager
Handles dynamic chains of steps for various processes (e.g. registration).
"""
import logging
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger(__name__)

class WorkflowManager:
    """
    Manages linear workflows (chains of steps).
    Modules can register steps into a named chain.
    """
    
    def __init__(self):
        # chain_name -> list of steps associated with it
        self.chains: Dict[str, List[Dict[str, Any]]] = {}
    
    def register_step(self, 
                      chain_name: str, 
                      step_name: str, 
                      order: int = 100, 
                      state_name: str = None,
                      module_name: str = None,
                      meta: Dict = None):
        """
        Register a step in a workflow chain.
        :param chain_name: Name of the workflow (e.g., 'registration')
        :param step_name: Unique name of the step (e.g., 'phone')
        :param order: Sort order (lower = earlier)
        :param state_name: FSM state associated with this step (optional)
        :param module_name: Name of the module owning this step (for enable/disable checks)
        :param meta: Any extra metadata
        """
        if chain_name not in self.chains:
            self.chains[chain_name] = []
            
        step = {
            "name": step_name,
            "order": order,
            "state": state_name,
            "module_name": module_name,
            "meta": meta or {}
        }
        
        # Remove existing if same name (overwrite)
        self.chains[chain_name] = [s for s in self.chains[chain_name] if s["name"] != step_name]
        
        self.chains[chain_name].append(step)
        # Sort by order
        self.chains[chain_name].sort(key=lambda x: x["order"])
        
        logger.info(f"Registered step '{step_name}' in chain '{chain_name}' at order {order} (Module: {module_name})")

    def get_steps(self, chain_name: str) -> List[Dict]:
        return self.chains.get(chain_name, [])

    def get_steps_by_module(self, module_name: str) -> List[str]:
        """Get list of step names registered by a specific module across all chains."""
        steps = []
        for chain in self.chains.values():
            for step in chain:
                if step.get("module_name") == module_name:
                    steps.append(step["name"])
        return steps

    async def get_next_step(self, chain_name: str, current_step_name: str, bot_id: int = None) -> Optional[Dict]:
        """
        Get the next ENABLED step after the current one.
        If bot_id is provided, checks if the module owning the step is enabled.
        Also respects custom pipeline order from DB if bot_id is provided.
        """
        from modules.base import module_loader
        from database.panel_db import get_pipeline_config
        
        default_steps = self.chains.get(chain_name, [])
        if not default_steps:
            return None
            
        # Determine effective step order
        steps_ordered = default_steps
        
        if bot_id:
            custom_order_names = await get_pipeline_config(bot_id, chain_name)
            if custom_order_names:
                # Reorder default steps based on custom order
                # Create a map for quick lookup
                step_map = {s["name"]: s for s in default_steps}
                new_order = []
                
                # Add customs that exist in definitions
                for name in custom_order_names:
                    if name in step_map:
                        new_order.append(step_map[name])
                
                # Add any missing steps at the end (fallback)
                for step in default_steps:
                    if step["name"] not in custom_order_names:
                        new_order.append(step)
                
                steps_ordered = new_order
        
        # Find index of current
        idx = -1
        for i, step in enumerate(steps_ordered):
            if step["name"] == current_step_name:
                idx = i
                break
        
        # Search for the next VALID step starting from idx + 1
        for i in range(idx + 1, len(steps_ordered)):
            step = steps_ordered[i]
            # Check if module is enabled
            mod_name = step.get("module_name")
            if bot_id is not None and mod_name:
                if not module_loader.is_enabled(bot_id, mod_name):
                    # Module disabled, skip this step
                    continue
            
            return step
        
        return None

    async def get_first_step(self, chain_name: str, bot_id: int = None) -> Optional[Dict]:
         from database.panel_db import get_pipeline_config
         from modules.base import module_loader
         
         default_steps = self.chains.get(chain_name, [])
         if not default_steps:
             return None
             
         steps_ordered = default_steps
         
         if bot_id:
            custom_order_names = await get_pipeline_config(bot_id, chain_name)
            if custom_order_names:
                 step_map = {s["name"]: s for s in default_steps}
                 new_order = []
                 for name in custom_order_names:
                     if name in step_map:
                         new_order.append(step_map[name])
                 for step in default_steps:
                     if step["name"] not in custom_order_names:
                         new_order.append(step)
                 steps_ordered = new_order

         # Return first enabled step
         for step in steps_ordered:
            mod_name = step.get("module_name")
            if bot_id is not None and mod_name:
                if not module_loader.is_enabled(bot_id, mod_name):
                    continue
            return step
            
         return None

# Global instance
workflow_manager = WorkflowManager()
