import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    print("Checking imports...")
    import database
    import database.bot_methods
    import database.methods
    import database.db
    import database.bot_db
    import admin_panel.app
    import admin_panel.routers.users
    import admin_panel.routers.campaigns
    print("Imports check passed!")
except ImportError as e:
    print(f"Import check failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error during import check: {e}")
    sys.exit(1)
