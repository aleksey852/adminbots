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
                      meta: Dict = None):
        """
        Register a step in a workflow chain.
        :param chain_name: Name of the workflow (e.g., 'registration')
        :param step_name: Unique name of the step (e.g., 'phone')
        :param order: Sort order (lower = earlier)
        :param state_name: FSM state associated with this step (optional)
        :param meta: Any extra metadata
        """
        if chain_name not in self.chains:
            self.chains[chain_name] = []
            
        step = {
            "name": step_name,
            "order": order,
            "state": state_name,
            "meta": meta or {}
        }
        
        # Remove existing if same name (overwrite)
        self.chains[chain_name] = [s for s in self.chains[chain_name] if s["name"] != step_name]
        
        self.chains[chain_name].append(step)
        # Sort by order
        self.chains[chain_name].sort(key=lambda x: x["order"])
        
        logger.info(f"Registered step '{step_name}' in chain '{chain_name}' at order {order}")

    def get_steps(self, chain_name: str) -> List[Dict]:
        return self.chains.get(chain_name, [])

    def get_next_step(self, chain_name: str, current_step_name: str) -> Optional[Dict]:
        """
        Get the next step after the current one.
        """
        steps = self.chains.get(chain_name, [])
        if not steps:
            return None
        
        # Find index of current
        idx = -1
        for i, step in enumerate(steps):
            if step["name"] == current_step_name:
                idx = i
                break
        
        if idx != -1 and idx + 1 < len(steps):
            return steps[idx + 1]
        
        return None

    def get_first_step(self, chain_name: str) -> Optional[Dict]:
         steps = self.chains.get(chain_name, [])
         return steps[0] if steps else None

# Global instance
workflow_manager = WorkflowManager()
