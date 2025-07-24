# Файл: report_generator.py
# Этот модуль отвечает за генерацию текстовых представлений для всех видов отчетов.

import datetime
from typing import List
import database as db
from utils import seconds_to_str, get_now
from config import LOCAL_TZ

class ReportGenerator:
    """Класс, отвечающий за генерацию текстов для отчетов."""

    @staticmethod
    async def get_team_status_text(manager_id: int) -> str:
        """Генерирует текст статуса команды для руководителя с временем начала/окончания работы."""
        team_members = db.get_managed_users(manager_id)
        if not team_members:
            return "За вами не закреплено ни одного сотрудника."
        
        status_lines = [f"**Статус команды на {get_now().strftime('%d.%m.%Y %H:%M')}**\n"]
        today = get_now().date()
        
        for member in team_members:
            member_id = member['user_id']
            member_name = member['full_name']
            session = db.get_session_state(member_id)
            
            if session and session.get('status'):
                status = session['status']
                start_time = session['start_time'] # Это время уже в нашей таймзоне
                
                if status == 'working':
                    status_lines.append(f"🟢 {member_name}: Работает (начал в {start_time.strftime('%H:%M')})")
                elif status == 'on_break':
                    break_start = session.get('break_start_time')
                    status_lines.append(f"☕️ {member_name}: На перерыве (начал в {start_time.strftime('%H:%M')})")
                else:
                    status_lines.append(f"⚙️ {member_name}: Доп. работа (начал в {start_time.strftime('%H:%M')})")
            else:
                absences = db.get_absences_for_user(member_id, today)
                if absences:
                    status_lines.append(f"🏖️ {member_name}: {absences[0]['absence_type']}")
                else:
                    last_log = db.get_todays_work_log_for_user(member_id)
                    if last_log:
                        # Время из БД приходит с таймзоной UTC. Конвертируем его в нашу локальную.
                        start_time_local = last_log['start_time'].astimezone(LOCAL_TZ)
                        end_time_local = last_log['end_time'].astimezone(LOCAL_TZ)
                        status_lines.append(f"⚪️ {member_name}: Не в сети (работал с {start_time_local.strftime('%H:%M')} до {end_time_local.strftime('%H:%M')})")
                    else:
                        status_lines.append(f"⚪️ {member_name}: Не в сети")
        
        return "\n".join(status_lines)

    @staticmethod
    async def get_employee_report_text(user_id: int, start_date: datetime.date, end_date: datetime.date) -> str:
        """Генерирует текстовое содержимое отчета для сотрудника."""
        work_logs = db.get_work_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
        total_work_seconds = sum(log.get('total_work_seconds', 0) for log in work_logs)
        total_break_seconds = sum(log.get('total_break_seconds', 0) for log in work_logs)
        
        report_text = f"**Отчет для вас за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n\n"
        report_text += f"**Чистое рабочее время:** {seconds_to_str(total_work_seconds)}\n"
        report_text += f"**Время на перерывах:** {seconds_to_str(total_break_seconds)}\n\n"
        
        cleared_debt = db.get_debt_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
        total_current_debt = db.get_total_debt(user_id)
        if cleared_debt > 0 or total_current_debt > 0:
            report_text += f"**Отработка:**\n"
            report_text += f"Закрыто долга за период: {seconds_to_str(cleared_debt)}\n"
            report_text += f"Общий текущий долг: {seconds_to_str(total_current_debt)}"
            
        return report_text

    @staticmethod
    async def get_manager_report_text(manager_id: int, start_date: datetime.date, end_date: datetime.date) -> str:
        """Генерирует текстовое содержимое отчета для руководителя."""
        team_members = db.get_managed_users(manager_id)
        if not team_members:
            return "За вами не закреплено ни одного сотрудника."
            
        report_lines = [f"**Отчет по команде за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n"]
        
        for member in team_members:
            member_id = member['user_id']
            member_name = member['full_name']
            
            logs = db.get_work_logs_for_user(member_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
            # Для отсутствий нужно проверять весь период, а не одну дату
            absences_list = db.get_absences_for_user_in_period(member_id, start_date, end_date) # Предполагается, что такая функция будет создана в database.py
            
            employee_line = f"👤 **{member_name}**:"
            
            if logs:
                total_work = sum(log.get('total_work_seconds', 0) for log in logs)
                total_break = sum(log.get('total_break_seconds', 0) for log in logs)
                employee_line += f" отработано {seconds_to_str(total_work)} (перерывы: {seconds_to_str(total_break)})."
            
            if absences_list:
                details = [f"{a['absence_type']} ({a['start_date'].strftime('%d.%m')}-{a['end_date'].strftime('%d.%m')})" for a in absences_list]
                employee_line += f"\n  - *Отсутствия:* {', '.join(details)}" if logs else f" *{', '.join(details)}.*"
            
            if not logs and not absences_list:
                employee_line += " нет данных за период."
                
            report_lines.append(employee_line)

        return "\n".join(report_lines)

# Примечание: для get_manager_report_text может потребоваться добавить в database.py функцию
# get_absences_for_user_in_period, которая ищет пересечения отсутствий с заданным диапазоном дат.
# Пример такой функции:
# def get_absences_for_user_in_period(user_id: int, start_date: datetime.date, end_date: datetime.date) -> List[Dict]:
#     with db_connection() as conn:
#         with conn.cursor(cursor_factory=RealDictCursor) as cursor:
#             cursor.execute(
#                 "SELECT * FROM absences WHERE user_id = %s AND start_date <= %s AND end_date >= %s",
#                 (user_id, end_date, start_date)
#             )
#             return cursor.fetchall()