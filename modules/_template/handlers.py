"""
Template Module Handlers

Rename this class and customize for your module.
"""
from aiogram import F
from aiogram.types import Message

# Import from core package
from core.module_base import BotModule


class TemplateModule(BotModule):
    """Template module — copy and customize."""
    
    # === REQUIRED: Change these ===
    name = "_template"  # Must be unique
    version = "1.0.0"
    description = "Template module"
    
    # === OPTIONAL ===
    default_enabled = False  # Templates shouldn't auto-enable
    dependencies = []  # e.g., ["core", "registration"]
    
    # Settings shown in admin panel
    settings_schema = {
        "example_setting": {
            "type": "text",
            "label": "Example Setting",
            "default": "default value"
        }
    }
    
    # Default messages (can be overridden in panel)
    default_messages = {
        "greeting": "Hello from template!"
    }
    
    def _setup_handlers(self):
        """Register your aiogram handlers here."""
        
        # Example: button handler
        @self.router.message(F.text == "🔧 Template")
        async def template_handler(message: Message, bot_id: int = None):
            """Handle template button press."""
            if not bot_id:
                return
            
            # Get config value
            setting = self.get_config(bot_id, "example_setting", "default")
            
            await message.answer(f"Template module active! Setting: {setting}")
    
    # === OPTIONAL LIFECYCLE HOOKS ===
    
    async def on_bot_start(self, bot_id: int):
        """Called when a bot using this module starts."""
        pass
    
    async def on_bot_stop(self, bot_id: int):
        """Called when a bot stops."""
        pass


# Export instance — this is what gets registered
template_module = TemplateModule()
