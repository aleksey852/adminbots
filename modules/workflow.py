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

    def get_next_step(self, chain_name: str, current_step_name: str, bot_id: int = None) -> Optional[Dict]:
        """
        Get the next ENABLED step after the current one.
        If bot_id is provided, checks if the module owning the step is enabled.
        """
        from modules.base import module_loader
        
        steps = self.chains.get(chain_name, [])
        if not steps:
            return None
        
        # Find index of current
        idx = -1
        for i, step in enumerate(steps):
            if step["name"] == current_step_name:
                idx = i
                break
        
        # Search for the next VALID step starting from idx + 1
        for i in range(idx + 1, len(steps)):
            step = steps[i]
            # Check if module is enabled
            mod_name = step.get("module_name")
            if bot_id is not None and mod_name:
                if not module_loader.is_enabled(bot_id, mod_name):
                    # Module disabled, skip this step
                    continue
            
            return step
        
        return None

    def get_first_step(self, chain_name: str) -> Optional[Dict]:
         steps = self.chains.get(chain_name, [])
         return steps[0] if steps else None

# Global instance
workflow_manager = WorkflowManager()
