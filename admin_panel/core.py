"""
Admin Panel Core - Shared configuration and utilities
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from fastapi import Request
from fastapi.templating import Jinja2Templates


@dataclass
class RouterConfig:
    """Configuration object for router setup - avoids passing many arguments"""
    templates: Jinja2Templates
    get_current_user: Callable
    verify_csrf_token: Callable
    get_template_context: Callable
    require_superadmin: Optional[Callable] = None
    uploads_dir: Optional[Path] = None
    base_dir: Optional[Path] = None
    
    def context(self, request: Request, **kwargs) -> Dict[str, Any]:
        """Shorthand for get_template_context"""
        return self.get_template_context(request, **kwargs)
