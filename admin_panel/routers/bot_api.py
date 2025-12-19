"""
Bot Connection API — Эндпоинты для подключения ботов к панели.

Этот роутер обрабатывает:
- Регистрацию новых ботов через deploy.py
- Переподключение существующих ботов
- Получение информации о подключенных ботах
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging
import json
import re
import uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bots", tags=["bot-api"])


class BotConnectRequest(BaseModel):
    """Request body for bot connection"""
    token: str
    name: str
    type: str = "custom"
    manifest: Optional[Dict] = None
    manifest_path: Optional[str] = None
    database_url: Optional[str] = None


class BotConnectResponse(BaseModel):
    """Response for successful bot connection"""
    bot_id: int
    database_url: str
    status: str = "connected"


def setup_routes():
    """Setup routes - called from app.py"""
    
    @router.post("/connect", response_model=BotConnectResponse)
    async def connect_bot(request: Request, body: BotConnectRequest):
        """
        Register a new bot with the panel.
        
        Called by deploy.py script from bot folder.
        Creates database if not provided, registers bot in panel registry.
        """
        from database.panel_db import (
            get_bot_by_token, register_bot, create_bot_database,
            update_bot, get_panel_connection
        )
        from database.bot_db import bot_db_manager
        import config
        
        # Validate token format
        if not body.token or ":" not in body.token:
            raise HTTPException(400, "Invalid bot token format")
        
        # Check if bot already exists
        existing = await get_bot_by_token(body.token)
        if existing:
            raise HTTPException(409, f"Bot already registered with ID {existing['id']}")
        
        # Create database if not provided
        if body.database_url:
            db_url = body.database_url
        else:
            # Generate database name from bot name
            safe_name = re.sub(r'[^a-z0-9_]', '', body.name.lower())[:20]
            db_name = f"bot_{safe_name}_{uuid.uuid4().hex[:6]}"
            try:
                db_url = await create_bot_database(db_name, config.DATABASE_URL)
            except Exception as e:
                logger.error(f"Failed to create database: {e}")
                raise HTTPException(500, f"Database creation failed: {e}")
        
        # Determine bot type from manifest
        bot_type = body.type
        if body.manifest:
            modules = body.manifest.get('modules', [])
            if 'receipts' in modules:
                bot_type = 'receipt'
            elif 'promo' in modules:
                bot_type = 'promo'
        
        # Register bot in panel
        try:
            bot_id = await register_bot(
                token=body.token,
                name=body.name,
                bot_type=bot_type,
                database_url=db_url,
                admin_ids=[]
            )
            
            # Update with manifest path if provided
            if body.manifest_path:
                await update_bot(bot_id, manifest_path=body.manifest_path)
            
            # Connect to bot database
            bot_db_manager.register(bot_id, db_url)
            await bot_db_manager.connect(bot_id)
            
            # Notify bot process about new bot
            async with get_panel_connection() as db:
                await db.execute("NOTIFY new_bot")
            
            logger.info(f"Connected new bot: {body.name} (ID: {bot_id})")
            
            return BotConnectResponse(
                bot_id=bot_id,
                database_url=db_url,
                status="connected"
            )
            
        except Exception as e:
            logger.error(f"Bot registration failed: {e}")
            raise HTTPException(500, f"Registration failed: {e}")
    
    @router.put("/reconnect", response_model=BotConnectResponse)
    async def reconnect_bot(request: Request, body: BotConnectRequest):
        """
        Reconnect an existing bot (update its configuration).
        
        Used when deploy.py is run again for an already registered bot.
        """
        from database.panel_db import get_bot_by_token, update_bot
        
        existing = await get_bot_by_token(body.token)
        if not existing:
            raise HTTPException(404, "Bot not found")
        
        bot_id = existing['id']
        
        # Update manifest path if provided
        updates = {}
        if body.manifest_path:
            updates['manifest_path'] = body.manifest_path
        if body.name:
            updates['name'] = body.name
        
        if updates:
            await update_bot(bot_id, **updates)
        
        logger.info(f"Reconnected bot: {body.name} (ID: {bot_id})")
        
        return BotConnectResponse(
            bot_id=bot_id,
            database_url=existing['database_url'],
            status="reconnected"
        )
    
    @router.get("/connected")
    async def list_connected_bots(request: Request):
        """List all connected bots with their status"""
        from database.panel_db import get_active_bots
        
        bots = await get_active_bots()
        
        result = []
        for bot in bots:
            result.append({
                "id": bot['id'],
                "name": bot['name'],
                "type": bot['type'],
                "is_active": bot['is_active'],
                "has_manifest": bool(bot.get('manifest_path')),
                "created_at": bot['created_at'].isoformat() if bot.get('created_at') else None
            })
        
        return {"bots": result, "total": len(result)}
    
    @router.get("/{bot_id}/manifest")
    async def get_bot_manifest(request: Request, bot_id: int):
        """Get bot manifest.json content"""
        from database.panel_db import get_bot_by_id
        import os
        
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(404, "Bot not found")
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            raise HTTPException(404, "Bot has no manifest path")
        
        manifest_file = os.path.join(manifest_path, 'manifest.json')
        if not os.path.exists(manifest_file):
            raise HTTPException(404, "manifest.json not found")
        
        with open(manifest_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @router.get("/{bot_id}/content")
    async def get_bot_content(request: Request, bot_id: int):
        """Get bot content.py as structured data for editing"""
        from utils.content_loader import list_content_keys
        
        try:
            content = list_content_keys(bot_id)
            return {"bot_id": bot_id, "content": content}
        except Exception as e:
            logger.error(f"Failed to get content for bot {bot_id}: {e}")
            raise HTTPException(500, str(e))
    
    @router.post("/{bot_id}/content")
    async def save_bot_content(request: Request, bot_id: int):
        """
        Save updated content.py for a bot.
        
        Receives content as JSON, writes to content.py file,
        and triggers content reload.
        """
        from database.panel_db import get_bot_by_id
        from utils.content_loader import reload_content
        import os
        
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(404, "Bot not found")
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            raise HTTPException(400, "Bot has no manifest path, cannot save content")
        
        content_path = os.path.join(manifest_path, 'content.py')
        
        # Get new content from request
        body = await request.json()
        content_data = body.get('content', {})
        
        # Generate Python file content
        lines = [
            '"""',
            'Bot Content — Auto-generated by Admin Panel.',
            '',
            'Warning: This file is managed by Admin Panel.',
            'Manual edits may be overwritten.',
            '"""',
            ''
        ]
        
        for key, value in content_data.items():
            if isinstance(value, str):
                # Escape triple quotes in multiline strings
                if '\n' in value:
                    escaped = value.replace('"""', '\\"\\"\\"')
                    lines.append(f'{key} = """{escaped}"""')
                else:
                    escaped = value.replace('"', '\\"')
                    lines.append(f'{key} = "{escaped}"')
            elif isinstance(value, dict):
                lines.append(f'{key} = {json.dumps(value, ensure_ascii=False, indent=4)}')
            lines.append('')
        
        # Write file
        try:
            with open(content_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            # Reload content
            reload_content(bot_id)
            
            logger.info(f"Saved content for bot {bot_id}")
            return {"status": "saved", "bot_id": bot_id}
            
        except Exception as e:
            logger.error(f"Failed to save content for bot {bot_id}: {e}")
            raise HTTPException(500, f"Failed to save: {e}")
    
    return router
