# Файл: command_handlers.py
import re
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database as db
from utils import admin_only, get_now
from menu_generator import MenuGenerator
from config import CONFIG

logger = logging.getLogger(__name__)

class CommandHandlerManager:
    """Класс для обработки всех текстовых команд."""

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает команду /start, маршрутизируя по ролям и статусам."""
        user_id = update.effective_user.id
        user_info = db.get_user(user_id)

        if not user_info:
            await update.message.reply_text("Ваш аккаунт не зарегистрирован. Обратитесь к администратору.")
            return

        # Проверка на активное отсутствие
        today = get_now().date()
        absences = db.get_absences_for_user(user_id, today)
        if absences:
            absence = absences[0]
            absence_type = absence['absence_type'].lower()
            end_date_str = absence['end_date'].strftime('%d.%m.%Y')
            messages = {
                'отпуск': f"Вы в отпуске до {end_date_str}. Хорошего отдыха!",
                'больничный': f"Вы на больничном до {end_date_str}. Скорейшего выздоровления!",
                'командировка': f"Вы в командировке до {end_date_str}. Успешной поездки!"
            }
            text = messages.get(absence_type, f"У вас оформлено отсутствие до {end_date_str}.")
            await update.message.reply_text(text)
            return

        # Маршрутизация по роли
        role = user_info.get('role', 'employee')
        if role in ['admin', 'manager']:
            await update.message.reply_text("Меню руководителя:", reply_markup=MenuGenerator.get_manager_menu())
            return
        
        # Логика для сотрудника
        session_state = db.get_session_state(user_id)
        if not session_state or not session_state.get('status'):
            main_menu_markup = await MenuGenerator.get_main_menu(user_id)
            await update.message.reply_text("Выберите действие:", reply_markup=main_menu_markup)
        else:
            status = session_state.get('status')
            if status == 'working':
                await update.message.reply_text("Вы работаете. Меню восстановлено:", reply_markup=MenuGenerator.get_working_menu())
            elif status == 'on_break':
                await update.message.reply_text("Вы на перерыве. Меню восстановлено:", reply_markup=MenuGenerator.get_break_menu())
            elif status in ['clearing_debt', 'banking_time']:
                text, markup = MenuGenerator.get_extra_work_active_menu(status, session_state['start_time'])
                await update.message.reply_text(text, reply_markup=markup)

    @staticmethod
    @admin_only
    async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавляет или обновляет пользователя."""
        try:
            args = context.args
            if len(args) < 2:
                await update.message.reply_text("Формат: /adduser ID \"Имя Фамилия\" [роль] [ID_рук_1] [ID_рук_2]")
                return
            
            user_id_str = args[0]
            # Улучшенный парсинг имени в кавычках
            match = re.search(r'"(.*?)"', " ".join(args[1:]))
            if not match:
                full_name = args[1]
                remaining_args = args[2:]
            else:
                full_name = match.group(1)
                remaining_args_str = " ".join(args[1:]).replace(f'"{full_name}"', '').strip()
                remaining_args = remaining_args_str.split()

            target_user_id = int(user_id_str)
            role = 'employee'
            manager_1 = None
            manager_2 = None
            
            if len(remaining_args) > 0: role = remaining_args[0]
            if len(remaining_args) > 1: manager_1 = int(remaining_args[1])
            if len(remaining_args) > 2: manager_2 = int(remaining_args[2])

            db.add_or_update_user(target_user_id, full_name, role, manager_1, manager_2)
            await update.message.reply_text(f"Пользователь {full_name} (ID: {target_user_id}) успешно сохранен.")
        except (IndexError, ValueError) as e:
            logger.error(f"Ошибка при выполнении adduser: {e}")
            await update.message.reply_text(f"Ошибка в аргументах: {e}. Проверьте формат.")

    @staticmethod
    @admin_only
    async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает список всех зарегистрированных пользователей."""
        all_users = db.get_all_users()
        if not all_users:
            await update.message.reply_text("В базе данных пока нет пользователей.")
            return
        
        keyboard = [
            [InlineKeyboardButton(f"{user['full_name']} ({user['role']})", callback_data=f"user_details_{user['user_id']}")] 
            for user in all_users
        ]
        await update.message.reply_text("Список пользователей:", reply_markup=InlineKeyboardMarkup(keyboard))

    @staticmethod
    @admin_only
    async def del_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаляет пользователя по ID."""
        try:
            target_user_id = int(context.args[0])
            user_info = db.get_user(target_user_id)
            if not user_info:
                await update.message.reply_text(f"Пользователь с ID {target_user_id} не найден.")
                return
            
            # Предлагаем подтверждение
            text = f"Вы уверены, что хотите удалить пользователя {user_info['full_name']}? Это действие необратимо и удалит все связанные данные."
            keyboard = [[
                InlineKeyboardButton("ДА, УДАЛИТЬ", callback_data=f"confirm_delete_{target_user_id}"),
                InlineKeyboardButton("Отмена", callback_data="cancel_action")
            ]]
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except (IndexError, ValueError):
            await update.message.reply_text("Неверный формат. Используйте: /deluser <ID>")

    @staticmethod
    async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запускает диалог создания отчета."""
        user_info = db.get_user(update.effective_user.id)
        if not user_info: return

        session_state = db.get_session_state(update.effective_user.id)
        is_manager = user_info['role'] in ['manager', 'admin']
        await update.message.reply_text("Выберите период для отчета:", reply_markup=MenuGenerator.get_report_period_menu(is_manager=is_manager, in_session=bool(session_state)))

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет справочное сообщение."""
        user_id = update.effective_user.id
        user_info = db.get_user(user_id)
        
        help_text = "Инструкция по использованию бота:\n\n"
        if user_info and user_info['role'] == 'admin':
            help_text += ("**Вы — Администратор.**\n\n"
                          "`/adduser ID \"Имя Фамилия\" [роль] [ID_рук]` - добавить/изменить пользователя.\n"
                          "`/users` - посмотреть список всех пользователей.\n"
                          "`/deluser ID` - удалить пользователя по ID.\n"
                          "`/report` - отчет по команде.\n"
                          "`/help` - эта справка.")
        elif user_info and user_info['role'] == 'manager':
            help_text += ("**Вы — Руководитель.**\n\n"
                          "Команда `/start` вызовет ваше меню с кнопкой отчета по команде.\n"
                          "Вы будете получать запросы на согласование отгулов, удаленной работы и раннего ухода от ваших сотрудников.\n"
                          "`/help` - эта справка.")
        elif user_info and user_info['role'] == 'employee':
            help_text += ("**Вы — Сотрудник.**\n\n"
                          "- Начинайте и заканчивайте рабочий день кнопками.\n"
                          "- Фиксируйте перерывы.\n"
                          "- Запрашивайте отсутствия через меню 'Оформить отсутствие'.\n"
                          "`/help` - эта справка.")
        else:
            help_text += "Ваш аккаунт не зарегистрирован. Пожалуйста, обратитесь к администратору."
        
        # Отправляем сообщение в чат, а не в ответ на callback, если это возможно
        await context.bot.send_message(chat_id=user_id, text=help_text, parse_mode='Markdown')
