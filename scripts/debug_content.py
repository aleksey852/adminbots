
import asyncio
import sys
import os
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.panel_db import init_panel_db, get_active_bots, get_bot_by_id
from database.bot_db import bot_db_manager
from utils.config_manager import config_manager
from utils.content_loader import get_bot_content
import config

async def main():
    await init_panel_db(config.PANEL_DATABASE_URL)
    
    # 1. List Bots
    bots = await get_active_bots()
    print(f"\nFound {len(bots)} active bots:")
    for b in bots:
        print(f"[{b['id']}] {b['name']} (@{b.get('username', 'unknown')}) - Type: {b.get('type')}")
    
    args = sys.argv[1:]
    bot_id = None
    
    # Check for ID in args
    for arg in args:
        if arg.isdigit():
            bot_id = int(arg)
            break
            
    if not bot_id:
        bot_id_input = input("\nEnter Bot ID to debug: ")
        try:
            bot_id = int(bot_id_input)
        except:
            print("Invalid ID")
            return

    bot = await get_bot_by_id(bot_id)
    if not bot:
        print("Bot not found!")
        return
        
    print(f"\nDebugging Bot: {bot['name']} (ID: {bot_id})")
    print(f"Database URL: {bot['database_url']}")
    
    # 2. Connect to Bot DB
    bot_db_manager.register(bot_id, bot['database_url'])
    await bot_db_manager.connect(bot_id)
    
    # 3. Load DB Messages
    db_messages = {}
    async with bot_db_manager.get(bot_id).get_connection() as conn:
        rows = await conn.fetch("SELECT key, text FROM messages")
        for r in rows:
            db_messages[r['key']] = r['text']
            
    print(f"\n[DATABASE] Messages Table ({len(db_messages)} items):")
    for k, v in db_messages.items():
        print(f"  - {k}: {v[:50]}...")

    # 4. Load File Content
    print("\n[FILE] loading content.py...")
    try:
        content_module = get_bot_content(bot_id)
        file_content = {}
        for key in dir(content_module):
            if key.startswith("_"): continue
            val = getattr(content_module, key)
            if isinstance(val, str):
                file_content[key] = val
        
        print(f"Loaded {len(file_content)} keys from content.py")
    except Exception as e:
        print(f"Error loading content.py: {e}")
        file_content = {}

    # 5. Check Conflicts
    print("\n[CONFLICT CHECK]")
    conflicts = []
    for key, file_val in file_content.items():
        if key in db_messages:
            db_val = db_messages[key]
            if str(db_val) != str(file_val):
                conflicts.append(key)
                print(f"🔴 CONFLICT: {key}")
                print(f"   [DB]   {db_val[:50]}...")
                print(f"   [FILE] {file_val[:50]}...")
            else:
                 print(f"🟢 MATCH: {key} (DB has same value)")
        else:
            # print(f"⚪️ FILE ONLY: {key}")
            pass
            
    if conflicts:
        print(f"\n⚠️ FOUND {len(conflicts)} KEYS where DB overrides File.")
        print("To fix, run this script with --fix flag to DELETE these keys from DB so File is used.")
        
        if "--fix" in sys.argv:
            confirm = input(f"Delete {len(conflicts)} keys from DB? (y/n): ")
            if confirm.lower() == 'y':
                async with bot_db_manager.get(bot_id).get_connection() as conn:
                    for key in conflicts:
                        await conn.execute("DELETE FROM messages WHERE key = $1", key)
                print("✅ Deleted from DB. Now File content will be used.")
    else:
        print("\n✅ No conflicts found. File content should appear correctly unless DB has extra keys.")

if __name__ == "__main__":
    asyncio.run(main())
