
import asyncio
import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.getcwd())

# Mock config
os.environ["BOT_TOKEN"] = "123:test"
os.environ["ADMIN_IDS"] = "12345"
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
os.environ["REDIS_URL"] = "redis://localhost"
os.environ["LOG_LEVEL"] = "ERROR"

try:
    import config
    from bot_manager import bot_manager
    from modules.base import module_loader
    from modules.core import core_module
    from modules.registration import registration_module
    from modules.receipts import receipts_module
    from modules.promo import promo_module
    from modules.admin import admin_module
    
    # Check imports of routers
    from admin_panel.routers import auth, bots, users, campaigns, settings, system

    print("Imports success.")

    async def verify_modules():
        print("Verifying module registration...")
        # Mock registration
        module_loader.register(core_module)
        module_loader.register(registration_module)
        module_loader.register(receipts_module)
        module_loader.register(promo_module)
        module_loader.register(admin_module)
        
        modules = module_loader.get_all_modules()
        if len(modules) != 5:
            print(f"Error: Expected 5 modules, got {len(modules)}")
            sys.exit(1)
        
        print("Modules registered successfully.")
        
        for mod in modules:
            router = mod.get_router()
            if not router:
                print(f"Error: Module {mod.name} has no router")
                sys.exit(1)
        
        print("All module routers accessible.")

    asyncio.run(verify_modules())
    print("Verification script finished successfully.")

except Exception as e:
    print(f"Verification FAILED: {e}")
    sys.exit(1)
