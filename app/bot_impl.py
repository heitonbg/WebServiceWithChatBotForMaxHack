import threading
import time
import aiomax
from aiomax import buttons
import logging
import re
import asyncio
from datetime import datetime, timedelta

from services import (
    random_motivation, decompose_task, analyze_day, get_or_create_user, 
    add_task_for_user, list_tasks, complete_task, parse_date, validate_date,
    add_subtask, complete_subtask, list_subtasks, update_task, delete_task,
    get_task_by_id, get_task_progress, complete_parent_task
)
from models import init_db
from config import MAX_BOT_TOKEN

logging.basicConfig(level=logging.INFO)

class TaskBot:
    def __init__(self):
        self.token = MAX_BOT_TOKEN
        self.bot = aiomax.Bot(self.token, default_format="markdown")
        self.active_chats = {}  
        self.last_activity = {}  
        self.pagination_state = {}  
        self.setup_handlers()
        self.setup_inactivity_checker_sync()

    def setup_inactivity_checker_sync(self):
        """Синхронная проверка неактивности в отдельном потоке"""
        def checker():
            while True:
                try:
                    time.sleep(300)  # 5 минут
                    asyncio.create_task(self._check_inactive_users())
                except Exception as e:
                    logging.error(f"Inactivity checker error: {e}")
                    time.sleep(300)

        thread = threading.Thread(target=checker, daemon=True)
        thread.start()

    async def _check_inactive_users(self, test_mode=False):
        """Проверка пользователей, которые не активны 4+ часа (или 1 минуту в тестовом режиме)"""
        now = datetime.now()
    
        if test_mode:
            # ТЕСТОВЫЙ РЕЖИМ: 1 минута неактивности
            time_threshold = now - timedelta(minutes=1)
            logging.info("🔍 [TEST] Checking for 1-minute inactivity...")
        else:
            # РЕАЛЬНЫЙ РЕЖИМ: 4 часа неактивности
            time_threshold = now - timedelta(hours=4)
            logging.info("🔍 Checking for 4-hour inactivity...")

        notified_count = 0

        for user_id, last_time in self.last_activity.items():
            if last_time < time_threshold:
                await self._send_inactivity_notification(user_id, test_mode)
                # Обновляем время, чтобы не спамить
                self.last_activity[user_id] = now
                notified_count += 1

        if test_mode:
            logging.info(f"🔍 [TEST] Notified {notified_count} users")
        elif notified_count > 0:
            logging.info(f"📨 Sent inactivity notifications to {notified_count} users")
        async def _send_inactivity_notification(self, user_id, test_mode=False):
            """Отправка уведомления о неактивности"""
            try:
                chat_id = self.active_chats.get(user_id)
                if not chat_id:
                    return

                if test_mode:
                    text = "🧪 Тестовое уведомление: система работает!"
                else:
                    text = "⏰ Напоминание: ты неактивен уже 4 часа! Вернись к своим задачам! 📝"

                await self.bot.send_message(text, chat_id)
                logging.info(f"📨 Sent inactivity notification to user {user_id}")

            except Exception as e:
                logging.error(f"Error in _send_inactivity_notification: {e}")

    def update_user_activity(self, user_id):
        """Обновляем время последней активности пользователя"""
        self.last_activity[user_id] = datetime.now()

    def normalize_user_id(self, user_data):
        user_id = user_data.user_id
        
        if isinstance(user_id, int):
            user_id = str(user_id)
        
        return user_id
        
    def get_main_keyboard(self):
        kb = buttons.KeyboardBuilder()
        kb.add(buttons.CallbackButton('📝 Добавить задачу', 'add_task'))
        kb.add(buttons.CallbackButton('📋 Список задач', 'list_tasks'))
        kb.row(buttons.CallbackButton('✅ Завершить задачу', 'complete_task'))
        kb.add(buttons.CallbackButton('💫 Мотивация', 'motivation'))
        kb.row(buttons.CallbackButton('🔍 Разложить задачу', 'decompose_task'))
        kb.add(buttons.CallbackButton('📊 Анализ дня', 'analyze_day'))
        return kb

    def get_add_task_keyboard(self):
        kb = buttons.KeyboardBuilder()
        kb.add(buttons.CallbackButton('📚 Учеба', 'add_study'))
        kb.add(buttons.CallbackButton('💼 Работа', 'add_work'))
        kb.row(buttons.CallbackButton('🏠 Дом', 'add_home'))
        kb.add(buttons.CallbackButton('🎯 Личное', 'add_personal'))
        kb.row(buttons.CallbackButton('⬅️ Назад', 'back_main'))
        return kb

    def get_back_keyboard(self):
        kb = buttons.KeyboardBuilder()
        kb.row(buttons.CallbackButton('⬅️ Назад', 'back_main'))
        return kb

    def get_paginated_task_selector(self, user_id, tasks, action_type='complete'):
        """Клавиатура с пагинацией - 3 задачи на страницу ТОЛЬКО АКТИВНЫЕ"""
        if user_id not in self.pagination_state:
            self.pagination_state[user_id] = {'page': 0, 'action': action_type}

        state = self.pagination_state[user_id]
        page = state['page']

        # ФИЛЬТРУЕМ ТОЛЬКО АКТИВНЫЕ ЗАДАЧИ (не выполненные)
        active_tasks = [t for t in tasks if t.status != 'done']

        if not active_tasks:
            kb = buttons.KeyboardBuilder()
            kb.add(buttons.CallbackButton('🎉 Все задачи выполнены!', 'no_tasks'))
            kb.row(buttons.CallbackButton('⬅️ Главное меню', 'back_main'))
            return kb, "🎉 **Все задачи выполнены!** Нет активных задач для завершения."

        # Разбиваем на страницы по 3 задачи
        tasks_per_page = 3
        total_pages = (len(active_tasks) + tasks_per_page - 1) // tasks_per_page

        # Корректируем номер страницы если он превышает доступные
        if page >= total_pages:
            page = total_pages - 1
            self.pagination_state[user_id]['page'] = page

        start_idx = page * tasks_per_page
        end_idx = start_idx + tasks_per_page
        page_tasks = active_tasks[start_idx:end_idx]

        # Формируем сообщение с информацией о странице
        message = f"📄 **Страница {page + 1}/{total_pages}**\n\n"

        kb = buttons.KeyboardBuilder()

        # Добавляем задачи текущей страницы
        for task in page_tasks:
            if task.is_parent:
                completed, total, _ = get_task_progress(task.id)
                label = f"🎯 {task.title[:15]}... ({completed}/{total})"
                callback_data = f'view_parent_{task.id}'
            else:
                # Обрезаем длинные названия
                short_title = task.title[:18] + "..." if len(task.title) > 18 else task.title
                label = f"✅ {short_title}"
                callback_data = f'{action_type}_{task.id}'

            kb.add(buttons.CallbackButton(label, callback_data))

        # Добавляем кнопки пагинации
        if total_pages > 1:
            pagination_row = []

            if page > 0:
                pagination_row.append(buttons.CallbackButton('⬅️ Пред.', f'page_{page - 1}'))

            pagination_row.append(buttons.CallbackButton(f'{page + 1}/{total_pages}', 'current_page'))

            if page < total_pages - 1:
                pagination_row.append(buttons.CallbackButton('След. ➡️', f'page_{page + 1}'))

            kb.row(*pagination_row)

        # Кнопка возврата
        kb.row(buttons.CallbackButton('⬅️ Главное меню', 'back_main'))

        # Формируем текст с задачами текущей страницы
        for i, task in enumerate(page_tasks, start_idx + 1):
            if task.is_parent:
                completed, total, progress = get_task_progress(task.id)
                status = f" ({completed}/{total} подзадач)"
            else:
                status = ""

            message += f"{i}. {task.title}{status}\n"

        return kb, message

    def get_parent_task_keyboard(self, task_id):
        """Клавиатура для родительской задачи с подзадачами"""
        kb = buttons.KeyboardBuilder()
        
        # Получаем подзадачи
        subtasks = list_subtasks(task_id)
        
        # Добавляем кнопки для подзадач
        for subtask in subtasks[:6]:  # Ограничиваем 6 подзадачами
            status_icon = "✅" if subtask.status == "done" else "🔲"
            short_title = subtask.title[:20] + "..." if len(subtask.title) > 20 else subtask.title
            label = f"{status_icon} {short_title}"
            kb.add(buttons.CallbackButton(label, f'complete_{subtask.id}'))
        
        # Кнопка завершения всей родительской задачи
        kb.row(buttons.CallbackButton('🎯 Завершить всю задачу', f'complete_parent_{task_id}'))
        
        # Кнопка обновления
        kb.add(buttons.CallbackButton('🔄 Обновить', f'refresh_parent_{task_id}'))
        
        # Кнопка возврата
        kb.row(buttons.CallbackButton('⬅️ Назад к списку', 'complete_task'))
        
        return kb

    def get_complete_keyboard(self, tasks):
        """Клавиатура для завершения задач - только обычные и родительские"""
        kb = buttons.KeyboardBuilder()

        # ✅ ОБЫЧНЫЕ ЗАДАЧИ (без подзадач)
        regular_tasks = [t for t in tasks if not t.parent_id and not t.is_parent and t.status != 'done']

        # ✅ РОДИТЕЛЬСКИЕ ЗАДАЧИ (только те, у которых есть незавершённые подзадачи)
        parent_tasks = []
        for task in tasks:
            if task.is_parent and task.status != 'done':
                completed, total, progress = get_task_progress(task.id)
                if progress < 100:  # Есть незавершённые подзадачи
                    parent_tasks.append(task)

        # 🔄 ОБЪЕДИНЯЕМ И ОГРАНИЧИВАЕМ
        available_tasks = (regular_tasks + parent_tasks)[:8]  # Максимум 8 кнопок

        if not available_tasks:
            kb.add(buttons.CallbackButton('📝 Нет задач для завершения', 'no_tasks'))
        else:
            for task in available_tasks:
                # 📝 ОБЫЧНЫЕ ЗАДАЧИ
                if not task.is_parent:
                    kb.add(buttons.CallbackButton(f'✅ {task.title[:15]}...', f'complete_{task.id}'))
                # 🎯 РОДИТЕЛЬСКИЕ ЗАДАЧИ (показываем прогресс)
                else:
                    completed, total, progress = get_task_progress(task.id)
                    kb.add(buttons.CallbackButton(f'🎯 {task.title[:12]}... ({completed}/{total})', f'view_parent_{task.id}'))

        kb.row(buttons.CallbackButton('⬅️ Назад', 'back_main'))
        return kb

    def get_task_details_keyboard(self, task_id):
        kb = buttons.KeyboardBuilder()
        kb.add(buttons.CallbackButton('🔄 Обновить', f'refresh_parent_{task_id}'))
        kb.add(buttons.CallbackButton('✅ Завершить все', f'complete_parent_{task_id}'))
        kb.row(buttons.CallbackButton('⬅️ Назад', 'complete_task'))
        return kb

    def format_task_list(self, tasks):
        """Показываем ТОЛЬКО главные задачи с прогрессом подзадач"""
        if not tasks:
            return "📝 **Список задач пуст.**"

        # Берем ТОЛЬКО родительские задачи и обычные задачи (без подзадач)
        parent_tasks = [t for t in tasks if t.is_parent]
        regular_tasks = [t for t in tasks if not t.parent_id and not t.is_parent]

        lines = []

        # 📝 ОБЫЧНЫЕ ЗАДАЧИ
        for task in regular_tasks:
            status_icon = "✅" if task.status == "done" else "⏳"
            time_info = f" ⏱{task.estimated_minutes}m" if task.estimated_minutes else ""
            diff_info = f" ⚡{task.difficulty}" if task.difficulty > 1 else ""
            lines.append(f"{status_icon} `{task.id:02d}` {task.title}{time_info}{diff_info}")

        # 🎯 РОДИТЕЛЬСКИЕ ЗАДАЧИ (с прогрессом)
        for parent in parent_tasks:
            completed, total, progress = get_task_progress(parent.id)

            if progress == 100:
                status_icon = "✅"
            elif progress > 0:
                status_icon = "🟡"
            else:
                status_icon = "🎯"

            progress_text = f" ({completed}/{total})" if total > 0 else ""
            lines.append(f"{status_icon} `{parent.id:02d}` {parent.title}{progress_text}")

        return "📋 **Твои задачи:**\n\n" + "\n".join(lines)

    def format_subtask_list(self, subtasks, parent_title):
        if not subtasks:
            return f"🎯 **{parent_title}**\n\n📝 Подзадачи не найдены"
        
        lines = [f"🎯 **{parent_title}**\n"]
        completed = 0
        
        for subtask in subtasks:
            status_icon = "✅" if subtask.status == "done" else "🔲"
            lines.append(f"{status_icon} {subtask.title}")
            if subtask.status == "done":
                completed += 1
        
        progress = f"\n📊 **Прогресс: {completed}/{len(subtasks)}**"
        return "\n".join(lines) + progress

    def setup_handlers(self):
        bot = self.bot

        @bot.on_bot_start()
        async def welcome(pd):
            user_id = self.normalize_user_id(pd.user)
            name = pd.user.name
            chat_id = pd.chat_id
            
            self.active_chats[user_id] = chat_id
            self.update_user_activity(user_id)

            user = get_or_create_user(user_id, name)
            logging.info(f"🆕 Новый пользователь: {user_id} ({name})")

            await pd.send(
                f"🧠 **Привет, {name}!**\n\n"
                "Я бот для управления задачами с интеграцией веб-приложения.\n\n"
                "💡 *Задачи, созданные в веб-приложении, будут видны здесь и наоборот!*\n\n"
                f"🌐 Для доступа к веб-приложению используй твой ID:\n`{user_id}`\n\n"
                "💡 Сохрани этот ID - он нужен для входа в мини-приложение!\n\n"
                "Выбери действие:",
                keyboard=self.get_main_keyboard()
            )

        @bot.on_command('start')
        async def cmd_start(ctx):
            user_id = self.normalize_user_id(ctx.sender)
            name = ctx.sender.name
            chat_id = ctx.recipient.chat_id
            
            self.active_chats[user_id] = chat_id
            self.update_user_activity(user_id)

            user = get_or_create_user(user_id, name)
            logging.info(f"🔁 Пользователь перезапустил бота: {user_id} ({name})")

            await ctx.reply(
                f"✅ **С возвращением, {name}!** 🚀\n\n"
                f"🌐 Твой ID для веб-приложения: `{user_id}`\n\n"
                "Выбери действие:",
                keyboard=self.get_main_keyboard()
            )

        @bot.on_button_callback('add_task')
        async def add_task_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id
            self.update_user_activity(user_id)
            
            await cb.answer(
                text="🎯 **Добавление задачи**\n\n"
                     "Выбери категорию или напиши задачу вручную:\n\n"
                     "💡 *Пример:*\n"
                     "`/add сделать домашку est=30 difficulty=2 date=12.12.2025`",
                keyboard=self.get_add_task_keyboard()
            )

        @bot.on_button_callback('list_tasks')
        async def list_tasks_handler(cb):
            try:
                user_id = self.normalize_user_id(cb.user)
                self.active_chats[user_id] = cb.message.recipient.chat_id
                self.update_user_activity(user_id)
                
                tasks = list_tasks(user_id)
                logging.info(f"📋 Пользователь {user_id} запросил список задач: {len(tasks)} задач")

                if not tasks:
                    await cb.answer(
                        text="📝 Список задач пуст.\n\n"
                             "Добавь задачи через кнопку '📝 Добавить задачу' или в веб-приложении.",
                        keyboard=self.get_main_keyboard()
                    )
                    return
                    
                task_text = self.format_task_list(tasks)
                
                # Проверяем есть ли родительские задачи для детального просмотра
                parent_tasks = [t for t in tasks if t.is_parent and t.status != 'done']
                if parent_tasks:
                    # Создаем клавиатуру с возможностью просмотра родительских задач
                    kb = buttons.KeyboardBuilder()
                    
                    # Добавляем кнопки для родительских задач
                    for task in parent_tasks[:4]:  # Ограничиваем 4 задачами
                        completed, total, _ = get_task_progress(task.id)
                        label = f"🎯 {task.title[:18]} ({completed}/{total})"
                        kb.add(buttons.CallbackButton(label, f'view_parent_{task.id}'))
                    
                    # Кнопка возврата
                    kb.row(buttons.CallbackButton('⬅️ Главное меню', 'back_main'))
                    
                    await cb.answer(
                        text=task_text + "\n\n🔍 **Выбери задачу для просмотра подзадач:**",
                        keyboard=kb
                    )
                else:
                    await cb.answer(
                        text=task_text,
                        keyboard=self.get_main_keyboard()
                    )
                
            except Exception as e:
                logging.exception("Error in list_tasks_handler")
                await cb.answer("❌ Ошибка при получении списка задач")

        @bot.on_button_callback('complete_task')
        async def complete_task_handler(cb):
            try:
                user_id = self.normalize_user_id(cb.user)
                self.active_chats[user_id] = cb.message.recipient.chat_id
                self.update_user_activity(user_id)
                
                tasks = list_tasks(user_id)
                pending_tasks = [t for t in tasks if t.status != 'done']
                
                if not pending_tasks:
                    await cb.answer(
                        text="🎉 Нет активных задач для завершения!\n\n"
                             "Все задачи выполнены 🚀",
                        keyboard=self.get_main_keyboard()
                    )
                    return
                
                # Используем пагинацию для завершения задач
                kb, message = self.get_paginated_task_selector(user_id, tasks, 'complete')
                
                full_message = f"✅ **Завершение задач**\n\n{message}"
                    
                # ИСПРАВЛЕНИЕ: Используем send_message вместо answer для стабильности
                await self.bot.send_message(
                    full_message,
                    cb.message.recipient.chat_id,
                    keyboard=kb
                )
                
            except Exception as e:
                logging.exception("Error in complete_task_handler")
                await cb.answer("❌ Ошибка при получении списка задач")

        @bot.on_button_callback(lambda data: data.payload.startswith('view_parent_'))
        async def view_parent_task_handler(cb):
            """Просмотр родительской задачи с подзадачами"""
            try:
                if not cb.payload.startswith('view_parent_') or len(cb.payload.split('_')) < 3:
                    await cb.answer("❌ Ошибка: неверный формат")
                    return

                task_id_str = cb.payload.split('_')[2]
                if not task_id_str.isdigit():
                    await cb.answer("❌ Ошибка: ID задачи должен быть числом")
                    return

                task_id = int(task_id_str)
                user_id = self.normalize_user_id(cb.user)

                task = get_task_by_id(task_id)
                if not task:
                    await cb.answer("❌ Задача не найдена")
                    return

                # Получаем подзадачи
                subtasks = list_subtasks(task_id)
                response = self.format_subtask_list(subtasks, task.title)

                kb = self.get_parent_task_keyboard(task_id)

                # ИСПРАВЛЕНИЕ: Используем send_message для стабильности
                await self.bot.send_message(
                    response,
                    cb.message.recipient.chat_id,
                    keyboard=kb
                )

            except Exception as e:
                logging.exception("Error in view_parent_task_handler")
                await cb.answer("❌ Ошибка при просмотре задачи")

        @bot.on_button_callback(lambda data: data.payload.startswith('complete_'))
        async def complete_specific_task(cb):
            try:
                if cb.payload.startswith('complete_parent_'):
                    return

                if not cb.payload.startswith('complete_') or len(cb.payload.split('_')) < 2:
                    await cb.answer("❌ Ошибка: неверный формат задачи")
                    return

                task_id_str = cb.payload.split('_')[1]
                if not task_id_str.isdigit():
                    await cb.answer("❌ Ошибка: ID задачи должен быть числом")
                    return

                task_id = int(task_id_str)
                user_id = self.normalize_user_id(cb.user)
                self.active_chats[user_id] = cb.message.recipient.chat_id

                task = get_task_by_id(task_id)
                if not task:
                    await cb.answer("❌ Задача не найдена")
                    return

                # Завершаем задачу
                completed_task = complete_task(user_id, task_id)

                if not completed_task:
                    await cb.answer("❌ Задача не найдена")
                    return

                # Если это подзадача, проверяем родительскую задачу
                if task.parent_id:
                    parent_task = get_task_by_id(task.parent_id)
                    if parent_task:
                        # Получаем обновленный список подзадач
                        subtasks = list_subtasks(parent_task.id)
                        completed = len([t for t in subtasks if t.status == 'done'])
                        total = len(subtasks)
                        
                        response = f"✅ **Подзадача завершена:** {completed_task['title']}\n\n"
                        response += f"🎯 **Прогресс '{parent_task.title}':** {completed}/{total}\n\n"
                        
                        # Если все подзадачи выполнены, сообщаем об этом
                        if completed == total:
                            response += "🎉 **Все подзадачи выполнены! Задача завершена автоматически!**"
                        
                        kb = self.get_parent_task_keyboard(parent_task.id)
                        
                        await self.bot.send_message(
                            response,
                            cb.message.recipient.chat_id,
                            keyboard=kb
                        )
                        return

                # Если это обычная задача
                updated_tasks = list_tasks(user_id)
                task_text = self.format_task_list(updated_tasks)

                await self.bot.send_message(
                    f"✅ **Задача '{completed_task['title']}' завершена!** 🎉\n\n{task_text}",
                    cb.message.recipient.chat_id,
                    keyboard=self.get_main_keyboard()
                )

                logging.info(f"✅ Пользователь {user_id} завершил задачу: {task_id}")

            except Exception as e:
                logging.exception("Error in complete_specific_task")
                await cb.answer("❌ Ошибка при завершении задачи")

        @bot.on_button_callback(lambda data: data.payload.startswith('complete_parent_'))
        async def complete_parent_task_handler(cb):
            try:
                if not cb.payload.startswith('complete_parent_') or len(cb.payload.split('_')) < 3:
                    await cb.answer("❌ Ошибка: неверный формат")
                    return

                parent_task_id_str = cb.payload.split('_')[2]
                if not parent_task_id_str.isdigit():
                    await cb.answer("❌ Ошибка: ID задачи должен быть числом")
                    return

                parent_task_id = int(parent_task_id_str)
                user_id = self.normalize_user_id(cb.user)

                completed_task = complete_parent_task(parent_task_id)

                if not completed_task:
                    await cb.answer("❌ Задача не найдена")
                    return

                updated_tasks = list_tasks(user_id)
                task_text = self.format_task_list(updated_tasks)

                await self.bot.send_message(
                    f"🎉 **Вся задача завершена!**\n\n"
                    f"'{completed_task['title']}'\n"
                    f"✅ Завершено подзадач: {completed_task['subtasks_completed']}\n\n"
                    f"{task_text}",
                    cb.message.recipient.chat_id,
                    keyboard=self.get_main_keyboard()
                )

            except Exception as e:
                logging.exception("Error in complete_parent_task_handler")
                await cb.answer("❌ Ошибка при завершении задачи")

        @bot.on_button_callback(lambda data: data.payload.startswith('refresh_parent_'))
        async def refresh_parent_task_handler(cb):
            try:
                if not cb.payload.startswith('refresh_parent_') or len(cb.payload.split('_')) < 3:
                    await cb.answer("❌ Ошибка: неверный формат")
                    return

                task_id_str = cb.payload.split('_')[2]
                if not task_id_str.isdigit():
                    await cb.answer("❌ Ошибка: ID задачи должен быть числом")
                    return

                task_id = int(task_id_str)
                task = get_task_by_id(task_id)

                if not task or not task.is_parent:
                    await cb.answer("❌ Задача не найдена или не является родительской")
                    return

                subtasks = list_subtasks(task_id)
                response = self.format_subtask_list(subtasks, task.title)

                await self.bot.send_message(
                    response,
                    cb.message.recipient.chat_id,
                    keyboard=self.get_parent_task_keyboard(task_id)
                )

            except Exception as e:
                logging.exception("Error in refresh_parent_task_handler")
                await cb.answer("❌ Ошибка при обновлении задачи")

        @bot.on_button_callback('motivation')
        async def motivation_handler(cb):
            try:
                user_id = self.normalize_user_id(cb.user)
                self.active_chats[user_id] = cb.message.recipient.chat_id
                self.update_user_activity(user_id)
                
                q = random_motivation()
                await cb.answer(
                    text=f"💫 **Мотивация:**\n\n{q}",
                    keyboard=self.get_back_keyboard()
                )
            except Exception as e:
                logging.exception("Error in motivation_handler")
                await cb.answer("❌ Не могу найти мотивацию...")

        @bot.on_button_callback('decompose_task')
        async def decompose_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id
            self.update_user_activity(user_id)

            await cb.answer(
                text="🔍 **Разложение задачи**\n\n"
                     "Напиши задачу для разложения:\n\n"
                     "💡 *Пример:*\n"
                     "`/decompose подготовить отчет по проекту`\n\n"
                     "✅ *После разложения шаги автоматически станут задачами!*",
                keyboard=self.get_back_keyboard()
            )

        @bot.on_button_callback('analyze_day')
        async def analyze_handler(cb):
            try:
                user_id = self.normalize_user_id(cb.user)
                self.active_chats[user_id] = cb.message.recipient.chat_id
                self.update_user_activity(user_id)
                
                tasks = list_tasks(user_id)
                user = get_or_create_user(user_id)
                res = analyze_day(user, tasks)
                
                await cb.answer(
                    text=f"📊 **Анализ дня:**\n\n{res['text']}",
                    keyboard=self.get_back_keyboard()
                )
                
                logging.info(f"📊 Пользователь {user_id} запросил анализ дня")
                
            except Exception as e:
                logging.exception("Error in analyze_handler")
                await cb.answer("❌ Ошибка при анализе дня")

        # Кнопки быстрого добавления задач
        @bot.on_button_callback('add_study')
        async def add_study_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id
            self.update_user_activity(user_id)
            
            await cb.answer(
                text="📚 **Учебные задачи**\n\n"
                     "Напиши учебную задачу:\n\n"
                     "💡 *Пример:*\n"
                     "`/add сделать домашку по математике est=60 difficulty=2`",
                keyboard=self.get_add_task_keyboard()
            )

        @bot.on_button_callback('add_work')
        async def add_work_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id
            self.update_user_activity(user_id)
            
            await cb.answer(
                text="💼 **Рабочие задачи**\n\n"
                     "Напиши рабочую задачу:\n\n"
                     "💡 *Пример:*\n"
                     "`/add подготовить отчет est=45 difficulty=3`",
                keyboard=self.get_add_task_keyboard()
            )

        @bot.on_button_callback('add_home')
        async def add_home_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id
            self.update_user_activity(user_id)
            
            await cb.answer(
                text="🏠 **Домашние задачи**\n\n"
                     "Напиши домашнюю задачу:\n\n"
                     "💡 *Пример:*\n"
                     "`/add убраться в комнате est=30 difficulty=1`",
                keyboard=self.get_add_task_keyboard()
            )

        @bot.on_button_callback('add_personal')
        async def add_personal_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id
            self.update_user_activity(user_id)
            
            await cb.answer(
                text="🎯 **Личные задачи**\n\n"
                     "Напиши личную задачу:\n\n"
                     "💡 *Пример:*\n"
                     "`/add сходить в спортзал est=90 difficulty=2`",
                keyboard=self.get_add_task_keyboard()
            )

        # Назад в главное меню
        @bot.on_button_callback('back_main')
        async def back_main_handler(cb):
            user_id = self.normalize_user_id(cb.user)
            self.active_chats[user_id] = cb.message.recipient.chat_id

            # Очищаем состояние пагинации
            if user_id in self.pagination_state:
                del self.pagination_state[user_id]

            await cb.answer(
                text="🏠 **Главное меню**",
                keyboard=self.get_main_keyboard()
            )

        # Команды
        @bot.on_command('add')
        async def cmd_add(ctx):
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)

                text = ctx.message.body.text or ""
                args = text[len("/add"):].strip()
                est = 0
                diff = 1
                task_date = None
                parent_task_id = None

                m_est = re.search(r"est\s*=\s*(\d+)", args, re.IGNORECASE)
                m_diff = re.search(r"difficulty\s*=\s*(\d+)", args, re.IGNORECASE)
                m_date = re.search(r"date\s*=\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})", args, re.IGNORECASE)
                m_parent = re.search(r"parent\s*=\s*(\d+)", args, re.IGNORECASE)

                if m_est:
                    est = int(m_est.group(1))
                    args = re.sub(r"est\s*=\s*\d+", "", args, flags=re.IGNORECASE)
                if m_diff:
                    diff = int(m_diff.group(1))
                    args = re.sub(r"difficulty\s*=\s*\d+", "", args, flags=re.IGNORECASE)
                if m_date:
                    date_str = m_date.group(1)
                    task_date, error_msg = validate_date(date_str)
                    if error_msg:
                        await ctx.reply(
                            error_msg + "\n\n💡 *Пример правильной даты:*\n"
                                        "`/add встретиться с клиентом date=15.12.2024`",
                            keyboard=self.get_main_keyboard()
                        )
                        return
                    args = re.sub(r"date\s*=\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}", "", args, flags=re.IGNORECASE).strip()
                if m_parent:
                    parent_task_id = int(m_parent.group(1))
                    args = re.sub(r"parent\s*=\s*\d+", "", args, flags=re.IGNORECASE).strip()
                
                args = re.sub(r"\s+", " ", args).strip()

                title = args.strip()
                if not title:
                    await ctx.reply(
                        "❌ **Укажи название задачи после /add**\n\n"
                        "💡 *Пример:*\n"
                        "`/add сделать домашку est=30 difficulty=2`\n"
                        "`/add встретиться с клиентом date=15.12.2024`\n"
                        "`/add подзадача parent=1`",
                        keyboard=self.get_main_keyboard()
                    )
                    return

                if parent_task_id:
                    task = add_subtask(user_id, parent_task_id, title, est, diff)
                else:
                    task = add_task_for_user(user_id, title, estimated_minutes=est, difficulty=diff, task_date=task_date)

                updated_tasks = list_tasks(user_id)
                task_text = self.format_task_list(updated_tasks)

                date_info = ""
                if task_date:
                    date_info = f" 📅 {task_date.strftime('%d.%m.%Y')}"

                parent_info = ""
                if parent_task_id:
                    parent_task = get_task_by_id(parent_task_id)
                    if parent_task:
                        parent_info = f"\n\n🎯 Подзадача для: '{parent_task.title}'"

                if task.status == "quick":
                    response = (f'⚡ **Быстрая задача добавлена!**{date_info}{parent_info}\n\n'
                                f'"{title}" (<=2 мин)\n\n'
                                f'💡 *Сделай прямо сейчас!*\n\n'
                                f'{task_text}')
                else:
                    est_info = f"⏱{est}m" if est else ""
                    diff_info = f"⚡{diff}" if diff > 1 else ""
                    info_parts = [p for p in [est_info, diff_info] if p]
                    info_str = f" ({' '.join(info_parts)})" if info_parts else ""

                    response = (f'✅ **Задача добавлена**{date_info}{parent_info}\n\n'
                                f'"{title}"{info_str}\n\n'
                                f'{task_text}')

                await ctx.reply(response, keyboard=self.get_main_keyboard())
                logging.info(f"📝 Пользователь {user_id} добавил задачу: {title}")

            except ValueError as e:
                await ctx.reply(
                    f"❌ {str(e)}\n\n"
                    "💡 *Используй сегодняшнюю или будущую дату*",
                    keyboard=self.get_main_keyboard()
                )
            except Exception as e:
                logging.exception("Error in cmd_add")
                await ctx.reply(
                    "❌ Ошибка при добавлении задачи",
                    keyboard=self.get_main_keyboard()
                )

        @bot.on_command('list_tasks')
        async def cmd_list(ctx):
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)
                
                tasks = list_tasks(user_id)
                logging.info(f"📋 Пользователь {user_id} запросил список задач: {len(tasks)} задач")
                
                if not tasks:
                    await ctx.reply(
                        "📝 **Список задач пуст**\n\n"
                        "Добавь задачи через:\n"
                        "• Кнопку '📝 Добавить задачу'\n"  
                        "• Команду `/add <задача>`\n"
                        "• Веб-приложение",
                        keyboard=self.get_main_keyboard()
                    )
                    return
                    
                task_text = self.format_task_list(tasks)
                
                # Проверяем есть ли родительские задачи для детального просмотра
                parent_tasks = [t for t in tasks if t.is_parent and t.status != 'done']
                if parent_tasks:
                    # Создаем клавиатуру с возможностью просмотра родительских задач
                    kb = buttons.KeyboardBuilder()
                    
                    # Добавляем кнопки для родительских задач
                    for task in parent_tasks[:4]:  # Ограничиваем 4 задачами
                        completed, total, _ = get_task_progress(task.id)
                        label = f"🎯 {task.title[:18]} ({completed}/{total})"
                        kb.add(buttons.CallbackButton(label, f'view_parent_{task.id}'))
                    
                    # Кнопка возврата
                    kb.row(buttons.CallbackButton('⬅️ Главное меню', 'back_main'))
                    
                    await ctx.reply(
                        task_text + "\n\n🔍 **Выбери задачу для просмотра подзадач:**",
                        keyboard=kb
                    )
                else:
                    await ctx.reply(task_text, keyboard=self.get_main_keyboard())
                
            except Exception as e:
                logging.exception("Error in cmd_list")
                await ctx.reply(
                    "❌ Ошибка при получении списка задач",
                    keyboard=self.get_main_keyboard()
                )

        @bot.on_command('complete')
        async def cmd_complete(ctx):
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)

                text = ctx.message.body.text or ""
                arg = text[len("/complete"):].strip()

                if not arg or not arg.isdigit():
                    # Если не указан ID, показываем пагинацию
                    tasks = list_tasks(user_id)
                    kb, message = self.get_paginated_task_selector(user_id, tasks, 'complete')

                    full_message = f"✅ **Завершение задач**\n\n{message}"

                    await ctx.reply(full_message, keyboard=kb)
                    return

                task_id = int(arg)

                task = get_task_by_id(task_id)

                if not task:
                    await ctx.reply(
                        "❌ **Задача не найдена**\n\n"
                        "Проверь ID через список задач",
                        keyboard=self.get_main_keyboard()
                    )
                    return

                # 🎯 ЕСЛИ ЭТО РОДИТЕЛЬСКАЯ ЗАДАЧА - показываем детальный просмотр
                if task.is_parent:
                    subtasks = list_subtasks(task_id)
                    response = self.format_subtask_list(subtasks, task.title)

                    await ctx.reply(
                        text=response,
                        keyboard=self.get_parent_task_keyboard(task_id)
                    )
                    return

                # 📝 ЕСЛИ ЭТО ОБЫЧНАЯ ЗАДАЧА - завершаем как обычно
                completed_task = complete_task(user_id, task_id)

                if not completed_task:
                    await ctx.reply(
                        "❌ **Задача не найдена**\n\n"
                        "Проверь ID через список задач",
                        keyboard=self.get_main_keyboard()
                    )
                else:
                    updated_tasks = list_tasks(user_id)
                    task_text = self.format_task_list(updated_tasks)

                    await ctx.reply(
                        f"✅ **Задача завершена!**\n\n"
                        f"'{completed_task['title']}' ✅\n\n"
                        f"{task_text}",
                        keyboard=self.get_main_keyboard()
                    )

            except Exception as e:
                logging.exception("Error in cmd_complete")
                await ctx.reply(
                    "❌ Ошибка при завершении задачи",
                    keyboard=self.get_main_keyboard()
                )

        @bot.on_command('motivation')
        async def cmd_motivation(ctx):
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)
                
                q = random_motivation()
                await ctx.reply(
                    f"💫 **Мотивация:**\n\n{q}",
                    keyboard=self.get_main_keyboard()
                )
            except Exception as e:
                logging.exception("Error in cmd_motivation")
                await ctx.reply(
                    "❌ Не могу найти мотивацию...",
                    keyboard=self.get_main_keyboard()
                )

        @bot.on_command('decompose')
        async def cmd_decompose(ctx):
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)

                text = ctx.message.body.text or ""
                arg = text[len("/decompose"):].strip()

                if not arg:
                    await ctx.reply(
                        "❌ **Укажи задачу для разложения**\n\n"
                        "💡 *Пример:*\n"
                        "`/decompose подготовить отчет по проекту`",
                        keyboard=self.get_main_keyboard()
                    )
                    return

                hints = []

                if arg.isdigit():
                    tasks = list_tasks(user_id)
                    found_task = None
                    for t in tasks:
                        if t.id == int(arg):
                            found_task = t
                            break

                    if found_task:
                        hints = decompose_task(found_task.title, user_id)
                        response = f"🔍 **Разложение задачи:**\n'{found_task.title}'\n\n" + "\n".join(
                            [f"{i + 1}. {step}" for i, step in enumerate(hints)])
                    else:
                        await ctx.reply(
                            "❌ Задача с таким ID не найдена",
                            keyboard=self.get_main_keyboard()
                        )
                        return
                else:
                    hints = decompose_task(arg, user_id)
                    response = f"🔍 **Разложение задачи:**\n'{arg}'\n\n" + "\n".join(
                        [f"{i + 1}. {step}" for i, step in enumerate(hints)])

                response += f"\n\n✅ **Создано {len(hints)} подзадач!** Проверь список задач."

                await ctx.reply(response, keyboard=self.get_main_keyboard())

            except Exception as e:
                logging.exception("Error in cmd_decompose")
                await ctx.reply(
                    "❌ Ошибка при разложении задачи",
                    keyboard=self.get_main_keyboard()
                )

        @bot.on_command('analyze')
        async def cmd_analyze(ctx):
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)
                
                tasks = list_tasks(user_id)
                user = get_or_create_user(user_id)
                res = analyze_day(user, tasks)
                
                await ctx.reply(
                    f"📊 **Анализ дня:**\n\n{res['text']}",
                    keyboard=self.get_main_keyboard()
                )
                
                logging.info(f"📊 Пользователь {user_id} запросил анализ дня")
                
            except Exception as e:
                logging.exception("Error in cmd_analyze")
                await ctx.reply(
                    "❌ Ошибка при анализе дня",
                    keyboard=self.get_main_keyboard()
                )

        # Обработка любых сообщений (не команд)
        @bot.on_message()
        async def handle_all_messages(message):
            try:
                user_id = self.normalize_user_id(message.sender)
                self.active_chats[user_id] = message.recipient.chat_id
                self.update_user_activity(user_id)
                
                text = message.body.text or ""
                
                if text.startswith('/'):
                    return
                    
                await message.reply(
                    "🤖 **Бот управления задачами**\n\n"
                    "💡 *Доступные команды:*\n"
                    "`/start` - регистрация\n"
                    "`/add [задача]` - добавить задачу\n"
                    "`/list_tasks` - список задач\n"
                    "`/complete [id]` - завершить задачу\n"
                    "`/motivation` - мотивация\n"
                    "`/decompose [текст/id]` - разложить задачу\n"
                    "`/analyze` - анализ дня\n\n"
                    "🌐 *Задачи синхронизированы с веб-приложением*\n\n"
                    "Выбери действие:",
                    keyboard=self.get_main_keyboard()
                )
                
            except Exception as e:
                logging.exception("Error in handle_all_messages")

        @bot.on_command('test_notification')
        async def cmd_test_notification(ctx):
            """Тестовая команда для проверки уведомлений"""
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)

                # Имитируем, что пользователь неактивен 1 минуту
                self.last_activity[user_id] = datetime.now() - timedelta(minutes=2)

                # Запускаем проверку в тестовом режиме
                await self._check_inactive_users(test_mode=True)

                await ctx.reply(
                    "🧪 Тест запущен! Проверяю систему уведомлений...\n"
                    "Если ты был неактивен более 1 минуты - должно прийти уведомление.",
                    keyboard=self.get_main_keyboard()
                )

            except Exception as e:
                logging.exception("Error in test_notification")
                await ctx.reply("❌ Ошибка тестирования")

        @bot.on_command('force_notification')
        async def cmd_force_notification(ctx):
            """Принудительная отправка тестового уведомления"""
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id

                # Принудительно отправляем тестовое уведомление
                await self._send_inactivity_notification(user_id, test_mode=True)

                await ctx.reply(
                    "✅ Тестовое уведомление отправлено! Проверь сообщения от бота.",
                    keyboard=self.get_main_keyboard()
                )

            except Exception as e:
                logging.exception("Error in force_notification")
                await ctx.reply("❌ Ошибка отправки уведомления")

        @bot.on_command('check_activity')
        async def cmd_check_activity(ctx):
            """Проверить статус активности"""
            try:
                user_id = self.normalize_user_id(ctx.sender)
                self.active_chats[user_id] = ctx.recipient.chat_id
                self.update_user_activity(user_id)

                last_active = self.last_activity.get(user_id)
                if last_active:
                    time_diff = datetime.now() - last_active
                    minutes_diff = int(time_diff.total_seconds() / 60)
                    hours_diff = int(minutes_diff / 60)

                    await ctx.reply(
                        f"📊 **Статус активности:**\n\n"
                        f"🕐 Последняя активность: {last_active.strftime('%H:%M:%S')}\n"
                        f"⏱ Прошло времени: {hours_diff}ч {minutes_diff % 60}м\n"
                        f"👥 Активных пользователей: {len(self.last_activity)}\n\n"
                        f"💡 Уведомление придет через 4 часа неактивности",
                        keyboard=self.get_main_keyboard()
                    )
                else:
                    await ctx.reply(
                        "❌ Данные активности не найдены",
                        keyboard=self.get_main_keyboard()
                    )

            except Exception as e:
                logging.exception("Error in check_activity")
                await ctx.reply("❌ Ошибка проверки активности")

        @bot.on_button_callback(lambda data: data.payload.startswith('page_'))
        async def pagination_handler(cb):
            try:
                user_id = self.normalize_user_id(cb.user)
                self.active_chats[user_id] = cb.message.recipient.chat_id
                self.update_user_activity(user_id)

                # Получаем номер страницы
                page_num = int(cb.payload.split('_')[1])

                # Обновляем состояние
                if user_id in self.pagination_state:
                    self.pagination_state[user_id]['page'] = page_num
                    action_type = self.pagination_state[user_id]['action']
                else:
                    action_type = 'complete'

                tasks = list_tasks(user_id)
                kb, message = self.get_paginated_task_selector(user_id, tasks, action_type)

                if action_type == 'complete':
                    full_message = f"✅ **Завершение задач**\n\n{message}"
                else:
                    full_message = f"🔍 **Просмотр задач**\n\n{message}"

                # ИСПРАВЛЕНИЕ: Используем send_message для стабильности
                await self.bot.send_message(
                    full_message,
                    cb.message.recipient.chat_id,
                    keyboard=kb
                )

            except Exception as e:
                logging.exception("Error in pagination_handler")
                await cb.answer("❌ Ошибка пагинации")

    def run(self):
        logging.info("🚀 Starting Task Bot with real-time synchronization and notifications...")
        self.bot.run()

def main():
    init_db()
    
    bot = TaskBot()
    bot.run()

if __name__ == "__main__":
    main()