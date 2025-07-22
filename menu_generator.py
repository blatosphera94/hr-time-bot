# Файл: menu_generator.py
import datetime
from typing import List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import database as db
from utils import get_now, seconds_to_str
from config import CONFIG

class MenuGenerator:
    """Класс, отвечающий за генерацию всех клавиатур в боте."""

    @staticmethod
    async def get_main_menu(user_id: int) -> Optional[InlineKeyboardMarkup]:
        """Генерирует главное меню в зависимости от статуса и прав пользователя."""
        today = get_now().date()
        
        # Проверка на активное отсутствие
        absences = db.get_absences_for_user(user_id, today)
        if absences:
            # Если есть отсутствие, меню не показываем (сообщение отправит command_handler)
            return None
        
        # Проверка на выходной или уже отработанный день
        is_weekend = today.weekday() >= 5
        today_logs = db.get_todays_work_log_for_user(user_id)
        if today_logs and not is_weekend:
            is_weekend = True # Считаем день отработанным, как выходной

        # Меню для выходного или отработанного дня
        if is_weekend:
            buttons = [
                {"text": "🛠️ Доп. работа", "callback": "additional_work_menu"},
                {"text": "❓ Помощь", "callback": "help_button"}
            ]
            return MenuGenerator.generate_from_list(buttons)

        # Стандартное меню для рабочего дня
        today_str = str(today)
        approved_remote_work = db.get_approved_request(user_id, 'Удаленная работа', today_str)
        
        buttons = []
        if approved_remote_work:
            buttons.append({"text": "☀️ Начать работу (удаленно)", "callback": "start_work_remote"})
        else:
            # Добавляем кнопку для запроса геолокации
            buttons.append({"text": "☀️ Начать рабочий день (в офисе)", "callback": "start_work_office_location"})
        
        buttons.extend([
            {"text": "🏦 Банк времени", "callback": "show_time_bank"},
            {"text": "🛠️ Доп. работа", "callback": "additional_work_menu"},
            {"text": "📝 Оформить отсутствие", "callback": "absence_menu"},
            {"text": "📊 Запросить отчет", "callback": "request_report"},
            {"text": "❓ Помощь", "callback": "help_button"}
        ])
        return MenuGenerator.generate_from_list(buttons)

    @staticmethod
    def get_working_menu() -> InlineKeyboardMarkup:
        buttons = [
            {"text": "🌙 Закончить рабочий день", "callback": "end_work"},
            {"text": "☕ Уйти на перерыв", "callback": "start_break"},
            {"text": "🏦 Банк времени", "callback": "show_time_bank"},
            {"text": "📊 Запросить отчет", "callback": "request_report"},
            {"text": "⏱️ Мое время", "callback": "show_status"},
            {"text": "❓ Помощь", "callback": "help_button"}
        ]
        return MenuGenerator.generate_from_list(buttons)

    @staticmethod
    def get_break_menu() -> InlineKeyboardMarkup:
        buttons = [
            {"text": "▶️ Вернуться с перерыва", "callback": "end_break"},
            {"text": "🏦 Банк времени", "callback": "show_time_bank"},
            {"text": "📊 Запросить отчет", "callback": "request_report"},
            {"text": "⏱️ Мое время", "callback": "show_status"},
            {"text": "❓ Помощь", "callback": "help_button"}
        ]
        return MenuGenerator.generate_from_list(buttons)
        
    @staticmethod
    def get_manager_menu() -> InlineKeyboardMarkup:
        buttons = [
            {"text": "👨‍💻 Статус команды", "callback": "team_status_button"},
            {"text": "📊 Отчет по команде", "callback": "manager_report_button"},
            {"text": "❓ Помощь", "callback": "help_button"}
        ]
        return MenuGenerator.generate_from_list(buttons)

    @staticmethod
    def get_report_period_menu(is_manager: bool = False, in_session: bool = False) -> InlineKeyboardMarkup:
        base_callback = "manager" if is_manager else "employee"
        buttons = [
            {"text": "📊 Отчет за сегодня", "callback": f'report_today_{base_callback}'},
            {"text": "🗓️ Отчет за текущий месяц", "callback": f'report_this_month_{base_callback}'},
            {"text": "📅 Выбрать другой период", "callback": f'report_custom_period_{base_callback}'}
        ]
        back_button_data = 'back_to_main_menu'
        if is_manager:
            back_button_data = 'back_to_manager_menu'
        elif in_session:
            back_button_data = 'back_to_working_menu'
        
        keyboard = [[InlineKeyboardButton(btn['text'], callback_data=btn['callback'])] for btn in buttons]
        keyboard.append([InlineKeyboardButton("« Назад", callback_data=back_button_data)])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_additional_work_menu(user_id: int) -> InlineKeyboardMarkup:
        total_debt_seconds = db.get_total_debt(user_id)
        buttons = []
        if total_debt_seconds > 0:
            debt_str = seconds_to_str(total_debt_seconds)
            buttons.append({"text": f"Погасить долг ({debt_str})", "callback": 'start_debt_work'})
        
        buttons.append({"text": "🏦 Начать работу в банк времени", "callback": 'start_banking_work'})
        buttons.append({"text": "« Назад", "callback": 'back_to_main_menu'})
        return MenuGenerator.generate_from_list(buttons)

    @staticmethod
    def get_extra_work_active_menu(status: str, start_time: datetime.datetime) -> (str, InlineKeyboardMarkup):
        duration_str = seconds_to_str((get_now() - start_time).total_seconds())
        
        if status == 'clearing_debt':
            text = f"Идет отработка долга. Прошло: {duration_str}"
            button_text = "Закончить отработку"
            callback_data = "end_debt_work"
        else: # banking_time
            text = f"Идет работа в банк времени. Накоплено: {duration_str}"
            button_text = "Закончить работу в банк"
            callback_data = "end_banking_work"

        keyboard = [[InlineKeyboardButton(button_text, callback_data=callback_data)]]
        return text, InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_absence_menu() -> InlineKeyboardMarkup:
        buttons = [
            {"text": "💻 Удаленная работа (запрос)", "callback": "request_remote_work"},
            {"text": "🙋‍♂️ Попросить отгул", "callback": "request_day_off"},
            {"text": "🤧 Больничный", "callback": "absence_sick"},
            {"text": "🌴 Отпуск", "callback": "absence_vacation"},
            {"text": "✈️ Командировка", "callback": "absence_trip"},
            {"text": "« Назад", "callback": "back_to_main_menu"}
        ]
        return MenuGenerator.generate_from_list(buttons)

    @staticmethod
    def get_early_leave_menu() -> InlineKeyboardMarkup:
        buttons = [
            {"text": "Использовать банк времени", "callback": "end_work_use_bank"},
            {"text": "Запросить согласование", "callback": "end_work_ask_manager"},
            {"text": "« Отмена", "callback": "back_to_working_menu"}
        ]
        return MenuGenerator.generate_from_list(buttons)

    @staticmethod
    def generate_from_list(buttons: List[dict]) -> InlineKeyboardMarkup:
        """Универсальный метод генерации меню: одна кнопка в ряду."""
        keyboard = [[InlineKeyboardButton(btn['text'], callback_data=btn['callback'])] for btn in buttons]
        return InlineKeyboardMarkup(keyboard)

