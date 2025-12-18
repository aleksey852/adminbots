"""External API client for receipt validation"""
import aiohttp
import asyncio
import logging
import config

logger = logging.getLogger(__name__)
_session = None
_session_lock = asyncio.Lock()


async def init_api_client():
    """Initialize the API client session (call once at startup)."""
    global _session
    if _session is None:
        _session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=20),
            timeout=aiohttp.ClientTimeout(total=30, connect=10)
        )


async def close_api_client():
    """Close the API client session (call at shutdown)."""
    global _session
    if _session:
        await _session.close()
        _session = None


async def _ensure_session():
    """Ensure session is initialized with thread-safe lock."""
    global _session
    if _session is None:
        async with _session_lock:
            # Double-check after acquiring lock
            if _session is None:
                await init_api_client()


async def check_receipt(qr_file=None, qr_raw: str = None, user_id: int = None) -> dict:
    """Validate receipt via proverkacheka.com API"""
    if not config.PROVERKA_CHEKA_TOKEN:
        return {"code": -1, "message": "API token not configured"}
    
    await _ensure_session()
    
    try:
        data = aiohttp.FormData()
        data.add_field("token", config.PROVERKA_CHEKA_TOKEN)
        if user_id:
            data.add_field("userdata_telegram_id", str(user_id))
        
        if qr_raw:
            if len(qr_raw) > 1000:
                return {"code": 0, "message": "QR data too long"}
            data.add_field("qrraw", qr_raw)
        elif qr_file:
            data.add_field("qrfile", qr_file, filename="qr.jpg", content_type="image/jpeg")
        else:
            return {"code": 0, "message": "No QR data provided"}
        
        async with _session.post(config.PROVERKA_CHEKA_URL, data=data) as resp:
            if resp.status != 200:
                return {"code": -1, "message": f"HTTP {resp.status}"}
            return await resp.json()
            
    except asyncio.TimeoutError:
        return {"code": -1, "message": "Timeout"}
    except Exception as e:
        logger.error(f"API error: {e}")
        return {"code": -1, "message": str(e)}
