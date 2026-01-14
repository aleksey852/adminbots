
import importlib.util
import os
import sys

def check_load(path, bot_id=2):
    print(f"Checking path: {path}")
    content_path = os.path.join(path, 'content.py')
    if not os.path.exists(content_path):
        print(f"❌ File not found: {content_path}")
        return

    try:
        spec = importlib.util.spec_from_file_location(
            f"content_{bot_id}", content_path
        )
        if spec is None:
            print("❌ Spec failure")
            return
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        print("✅ Module loaded successfully")
        
        # Check keys
        keys = ['FAQ_HOW_PROMO', 'FAQ_ITEMS', 'WELCOME_NEW']
        for key in keys:
            val = getattr(module, key, None)
            if val:
                print(f"✅ Found {key}: {str(val)[:50]}...")
            else:
                print(f"❌ Missing {key}")
                
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_load("/Users/aleksey/Documents/GitHub/adminbots/bots/love_is")
