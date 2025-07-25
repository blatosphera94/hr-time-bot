# Файл: bot.py
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import database as db
from config import CONFIG
from command_handlers import CommandHandlerManager
from callback_handlers import callback_manager
from conversation_handlers import (absence_conv_handler, report_conv_handler, location_conv_handler, upload_users_conv_handler)

logging.basicConfig(level=CONFIG.LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler(CONFIG.LOG_FILE_PATH), logging.StreamHandler()])
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Произошла ошибка при обработке обновления:", exc_info=context.error)

def main() -> None:
    logger.info("Инициализация базы данных...")
    db.init_db()
    logger.info("База данных успешно инициализирована.")
    if not CONFIG.TELEGRAM_BOT_TOKEN:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Токен Telegram не найден! Проверьте файл .env")
        return
    application = Application.builder().token(CONFIG.TELEGRAM_BOT_TOKEN).build()
    application.add_error_handler(error_handler)
    
    # Регистрация диалогов
    application.add_handler(absence_conv_handler)
    application.add_handler(report_conv_handler)
    application.add_handler(location_conv_handler)
    application.add_handler(upload_users_conv_handler)
    
    # Регистрация команд
    application.add_handler(CommandHandler("start", CommandHandlerManager.start))
    application.add_handler(CommandHandler("adduser", CommandHandlerManager.add_user))
    application.add_handler(CommandHandler("upload_users", CommandHandlerManager.upload_users_start)) # Для entry_point
    application.add_handler(CommandHandler("users", CommandHandlerManager.list_users))
    application.add_handler(CommandHandler("deluser", CommandHandlerManager.del_user))
    application.add_handler(CommandHandler("report", CommandHandlerManager.report))
    application.add_handler(CommandHandler("help", CommandHandlerManager.help_command))
    
    # Регистрация обработчика кнопок
    application.add_handler(CallbackQueryHandler(callback_manager.main_handler))
    
    logger.info("Бот запускается...")
    application.run_polling()

if __name__ == "__main__":
    main()