"""
Subscription Module - Checks user subscription to a channel
"""
from typing import Dict, Any
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import F

from modules.base import BotModule
from modules.workflow import workflow_manager
from utils.subscription import check_subscription, get_subscription_keyboard
from utils.config_manager import config_manager
import config

class SubscriptionState(StatesGroup):
    check = State()

class SubscriptionModule(BotModule):
    """
    Module for checking channel subscription.
    """
    
    name = "subscription"
    version = "1.0.0"
    description = "Проверка подписки на канал"
    default_enabled = False
    
    settings_schema = {
        "SUBSCRIPTION_REQUIRED": {
            "type": "checkbox",
            "label": "Требовать подписку",
            "default": "false",
            "required": False
        },
        "SUBSCRIPTION_CHANNEL_ID": {
            "type": "text",
            "label": "ID канала (напр. -100...)",
            "default": "",
            "required": False
        },
        "SUBSCRIPTION_CHANNEL_URL": {
            "type": "text",
            "label": "Ссылка на канал",
            "default": "",
            "required": False
        }
    }
    
    default_messages = {
        "sub_check_success": "✅ Подписка подтверждена!",
        "sub_check_fail": "❌ Вы ещё не подписаны на канал!",
        "sub_warning": "⚠️ Для участия в акции необходимо подписаться на наш канал!",
    }
    
    def _setup_handlers(self):
        # 1. Register Workflow Step
        workflow_manager.register_step(
            step_id="subscription.check",
            name="Проверка подписки",
            module_name=self.name,
            state_name=SubscriptionState.check,
            description="Блокирует, пока пользователь не подпишется"
        )
        
        # 2. Handler: Entering the step (Triggered by transition)
        @self.router.message(SubscriptionState.check)
        async def process_subscription_check(message: Message, state: FSMContext, bot_id: int = None):
            await self._run_check(message, state, bot_id)

        # 3. Handler: "I Subscribed" callback
        @self.router.callback_query(F.data == "check_subscription", SubscriptionState.check)
        async def process_callback_check(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            await callback.answer()
            await self._run_check(callback.message, state, bot_id, is_callback=True)

    async def _run_check(self, message: Message, state: FSMContext, bot_id: int, is_callback: bool = False):
        """Re-usable check logic"""
        is_sub, _, channel_url = await check_subscription(message.chat.id, message.bot, bot_id)
        
        if is_sub:
            # Pass! Move to next step
            if is_callback:
                msg = config_manager.get_message('sub_check_success', self.default_messages['sub_check_success'], bot_id=bot_id)
                await message.answer(msg)
            
            # Find next step
            next_step = await workflow_manager.get_next_step("registration", "subscription.check", bot_id)
            if next_step and next_step.get("state"):
                 # We need to resolve the state. 
                 # Since we only store string 'state_name' in registry usually, or State object.
                 # In this file we registered State object directly.
                 # But if we get it back from registry/DB it might be serialized.
                 # For now, let's assume we are in same process and object persists or we handle it.
                 # Note: Ideally we should soft-resolve states.
                 
                 await state.set_state(next_step["state"])
                 
                 # Optional: If the next step is waiting for input (like Phone), 
                 # we should prompt the user? Or let them type?
                 # Ideally, we should "execute" the entry logic of the next step.
                 # But aiogram FSM waits for user input.
                 # Simple hack: Ask user to continue or send prompt if possible.
                 
                 # For "Phone", we usually need to send a prompt. 
                 # We can trigger it manually or if the module supports efficient entry.
                 # Let's just notify user to continue.
                 pass
            else:
                 # End of flow?
                 await state.clear()
                 
        else:
            # Fail. Show warning.
            msg = config_manager.get_message('sub_warning', self.default_messages['sub_warning'], bot_id=bot_id)
            await message.answer(msg, reply_markup=get_subscription_keyboard(channel_url))

subscription_module = SubscriptionModule()
