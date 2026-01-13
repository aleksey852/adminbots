"""
API Response Utilities for Admin Panel

Unified response format for all API endpoints.
"""
from typing import Any, Optional, Dict, List
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class APIResponse(BaseModel):
    """Standard API response format"""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
    errors: Optional[List[str]] = None


def success(data: Any = None, message: str = None, status_code: int = 200) -> JSONResponse:
    """Return success response"""
    return JSONResponse(
        content={
            "success": True,
            "data": data,
            "message": message
        },
        status_code=status_code
    )


def error(message: str, errors: List[str] = None, status_code: int = 400) -> JSONResponse:
    """Return error response"""
    return JSONResponse(
        content={
            "success": False,
            "message": message,
            "errors": errors or []
        },
        status_code=status_code
    )


def not_found(message: str = "Not found") -> JSONResponse:
    """Return 404 response"""
    return error(message, status_code=404)


def forbidden(message: str = "Access denied") -> JSONResponse:
    """Return 403 response"""
    return error(message, status_code=403)


def server_error(message: str = "Internal server error") -> JSONResponse:
    """Return 500 response"""
    return error(message, status_code=500)
