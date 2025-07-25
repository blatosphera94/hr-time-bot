# Файл: bot.py
# Главный файл для запуска бота. Собирает все компоненты вместе.

import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- Импорт наших собственных модулей ---
from config import CONFIG
import database as db
from command_handlers import CommandHandlerManager
from callback_handlers import callback_manager
from conversation_handlers import (
    absence_conv_handler,
    report_conv_handler,
    location_conv_handler
)

# --- 1. Настройка логирования ---
# Настраиваем вывод логов в файл и в консоль.
logging.basicConfig(
    level=CONFIG.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG.LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# --- 2. Глобальный обработчик ошибок ---
# Эта функция будет вызываться, если в любом из хендлеров произойдет ошибка.
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует ошибки, вызванные обновлениями."""
    logger.error("Произошла ошибка при обработке обновления:", exc_info=context.error)


# --- 3. Главная функция запуска ---
def main() -> None:
    """Основная функция, которая собирает и запускает приложение бота."""

    logger.info("Инициализация базы данных...")
    db.init_db()
    logger.info("База данных успешно инициализирована.")

    if not CONFIG.TELEGRAM_BOT_TOKEN:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Токен Telegram не найден! Проверьте файл .env")
        return

    application = Application.builder().token(CONFIG.TELEGRAM_BOT_TOKEN).build()

    # --- 4. Регистрация всех обработчиков ---

    # Сначала регистрируем глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    # Регистрируем обработчики диалогов (должны идти до общих обработчиков, это ВАЖНО)
    application.add_handler(absence_conv_handler)
    application.add_handler(report_conv_handler)
    application.add_handler(location_conv_handler)

    # Регистрируем обработчики команд ( /start, /help, etc.)
    application.add_handler(CommandHandler("start", CommandHandlerManager.start))
    application.add_handler(CommandHandler("adduser", CommandHandlerManager.add_user))
    application.add_handler(CommandHandler("users", CommandHandlerManager.list_users))
    application.add_handler(CommandHandler("deluser", CommandHandlerManager.del_user))
    application.add_handler(CommandHandler("report", CommandHandlerManager.report))
    application.add_handler(CommandHandler("help", CommandHandlerManager.help_command))

    # Регистрируем главный обработчик нажатий на inline-кнопки (идет последним)
    application.add_handler(CallbackQueryHandler(callback_manager.main_handler))

    # --- 5. Запуск бота ---
    logger.info("Бот запускается...")
    application.run_polling()


# --- 6. Точка входа в скрипт ---
if __name__ == "__main__":
    main()