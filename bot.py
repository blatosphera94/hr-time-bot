# Файл: bot.py
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import CONFIG
import database as db

# Импортируем наши обработчики из модулей
from command_handlers import CommandHandlerManager
from callback_handlers import callback_manager
from conversation_handlers import (
    absence_conv_handler, 
    report_conv_handler, 
    location_conv_handler
)

# Настройка логирования
logging.basicConfig(
    level=CONFIG.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG.LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует ошибки, вызванные обновлениями."""
    logger.error("Exception while handling an update:", exc_info=context.error)

def main() -> None:
    """Главная функция для запуска бота."""
    
    logger.info("Инициализация базы данных...")
    db.init_db()
    logger.info("База данных успешно инициализирована.")

    if not CONFIG.TELEGRAM_BOT_TOKEN:
        logger.critical("ОШИБКА: Токен Telegram не найден в .env файле!")
        return

    application = Application.builder().token(CONFIG.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрация обработчика ошибок
    application.add_error_handler(error_handler)
    
    # --- Регистрация обработчиков ---

    # 1. Диалоги (должны идти первыми, чтобы перехватывать свои состояния)
    application.add_handler(absence_conv_handler)
    application.add_handler(report_conv_handler)
    application.add_handler(location_conv_handler)

    # 2. Команды ( /start, /help, etc.)
    application.add_handler(CommandHandler("start", CommandHandlerManager.start))
    application.add_handler(CommandHandler("adduser", CommandHandlerManager.add_user))
    application.add_handler(CommandHandler("users", CommandHandlerManager.list_users))
    application.add_handler(CommandHandler("deluser", CommandHandlerManager.del_user))
    application.add_handler(CommandHandler("report", CommandHandlerManager.report))
    application.add_handler(CommandHandler("help", CommandHandlerManager.help_command))

    # 3. Обработчик всех нажатий на inline-кнопки (самый главный)
    application.add_handler(CallbackQueryHandler(callback_manager.main_handler))
    
    logger.info("Бот запускается...")
    application.run_polling()

if __name__ == "__main__":
    main()
