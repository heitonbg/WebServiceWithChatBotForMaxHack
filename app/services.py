import logging
import os
import random
import datetime
import sys
import re
from typing import List, Optional, Tuple
from sqlalchemy import func

sys.path.append(os.path.dirname(__file__))

from models import SessionLocal, User, Task, Analytics, Project, BoardColumn, BoardCard

QUOTES = [
    "Сделай шаг — и дорога появится.",
    "Лучшее время начать — сейчас.",
    "Разбей большую задачу на маленькие шаги.",
    "Маленький прогресс — всё равно прогресс.",
    "Дисциплина — это когда ты делаешь то, что нужно, даже когда не хочется.",
    "Успех — это сумма маленьких усилий, повторяемых изо дня в день.",
    "Не откладывай на завтра то, что можно сделать за две минуты сегодня."
]

def random_motivation():
    return random.choice(QUOTES)

def normalize_user_id(user_id):
    if user_id is None:
        return "demo_user"
        
    if isinstance(user_id, int):
        user_id = str(user_id)
    
    if user_id.isdigit() and not user_id.startswith('max_'):
        user_id = f"max_{user_id}"
    
    return user_id

def get_or_create_user(external_id, name=None):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        
        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            user = User(external_id=external_id, name=name)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def get_user_by_external_id(external_id):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        user = db.query(User).filter_by(external_id=external_id).first()
        return user
    except Exception as e:
        print(f"Error getting user: {e}")
        return None
    finally:
        db.close()

def parse_date(date_str):
    try:
        if not date_str:
            return None

        date_str = date_str.strip()

        formats = [
            '%d.%m.%Y', '%d.%m.%y', '%d/%m/%Y', '%d/%m/%y',  
            '%Y-%m-%d',  
            '%m/%d/%Y', '%m/%d/%y'  
        ]

        for fmt in formats:
            try:
                parsed_date = datetime.datetime.strptime(date_str, fmt)
                return parsed_date.replace(hour=12, minute=0, second=0, microsecond=0)
            except ValueError:
                continue

        return None
    except Exception:
        return None

def validate_date(date_str):
    try:
        if not date_str:
            return None, None

        parsed_date = parse_date(date_str)
        if not parsed_date:
            return None, "❌ Неверный формат даты. Используй: дд.мм.гггг"

        today = datetime.datetime.utcnow().date()
        parsed_date_only = parsed_date.date()

        if parsed_date_only < today:
            return None, f"❌ Дата не может быть раньше сегодняшней ({today.strftime('%d.%m.%Y')})"

        return parsed_date, None

    except Exception as e:
        return None, f"❌ Ошибка при проверке даты: {str(e)}"

def add_task_for_user(external_id, title, estimated_minutes=0, difficulty=1, task_date=None, parent_id=None, is_parent=False):
    """Добавить задачу пользователю с поддержкой дат и подзадач"""
    db = SessionLocal()

    try:
        external_id = normalize_user_id(external_id)

        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            user = User(external_id=external_id)
            db.add(user)
            db.commit()
            db.refresh(user)

        if task_date is None:
            task_date = datetime.datetime.utcnow()
        else:
            if isinstance(task_date, str):
                task_date = parse_date(task_date)
                if not task_date:
                    raise ValueError("Неверный формат даты")

        today = datetime.datetime.utcnow().date()
        if task_date.date() < today:
            raise ValueError(f"Дата не может быть раньше сегодняшней ({today.strftime('%d.%m.%Y')})")

        task = Task(
            user_id=user.id,
            title=title,
            estimated_minutes=estimated_minutes,
            difficulty=difficulty,
            task_date=task_date,
            parent_id=parent_id,
            is_parent=is_parent
        )

        if estimated_minutes > 0 and estimated_minutes <= 2:
            task.status = 'quick'
        else:
            task.status = 'pending'

        db.add(task)
        db.commit()
        db.refresh(task)

        return task
    except Exception as e:
        db.rollback()
        print(f"Error in add_task_for_user: {e}")
        raise e
    finally:
        db.close()

def add_subtask(external_id, parent_task_id, title, estimated_minutes=0, difficulty=1):
    db = SessionLocal()

    try:
        parent_task = db.query(Task).filter_by(id=parent_task_id).first()
        if not parent_task:
            raise ValueError("Родительская задача не найдена")
        
        if parent_task.status == 'done':
            raise ValueError("Нельзя добавлять подзадачи к завершенной задаче")
        
        if parent_task.parent_id is not None:
            raise ValueError("Нельзя добавлять подзадачи к другой подзадаче")

        print(f"✅ Создаем подзадачу для родителя {parent_task_id}: '{title}'")

        subtask = add_task_for_user(
            external_id=external_id,
            title=title,
            estimated_minutes=estimated_minutes,
            difficulty=difficulty,
            parent_id=parent_task_id,
            is_parent=False,
            task_date=parent_task.task_date  
        )

        parent_task.is_parent = True
        db.commit()

        print(f"✅ Подзадача создана: {subtask.id}")
        return subtask

    except Exception as e:
        db.rollback()
        print(f"💥 Ошибка создания подзадачи: {e}")
        raise e
    finally:
        db.close()

def list_tasks(external_id, target_date=None):
    db = SessionLocal()

    try:
        external_id = normalize_user_id(external_id)

        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            return []

        query = db.query(Task).filter_by(user_id=user.id)

        if target_date:
            if isinstance(target_date, str):
                target_date = parse_date(target_date)
            if target_date:
                start_of_day = datetime.datetime.combine(target_date.date(), datetime.time.min)
                end_of_day = datetime.datetime.combine(target_date.date(), datetime.time.max)
                query = query.filter(Task.task_date >= start_of_day, Task.task_date <= end_of_day)

        tasks = query.order_by(Task.task_date.desc(), Task.created_at.desc()).all()
        return tasks
    except Exception as e:
        print(f"Error listing tasks: {e}")
        return []
    finally:
        db.close()

def list_tasks_by_date_range(external_id, start_date, end_date):
    db = SessionLocal()

    try:
        external_id = normalize_user_id(external_id)

        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            return []

        start_of_day = datetime.datetime.combine(start_date.date(), datetime.time.min)
        end_of_day = datetime.datetime.combine(end_date.date(), datetime.time.max)

        tasks = db.query(Task).filter_by(user_id=user.id).filter(
            Task.task_date >= start_of_day,
            Task.task_date <= end_of_day
        ).order_by(Task.task_date.desc(), Task.created_at.desc()).all()

        return tasks
    except Exception as e:
        print(f"Error listing tasks by date range: {e}")
        return []
    finally:
        db.close()

def complete_task(external_id, task_id):
    db = SessionLocal()

    try:
        external_id = normalize_user_id(external_id)

        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            return None

        task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return None

        task.status = 'done'
        db.commit()

        completed_task_data = {
            'id': task.id,
            'title': task.title,
            'status': task.status,
            'is_parent': task.is_parent,
            'parent_id': task.parent_id
        }

        return completed_task_data

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def complete_subtask(external_id, parent_task_id, subtask_id):
    db = SessionLocal()

    try:
        external_id = normalize_user_id(external_id)

        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            return None

        subtask = db.query(Task).filter_by(
            id=subtask_id, 
            user_id=user.id,
            parent_id=parent_task_id
        ).first()
        
        if not subtask:
            return None

        subtask.status = 'done'
        db.commit()

        return {
            'id': subtask.id,
            'title': subtask.title,
            'status': subtask.status
        }

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def complete_parent_task(parent_task_id):
    db = SessionLocal()
    try:
        parent = db.query(Task).filter_by(id=parent_task_id).first()
        if not parent:
            return None

        parent.status = 'done'

        subtasks = db.query(Task).filter_by(parent_id=parent_task_id).all()
        for subtask in subtasks:
            subtask.status = 'done'

        db.commit()

        return {
            'id': parent.id,
            'title': parent.title,
            'subtasks_completed': len(subtasks)
        }
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def get_subtasks(parent_task_id):
    db = SessionLocal()
    try:
        subtasks = db.query(Task).filter_by(parent_id=parent_task_id).order_by(Task.id).all()
        return subtasks
    except Exception as e:
        print(f"💥 Ошибка получения подзадач: {e}")
        return []
    finally:
        db.close()

def get_task_progress(parent_task_id):
    db = SessionLocal()
    try:
        parent_task = db.query(Task).filter_by(id=parent_task_id).first()
        if not parent_task:
            return (0, 0, 0)
        
        if parent_task.status == 'done':
            subtasks = db.query(Task).filter_by(parent_id=parent_task_id).all()
            total = len(subtasks) if subtasks else 1
            return (total, total, 100)
        
        subtasks = db.query(Task).filter_by(parent_id=parent_task_id).all()
        if not subtasks:
            return (0, 0, 0)

        completed = len([t for t in subtasks if t.status == 'done'])
        total = len(subtasks)
        progress = int((completed / total) * 100) if total > 0 else 0

        return (completed, total, progress)
    except Exception as e:
        print(f"💥 Ошибка получения прогресса: {e}")
        return (0, 0, 0)
    finally:
        db.close()

def get_task_by_id(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        return task
    except Exception as e:
        print(f"Error getting task: {e}")
        return None
    finally:
        db.close()

def list_subtasks(external_id, parent_task_id):
    db = SessionLocal()
    try:
        external_id = normalize_user_id(external_id)
        
        user = db.query(User).filter_by(external_id=external_id).first()
        if not user:
            return []

        parent_task = db.query(Task).filter_by(id=parent_task_id, user_id=user.id).first()
        if not parent_task:
            return []

        subtasks = db.query(Task).filter_by(parent_id=parent_task_id, user_id=user.id).order_by(Task.id).all()
        return subtasks
    except Exception as e:
        print(f"Error listing subtasks: {e}")
        return []
    finally:
        db.close()

def analyze_day(user, tasks):
    today = datetime.datetime.utcnow().date()
    done = [t for t in tasks if t.status == 'done' and t.created_at.date() == today]
    pending = [t for t in tasks if t.status != 'done' and t.created_at.date() == today]
    score = len(done) - len(pending)
    
    if score >= 3:
        result = 'success'
        text = f"🎉 Отлично! Сегодня выполнено {len(done)} задач. Ты просто машина продуктивности!"
    elif score >= 1:
        result = 'success'
        text = f"✅ Хорошо! Выполнено {len(done)} задач. Продолжай в том же духе!"
    elif score == 0:
        result = 'neutral'
        text = f"⚖️ Норм. Выполнил {len(done)} задач и откладывал {len(pending)}. Завтра будет лучше!"
    else:
        result = 'fail'
        text = f"💀 Хмм... Выполнено {len(done)} задач, но {len(pending)} не сделано. Не будь нубом — начни с малого!"
    
    return {'result': result, 'text': text, 'stats': {'done': len(done), 'pending': len(pending), 'score': score}}

def update_user_profile(external_id, name=None, energy=None, level=None):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        user = db.query(User).filter_by(external_id=external_id).first()
        
        if user:
            if name is not None:
                user.name = name
            if energy is not None:
                user.energy = energy
            if level is not None:
                user.level = level
                
            db.commit()
            db.refresh(user)
            
        return user
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def sync_user_from_max(external_id, max_user_data):
    if not max_user_data:
        return None
        
    name = f"{max_user_data.get('first_name', '')} {max_user_data.get('last_name', '')}".strip()
    if not name:
        name = max_user_data.get('username', 'Пользователь MAX')
    
    return update_user_profile(external_id, name=name)

def get_user_stats(external_id):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        user = db.query(User).filter_by(external_id=external_id).first()
        
        if not user:
            return None
            
        tasks = db.query(Task).filter_by(user_id=user.id).all()
        total_tasks = len(tasks)
        completed_tasks = len([t for t in tasks if t.status == 'done'])
        pending_tasks = len([t for t in tasks if t.status != 'done'])
        
        completion_rate = round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1)
        
        difficulty_stats = {
            'high': len([t for t in tasks if t.difficulty >= 4]),
            'medium': len([t for t in tasks if t.difficulty == 3]),
            'low': len([t for t in tasks if t.difficulty <= 2]),
        }
        
        return {
            'user_id': user.external_id,
            'name': user.name,
            'energy': user.energy,
            'level': user.level,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'pending_tasks': pending_tasks,
            'completion_rate': completion_rate,
            'difficulty_stats': difficulty_stats
        }
    except Exception as e:
        print(f"Error getting user stats: {e}")
        return None
    finally:
        db.close()

def delete_task(external_id, task_id):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        user = db.query(User).filter_by(external_id=external_id).first()
        
        if not user:
            return False
            
        task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return False
            
        db.delete(task)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def update_task(external_id, task_id, title=None, description=None, estimated_minutes=None, 
               difficulty=None, status=None, task_date=None):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        user = db.query(User).filter_by(external_id=external_id).first()
        
        if not user:
            return None
            
        task = db.query(Task).filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return None
            
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if estimated_minutes is not None:
            task.estimated_minutes = estimated_minutes
        if difficulty is not None:
            task.difficulty = difficulty
        if status is not None:
            task.status = status
        if task_date is not None:
            if hasattr(task_date, 'date'):
                today = datetime.datetime.utcnow().date()
                task_date_only = task_date.date()
                if task_date_only < today:
                    raise ValueError(f"Дата не может быть раньше сегодняшней ({today.strftime('%d.%m.%Y')})")
            task.task_date = task_date
            
        db.commit()
        db.refresh(task)
        return task
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def get_today_stats(external_id):
    db = SessionLocal()
    
    try:
        external_id = normalize_user_id(external_id)
        user = db.query(User).filter_by(external_id=external_id).first()
        
        if not user:
            return None
            
        today = datetime.datetime.utcnow().date()
        tasks = db.query(Task).filter_by(user_id=user.id).filter(
            Task.created_at >= today
        ).all()
        
        completed_today = len([t for t in tasks if t.status == 'done'])
        pending_today = len([t for t in tasks if t.status != 'done'])
        
        return {
            'completed_today': completed_today,
            'pending_today': pending_today,
            'total_today': len(tasks)
        }
    except Exception as e:
        print(f"Error getting today stats: {e}")
        return None
    finally:
        db.close()

def get_user_by_max_id(max_user_id):
    db = SessionLocal()
    try:
        external_id = f"max_{max_user_id}"
        user = db.query(User).filter_by(external_id=external_id).first()
        return user
    finally:
        db.close()

def sync_tasks_between_users(source_user_id, target_user_id):
    db = SessionLocal()
    try:
        source_user = db.query(User).filter_by(external_id=source_user_id).first()
        target_user = db.query(User).filter_by(external_id=target_user_id).first()
        
        if not source_user or not target_user:
            return False
            
        source_tasks = db.query(Task).filter_by(user_id=source_user.id).all()
        
        for task in source_tasks:
            existing_task = db.query(Task).filter_by(
                user_id=target_user.id, 
                title=task.title,
                status=task.status
            ).first()
            
            if not existing_task:
                new_task = Task(
                    user_id=target_user.id,
                    title=task.title,
                    description=task.description,
                    difficulty=task.difficulty,
                    status=task.status,
                    estimated_minutes=task.estimated_minutes,
                    task_date=task.task_date
                )
                db.add(new_task)
        
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Sync error: {e}")
        return False
    finally:
        db.close()

def enhanced_daily_analysis(user, tasks):
    today = datetime.datetime.utcnow().date()
    today_tasks = [t for t in tasks if t.created_at.date() == today]
    
    if not today_tasks:
        return {
            'result': 'neutral',
            'text': "📝 Сегодня еще нет задач. Начни с маленького шага!",
            'recommendation': "Попробуй добавить быструю задачу на 2 минуты.",
            'emoji': "🤔"
        }
    
    completed_today = [t for t in today_tasks if t.status == 'done']
    pending_today = [t for t in today_tasks if t.status != 'done']
    
    completion_ratio = len(completed_today) / len(today_tasks) if today_tasks else 0
    
    avg_difficulty = sum(t.difficulty for t in today_tasks) / len(today_tasks)
    completed_difficulty = sum(t.difficulty for t in completed_today) / len(completed_today) if completed_today else 0
    
    if completion_ratio >= 0.8:
        result = 'success'
        emoji = "🎉"
        text = f"Отлично! Выполнено {len(completed_today)} из {len(today_tasks)} задач!"
        recommendation = "Ты сегодня на высоте! Можешь взяться за что-то сложное."
    elif completion_ratio >= 0.5:
        result = 'success'
        emoji = "👍"
        text = f"Хорошо! Выполнено {len(completed_today)} из {len(today_tasks)} задач."
        recommendation = "Продолжай в том же духе! Ты близок к отличному результату."
    elif completion_ratio > 0:
        result = 'neutral'
        emoji = "💪"
        text = f"Неплохо, но можно лучше. Выполнено {len(completed_today)} из {len(today_tasks)}."
        recommendation = "Сосредоточься на одной задаче за раз. Используй Pomodoro таймер!"
    else:
        result = 'fail'
        emoji = "💀"
        text = f"Эй, нубик! 0 из {len(today_tasks)} задач выполнено. Соберись!"
        recommendation = "Начни с самой простой задачи. Даже 2 минуты работы - это прогресс!"
    
    if avg_difficulty > 3 and completion_ratio < 0.5:
        recommendation += " Слишком сложные задачи? Разбей их на части командой /decompose"
    
    return {
        'result': result,
        'text': text,
        'recommendation': recommendation,
        'emoji': emoji,
        'stats': {
            'completed': len(completed_today),
            'pending': len(pending_today),
            'total': len(today_tasks),
            'completion_ratio': round(completion_ratio * 100),
            'avg_difficulty': round(avg_difficulty, 1)
        }
    }

def ensure_user_sync(max_user_id, username):
    db = SessionLocal()
    try:
        max_external_id = f"max_{max_user_id}"
        web_external_id = f"user_{username.lower().replace(' ', '_')}"
        
        max_user = db.query(User).filter_by(external_id=max_external_id).first()
        web_user = db.query(User).filter_by(external_id=web_external_id).first()
        
        if max_user and web_user and max_user.id != web_user.id:
            sync_tasks_between_users(max_external_id, web_external_id)
            sync_tasks_between_users(web_external_id, max_external_id)
            
        return web_external_id
    finally:
        db.close()

try:
    from gigachat_client import gigachat_client
    
    def decompose_task(title: str, user_id: str = None) -> List[str]:
        """
        Разложить задачу на подзадачи и автоматически создать иерархию задач
        """
        print(f"🔍 decompose_task вызвана с: '{title}' для пользователя: {user_id}")

        try:
            parent_task = add_task_for_user(
                external_id=user_id,
                title=title,
                is_parent=True 
            )
            print(f"✅ Создана родительская задача: {parent_task.id} - '{title}'")

            ai_steps = gigachat_client.decompose_task(title)

            if ai_steps:
                print(f"✅ GigaChat вернул шаги: {ai_steps}")

                created_subtasks = []
                for step in ai_steps:
                    subtask = add_subtask(
                        external_id=user_id,
                        parent_task_id=parent_task.id,
                        title=step
                    )
                    created_subtasks.append(subtask)
                    print(f"✅ Создана подзадача: {subtask.id} - '{step}'")

                print(f"✅ Автоматически создано {len(created_subtasks)} подзадач")
                return ai_steps

            else:
                print("❌ GigaChat не вернул шаги, используем fallback")
                fallback_steps = decompose_task_fallback(title)
                if user_id and fallback_steps:
                    for step in fallback_steps:
                        add_subtask(user_id, parent_task.id, step)
                return fallback_steps

        except Exception as e:
            print(f"💥 Ошибка в decompose_task: {e}")
            logging.error(f"Decomposition failed: {e}")
            return decompose_task_fallback(title)

    def decompose_task_fallback(title: str) -> List[str]:
        hints = []
        parts = [p.strip() for p in (title.replace(' и ', ',').split(',')) if p.strip()]

        if len(parts) <= 1:
            words = title.split()
            if len(words) <= 3:
                hints = [
                    f"1. Подготовить всё необходимое для '{title}'",
                    f"2. Выполнить основные действия",
                    f"3. Проверить результат и завершить"
                ]
            else:
                for i, word in enumerate(words[:4], 1):
                    hints.append(f"{i}. Действие, связанное с '{word}'")
        else:
            for i, p in enumerate(parts[:4], 1):
                hints.append(f"{i}. {p}")

        return hints

except ImportError:
    print("⚠️ GigaChat client not available")
    
    def decompose_task(title: str, user_id: str = None) -> List[str]:
        """Fallback decomposition without GigaChat"""
        fallback_steps = decompose_task_fallback(title)
        
        if user_id:
            parent_task = add_task_for_user(
                external_id=user_id,
                title=title,
                is_parent=True
            )
            print(f"✅ Создана родительская задача: {parent_task.id} - '{title}'")
            
            for step in fallback_steps:
                add_subtask(user_id, parent_task.id, step)
            print(f"✅ Создано {len(fallback_steps)} подзадач из fallback")
        
        return fallback_steps
    
    def decompose_task_fallback(title: str) -> List[str]:
        """Fallback decomposition logic"""
        hints = []
        parts = [p.strip() for p in (title.replace(' и ', ',').split(',')) if p.strip()]

        if len(parts) <= 1:
            words = title.split()
            if len(words) <= 3:
                hints = [
                    f"1. Подготовить всё необходимое для '{title}'",
                    f"2. Выполнить основные действия",
                    f"3. Проверить результат и завершить"
                ]
            else:
                for i, word in enumerate(words[:4], 1):
                    hints.append(f"{i}. Действие, связанное с '{word}'")
        else:
            for i, p in enumerate(parts[:4], 1):
                hints.append(f"{i}. {p}")

        return hints

def create_project(external_id, title, description=None, color="#3b82f6"):
    """Создать новый проект"""
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return None
        
        project = Project(
            user_id=user.id,
            title=title,
            description=description,
            color=color
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        
        default_columns = [
            {"title": "📋 Бэклог", "color": "#6b7280", "position": 0},
            {"title": "🔄 В работе", "color": "#f59e0b", "position": 1},
            {"title": "✅ Готово", "color": "#10b981", "position": 2}
        ]
        
        for col_data in default_columns:
            column = BoardColumn(
                project_id=project.id,
                title=col_data["title"],
                color=col_data["color"],
                position=col_data["position"]
            )
            db.add(column)
        
        db.commit()
        return project
        
    except Exception as e:
        db.rollback()
        print(f"Error creating project: {e}")
        return None
    finally:
        db.close()

def get_user_projects(external_id):
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return []
        
        projects = db.query(Project).filter_by(user_id=user.id).order_by(Project.created_at.desc()).all()
        return projects
    except Exception as e:
        print(f"Error getting user projects: {e}")
        return []
    finally:
        db.close()

def create_card(column_id, external_id, title, description=None, color="#ffffff", tags=None, 
                due_date=None, estimated_minutes=0, priority=1):
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return None
        
        column = db.query(BoardColumn).join(Project).filter(
            BoardColumn.id == column_id,
            Project.user_id == user.id
        ).first()
        if not column:
            return None
        
        max_position_result = db.query(func.max(BoardCard.position)).filter_by(column_id=column_id).first()
        max_position = max_position_result[0] if max_position_result[0] is not None else 0
        
        tags_str = None
        if tags:
            tags_str = ','.join(tags)
        
        card = BoardCard(
            column_id=column_id,
            title=title,
            description=description,
            color=color,
            tags=tags_str,
            due_date=due_date,
            estimated_minutes=estimated_minutes,
            priority=priority,
            position=max_position + 1
        )
        db.add(card)
        db.commit()
        db.refresh(card)
        
        return card
        
    except Exception as e:
        db.rollback()
        print(f"Error creating card: {e}")
        return None
    finally:
        db.close()

def get_project_with_details(project_id, external_id):
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return None
        
        project = db.query(Project).filter_by(id=project_id, user_id=user.id).first()
        if not project:
            return None
        
        columns = db.query(BoardColumn).filter_by(project_id=project_id).order_by(BoardColumn.position).all()
        
        result_columns = []
        for column in columns:
            cards = db.query(BoardCard).filter_by(column_id=column.id).order_by(BoardCard.position).all()
            
            column_data = {
                "id": column.id,
                "title": column.title,
                "color": column.color,
                "position": column.position,
                "cards": []
            }
            
            for card in cards:
                card_data = {
                    "id": card.id,
                    "title": card.title,
                    "description": card.description,
                    "color": card.color,
                    "tags": card.tags.split(',') if card.tags else [],
                    "due_date": card.due_date,
                    "estimated_minutes": card.estimated_minutes,
                    "priority": card.priority,
                    "position": card.position,
                    "created_at": card.created_at,
                    "updated_at": card.updated_at
                }
                column_data["cards"].append(card_data)
            
            result_columns.append(column_data)
        
        project_data = {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "color": project.color,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "columns": result_columns
        }
        
        return project_data
        
    except Exception as e:
        print(f"Error getting project details: {e}")
        return None
    finally:
        db.close()

def update_card_position(card_id, external_id, new_column_id=None, new_position=None):
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return False
        
        card = db.query(BoardCard).join(BoardColumn).join(Project).filter(
            BoardCard.id == card_id,
            Project.user_id == user.id
        ).first()
        if not card:
            return False
        
        if new_column_id is not None:
            new_column = db.query(BoardColumn).join(Project).filter(
                BoardColumn.id == new_column_id,
                Project.user_id == user.id
            ).first()
            if not new_column:
                return False
            card.column_id = new_column_id
        
        if new_position is not None:
            card.position = new_position
        
        card.updated_at = datetime.datetime.utcnow()
        db.commit()
        return True
        
    except Exception as e:
        db.rollback()
        print(f"Error updating card position: {e}")
        return False
    finally:
        db.close()

def delete_card(card_id, external_id):
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return False
        
        card = db.query(BoardCard).join(BoardColumn).join(Project).filter(
            BoardCard.id == card_id,
            Project.user_id == user.id
        ).first()
        if not card:
            return False
        
        db.delete(card)
        db.commit()
        return True
        
    except Exception as e:
        db.rollback()
        print(f"Error deleting card: {e}")
        return False
    finally:
        db.close()

def delete_project(project_id, external_id):
    db = SessionLocal()
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return False
        
        project = db.query(Project).filter_by(id=project_id, user_id=user.id).first()
        if not project:
            return False
        
        db.delete(project)
        db.commit()
        return True
        
    except Exception as e:
        db.rollback()
        print(f"Error deleting project: {e}")
        return False
    finally:
        db.close()