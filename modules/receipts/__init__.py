"""
Receipts Module - Receipt upload and validation
"""
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import io
import logging

from modules.base import BotModule
from utils.states import ReceiptSubmission
from utils.config_manager import config_manager
from keyboards import get_main_keyboard, get_cancel_keyboard, get_receipt_continue_keyboard, get_support_keyboard
from utils.api import check_receipt
from utils.rate_limiter import check_rate_limit, increment_rate_limit
from database import add_receipt, get_user_with_stats, is_receipt_exists, get_user_tickets_count, update_username
import config

logger = logging.getLogger(__name__)


class ReceiptsModule(BotModule):
    """Receipt upload and validation module"""
    
    name = "receipts"
    version = "1.0.0"
    description = "Модуль загрузки и проверки чеков"
    default_enabled = True
    dependencies = ["registration"]  # Requires registration module
    
    default_settings = {
        "TARGET_KEYWORDS": "чипсы,buster,vibe",
        "EXCLUDED_KEYWORDS": "mosk",
        "MAX_FILE_SIZE_MB": 5,
    }
    
    default_messages = {
        "upload_instruction": "📸 Отправьте фото QR-кода с чека\n\nВаших билетов: {count}\n\n💡 QR-код должен быть чётким и полностью в кадре",
        "scanning": "⏳ Сканирую QR... (3 сек)",
        "file_too_big": "❌ Файл слишком большой. Максимум 5MB.",
        "processing_error": "⚠️ Ошибка обработки. Попробуйте ещё раз",
        "check_failed": "⚠️ Не удалось проверить чек. Попробуйте ещё раз.",
        "scan_failed": "🔍 Не удалось распознать чек\n\n• Сфотографируйте ближе\n• Улучшите освещение\n\n💡 Свежий чек? Подождите 5-10 минут",
        "receipt_no_product": "😔 В чеке нет акционных товаров",
        "receipt_duplicate": "ℹ️ Этот чек уже загружен",
        "receipt_first": "🎉 Поздравляем с первым чеком!\n\nВы в розыгрыше! Загружайте ещё 🎯",
        "receipt_valid": "✅ Чек принят!\n\nВсего билетов: {count} 🎯",
    }
    
    def _get_keywords(self, bot_id: int, key: str) -> list:
        """Get keywords from settings"""
        keywords_str = config_manager.get_setting(
            key, 
            self.default_settings.get(key, ""),
            bot_id=bot_id
        )
        return [kw.strip().lower() for kw in keywords_str.split(',') if kw.strip()]
    
    def _setup_handlers(self):
        """Setup receipt handlers"""
        
        @self.router.message(F.text == "🧾 Загрузить чек")
        @self.router.message(F.text == "🧾 Ещё чек")
        async def start_receipt_upload(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id: return
            
            if not config.is_promo_active():
                msg = config_manager.get_message('promo_ended', "🏁 Акция завершена", bot_id=bot_id)
                await message.answer(msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id)))
                return
            
            user = await get_user_with_stats(message.from_user.id, bot_id)
            if not user:
                await message.answer("Сначала зарегистрируйтесь: /start")
                return
            
            if message.from_user.username != user.get('username'):
                await update_username(message.from_user.id, message.from_user.username or "", bot_id)
            
            allowed, limit_msg = await check_rate_limit(message.from_user.id)
            if not allowed:
                await message.answer(limit_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id)))
                return
            
            await state.update_data(user_db_id=user['id'], bot_id=bot_id)
            
            tickets_count = user.get('total_tickets', user['valid_receipts'])
            instruction = config_manager.get_message(
                'upload_instruction',
                self.default_messages['upload_instruction'],
                bot_id=bot_id
            ).format(count=tickets_count)
            
            await message.answer(instruction, reply_markup=get_cancel_keyboard())
            await state.set_state(ReceiptSubmission.upload_qr)
        
        @self.router.message(ReceiptSubmission.upload_qr, F.photo)
        async def process_receipt_photo(message: Message, state: FSMContext, bot: Bot, bot_id: int = None):
            if not bot_id: return
            
            allowed, limit_msg = await check_rate_limit(message.from_user.id)
            if not allowed:
                await message.answer(limit_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id)))
                await state.clear()
                return
            
            scanning_msg = config_manager.get_message('scanning', self.default_messages['scanning'], bot_id=bot_id)
            processing_msg = await message.answer(scanning_msg)
            
            photo = message.photo[-1]
            max_size = int(self.default_settings.get('MAX_FILE_SIZE_MB', 5)) * 1024 * 1024
            
            if photo.file_size and photo.file_size > max_size:
                msg = config_manager.get_message('file_too_big', self.default_messages['file_too_big'], bot_id=bot_id)
                await processing_msg.edit_text(msg)
                await state.clear()
                return
            
            try:
                file_io = io.BytesIO()
                await bot.download(photo, destination=file_io)
                file_io.seek(0)
                result = await check_receipt(qr_file=file_io, user_id=message.from_user.id)
                file_io.close()
            except Exception as e:
                logger.error(f"Photo processing error: {e}")
                msg = config_manager.get_message('processing_error', self.default_messages['processing_error'], bot_id=bot_id)
                await processing_msg.edit_text(msg)
                await state.clear()
                return
            
            try:
                await processing_msg.delete()
            except:
                pass
            
            if not result:
                msg = config_manager.get_message('check_failed', self.default_messages['check_failed'], bot_id=bot_id)
                await message.answer(msg)
                await state.clear()
                return
            
            code = result.get("code")
            data = await state.get_data()
            user_db_id = data.get("user_db_id")
            
            if not user_db_id:
                user = await get_user_with_stats(message.from_user.id, bot_id)
                user_db_id = user['id'] if user else None
                if not user_db_id:
                    await message.answer("Ошибка. Попробуйте /start")
                    await state.clear()
                    return
            
            if code == 1:
                await self._handle_valid_receipt(message, state, result, user_db_id, bot_id)
            elif code in (0, 3, 4, 5):
                msg = config_manager.get_message('scan_failed', self.default_messages['scan_failed'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_support_keyboard())
            else:
                msg = config_manager.get_message('service_unavailable', "⚠️ Сервис временно недоступен", bot_id=bot_id)
                await message.answer(msg, reply_markup=get_support_keyboard())
                await state.clear()
    
    async def _handle_valid_receipt(self, message: Message, state: FSMContext, result: dict, user_db_id: int, bot_id: int):
        """Process a valid receipt"""
        receipt_data = result.get("data", {}).get("json", {})
        items = receipt_data.get("items", [])
        
        target_keywords = self._get_keywords(bot_id, 'TARGET_KEYWORDS')
        excluded_keywords = self._get_keywords(bot_id, 'EXCLUDED_KEYWORDS')
        
        # Find target products
        found_items = []
        total_tickets = 0
        
        for item in items:
            item_name = item.get("name", "")
            if any(kw in item_name.lower() for kw in target_keywords):
                if any(ex_kw in item_name.lower() for ex_kw in excluded_keywords):
                    continue
                
                quantity = item.get("quantity", 1)
                try:
                    quantity = max(1, int(float(quantity)))
                except:
                    quantity = 1
                
                total_tickets += quantity
                found_items.append({"name": item_name, "quantity": quantity, "sum": item.get("sum")})
        
        if not found_items:
            msg = config_manager.get_message('receipt_no_product', self.default_messages['receipt_no_product'], bot_id=bot_id)
            await message.answer(msg, reply_markup=get_cancel_keyboard())
            return
        
        # Check duplicates
        fn = str(receipt_data.get("fiscalDriveNumber", ""))
        fd = str(receipt_data.get("fiscalDocumentNumber", ""))
        fp = str(receipt_data.get("fiscalSign", ""))
        
        if fn and fd and fp and await is_receipt_exists(fn, fd, fp):
            msg = config_manager.get_message('receipt_duplicate', self.default_messages['receipt_duplicate'], bot_id=bot_id)
            await message.answer(msg, reply_markup=get_cancel_keyboard())
            return
        
        # Save receipt
        try:
            await add_receipt(
                user_id=user_db_id,
                status="valid",
                data={"dateTime": receipt_data.get("dateTime"), "totalSum": receipt_data.get("totalSum")},
                bot_id=bot_id,
                fiscal_drive_number=fn,
                fiscal_document_number=fd,
                fiscal_sign=fp,
                total_sum=receipt_data.get("totalSum", 0),
                raw_qr="photo_upload",
                product_name=found_items[0]["name"][:100] if found_items else None,
                tickets=total_tickets
            )
        except Exception as e:
            if "unique constraint" in str(e).lower():
                msg = config_manager.get_message('receipt_duplicate', self.default_messages['receipt_duplicate'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_cancel_keyboard())
                return
            logger.error(f"Receipt save error: {e}")
        
        await increment_rate_limit(message.from_user.id)
        
        total_user_tickets = await get_user_tickets_count(user_db_id)
        
        if total_user_tickets == total_tickets:
            msg = config_manager.get_message('receipt_first', self.default_messages['receipt_first'], bot_id=bot_id)
            if total_tickets > 1:
                msg = f"🎉 Поздравляем! +{total_tickets} билетов!\n\nВсего билетов: {total_user_tickets} 🎯"
        else:
            if total_tickets > 1:
                msg = f"✅ Чек принят! +{total_tickets} билетов!\n\nВсего билетов: {total_user_tickets} 🎯"
            else:
                msg = config_manager.get_message('receipt_valid', self.default_messages['receipt_valid'], bot_id=bot_id).format(count=total_user_tickets)
        
        await message.answer(msg, reply_markup=get_receipt_continue_keyboard())
        await state.set_state(ReceiptSubmission.upload_qr)


# Module instance
receipts_module = ReceiptsModule()
