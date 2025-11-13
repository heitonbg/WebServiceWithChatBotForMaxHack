from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import SessionLocal, User, Task, init_db, Project, BoardColumn, BoardCard
from services import (
    get_or_create_user, add_task_for_user, list_tasks, complete_task, 
    analyze_day, sync_user_from_max, get_user_stats, update_user_profile,
    get_user_by_external_id, get_today_stats, get_user_by_max_id,
    sync_tasks_between_users, ensure_user_sync,
    create_project, get_user_projects, create_card, get_project_with_details,
    update_card_position, delete_card, delete_project,
    parse_date, validate_date, list_tasks_by_date_range,  
    add_subtask, complete_subtask, list_subtasks,        
    update_task, delete_task                             
)

app = FastAPI(title="TaskBot API")

init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:5173", 
        "http://localhost:8080", 
        "https://max.ru",
        "https://webtomax.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TaskCreate(BaseModel):
    title: str
    estimated_minutes: int = 0
    difficulty: int = 1
    task_date: Optional[str] = None
    parent_task_id: Optional[int] = None  

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    estimated_minutes: Optional[int] = None
    difficulty: Optional[int] = None
    status: Optional[str] = None
    task_date: Optional[str] = None

class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    difficulty: int
    status: str
    estimated_minutes: int
    created_at: datetime.datetime
    task_date: datetime.datetime
    parent_task_id: Optional[int]
    subtasks: List['TaskResponse'] = []

    class Config:
        from_attributes = True

class CompleteTaskRequest(BaseModel):
    task_id: int

class SubtaskCreate(BaseModel):
    title: str
    estimated_minutes: int = 0
    difficulty: int = 1

class UserSyncRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    photo_url: Optional[str] = None

class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    energy: Optional[int] = None
    level: Optional[int] = None

class SyncRequest(BaseModel):
    max_user_id: str
    username: str

class DateRangeRequest(BaseModel):
    start_date: str
    end_date: str

class ProjectCreate(BaseModel):
    title: str
    description: Optional[str] = None
    color: Optional[str] = "#3b82f6"

class ColumnCreate(BaseModel):
    title: str
    color: Optional[str] = "#6b7280"

class CardCreate(BaseModel):
    title: str
    description: Optional[str] = None
    color: Optional[str] = "#ffffff"
    tags: Optional[List[str]] = None
    due_date: Optional[datetime.datetime] = None
    estimated_minutes: Optional[int] = 0
    priority: Optional[int] = 1

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    tags: Optional[List[str]] = None
    due_date: Optional[datetime.datetime] = None
    estimated_minutes: Optional[int] = None
    priority: Optional[int] = None
    column_id: Optional[int] = None
    position: Optional[int] = None

class ColumnReorderRequest(BaseModel):
    columns: List[Dict[str, Any]]

class CardReorderRequest(BaseModel):
    cards: List[Dict[str, Any]]

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def root():
    return {"message": "TaskBot API", "status": "running"}

@app.get("/tasks/list")
async def get_tasks(external_id: str, db: Session = Depends(get_db)):
    try:
        tasks = list_tasks(external_id)
        return {"tasks": tasks, "count": len(tasks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/create")
async def create_task(task_data: TaskCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        task_date = None
        if task_data.task_date:
            task_date = parse_date(task_data.task_date)
            if not task_date:
                raise HTTPException(status_code=400, detail="❌ Неверный формат даты. Используй: дд.мм.гггг или гггг-мм-дд")
            
            today = datetime.datetime.utcnow().date()
            if task_date.date() < today:
                raise HTTPException(status_code=400, detail=f"❌ Дата не может быть раньше сегодняшней ({today.strftime('%d.%m.%Y')})")

        if task_data.parent_task_id:
            task = add_subtask(
                external_id,
                task_data.parent_task_id,
                task_data.title,
                task_data.estimated_minutes,
                task_data.difficulty
            )
        else:
            task = add_task_for_user(
                external_id,
                task_data.title,
                task_data.estimated_minutes,
                task_data.difficulty,
                task_date
            )
        
        if not task:
            raise HTTPException(status_code=500, detail="Failed to create task")
            
        return {"task": task, "message": "Task created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/complete")
async def complete_task_endpoint(request: CompleteTaskRequest, external_id: str, db: Session = Depends(get_db)):
    try:
        task = complete_task(external_id, request.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": task, "message": "Task completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/tasks/{task_id}")
async def update_task_endpoint(task_id: int, task_data: TaskUpdate, external_id: str, db: Session = Depends(get_db)):
    try:
        task_date = None
        if task_data.task_date:
            task_date, error_msg = validate_date(task_data.task_date)
            if error_msg:
                raise HTTPException(status_code=400, detail=error_msg)

        task = update_task(
            external_id,
            task_id,
            title=task_data.title,
            description=task_data.description,
            estimated_minutes=task_data.estimated_minutes,
            difficulty=task_data.difficulty,
            status=task_data.status,
            task_date=task_date
        )
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
            
        return {"task": task, "message": "Task updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        success = delete_task(external_id, task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return {"message": "Task deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/list-by-date")
async def get_tasks_by_date(external_id: str, date: str, db: Session = Depends(get_db)):
    try:
        target_date = parse_date(date)
        if not target_date:
            raise HTTPException(status_code=400, detail="Неверный формат даты")
            
        tasks = list_tasks(external_id, target_date)
        return {"tasks": tasks, "count": len(tasks), "date": date}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/list-by-date-range")
async def get_tasks_by_date_range(external_id: str, date_range: DateRangeRequest, db: Session = Depends(get_db)):
    try:
        start_date = parse_date(date_range.start_date)
        end_date = parse_date(date_range.end_date)
        tasks = list_tasks_by_date_range(external_id, start_date, end_date)
        return {
            "tasks": tasks, 
            "count": len(tasks), 
            "start_date": date_range.start_date,
            "end_date": date_range.end_date
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/{task_id}/subtasks")
async def create_subtask_endpoint(task_id: int, subtask_data: SubtaskCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        subtask = add_subtask(
            external_id,
            task_id,
            subtask_data.title,
            subtask_data.estimated_minutes,
            subtask_data.difficulty
        )
        
        if not subtask:
            raise HTTPException(status_code=404, detail="Parent task not found or access denied")
            
        return {"subtask": subtask, "message": "Subtask created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/{task_id}/subtasks/{subtask_id}/complete")
async def complete_subtask_endpoint(task_id: int, subtask_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        subtask = complete_subtask(external_id, task_id, subtask_id)
        if not subtask:
            raise HTTPException(status_code=404, detail="Subtask not found")
        return {"subtask": subtask, "message": "Subtask completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}/subtasks")
async def get_subtasks_endpoint(task_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        subtasks = list_subtasks(external_id, task_id)
        return {"subtasks": subtasks, "count": len(subtasks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/analytics")
async def get_user_analytics(external_id: str, db: Session = Depends(get_db)):
    try:
        tasks = list_tasks(external_id)
        user = get_or_create_user(external_id)
        analytics = analyze_day(user, tasks)
        return analytics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/profile")
async def get_user_profile(external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_or_create_user(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        tasks = list_tasks(external_id)
        total_tasks = len(tasks)
        completed_tasks = len([t for t in tasks if t.status == 'done'])
        
        profile_data = {
            "user_id": user.external_id,
            "name": user.name,
            "energy": user.energy,
            "level": user.level,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "completion_rate": round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1),
            "created_at": user.created_at
        }
        
        return profile_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/user/sync")
async def sync_user(request: UserSyncRequest, external_id: str, db: Session = Depends(get_db)):
    try:
        user_data = request.dict()
        user = sync_user_from_max(external_id, user_data)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        return {
            "user": {
                "external_id": user.external_id,
                "name": user.name,
                "energy": user.energy,
                "level": user.level
            },
            "message": "User synchronized successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/stats")
async def get_user_stats_endpoint(external_id: str, db: Session = Depends(get_db)):
    try:
        stats = get_user_stats(external_id)
        if not stats:
            raise HTTPException(status_code=404, detail="User not found")
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/user/profile")
async def update_user_profile_endpoint(request: UserUpdateRequest, external_id: str, db: Session = Depends(get_db)):
    try:
        user = update_user_profile(
            external_id,
            name=request.name,
            energy=request.energy,
            level=request.level
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        return {
            "user": {
                "external_id": user.external_id,
                "name": user.name,
                "energy": user.energy,
                "level": user.level
            },
            "message": "Profile updated successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/today-stats")
async def get_today_stats_endpoint(external_id: str, db: Session = Depends(get_db)):
    try:
        stats = get_today_stats(external_id)
        if not stats:
            raise HTTPException(status_code=404, detail="User not found")
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "service": "TaskBot API"
    }

@app.post("/tasks/decompose")
async def decompose_task_endpoint(task_data: TaskCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        from services import decompose_task
        
        task_date = None
        if task_data.task_date:
            task_date = parse_date(task_data.task_date)
            if not task_date:
                raise HTTPException(status_code=400, detail="❌ Неверный формат даты. Используй: дд.мм.гггг или гггг-мм-дд")
            
            today = datetime.datetime.utcnow().date()
            if task_date.date() < today:
                raise HTTPException(status_code=400, detail=f"❌ Дата не может быть раньше сегодняшней ({today.strftime('%d.%m.%Y')})")

        steps = decompose_task(task_data.title, external_id)
        
        if not steps:
            raise HTTPException(status_code=500, detail="Не удалось разложить задачу")
            
        return {
            "steps": steps,
            "message": f"Задача разложена на {len(steps)} подзадач"
        }
        
    except Exception as e:
        print(f"Error decomposing task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/user/{external_id}")
async def debug_user(external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return {"error": "User not found"}
            
        tasks = list_tasks(external_id)
        
        return {
            "user": {
                "id": user.id,
                "external_id": user.external_id,
                "name": user.name,
                "energy": user.energy,
                "level": user.level,
                "created_at": user.created_at
            },
            "tasks_count": len(tasks),
            "tasks": [{"id": t.id, "title": t.title, "status": t.status} for t in tasks[:5]]
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/user/create")
async def create_user_endpoint(external_id: str, name: str, db: Session = Depends(get_db)):
    try:
        user = get_or_create_user(external_id, name)
        return {
            "user": {
                "external_id": user.external_id,
                "name": user.name,
                "energy": user.energy,
                "level": user.level
            },
            "message": "User created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/user/sync-with-bot")
async def sync_with_bot(request: SyncRequest, db: Session = Depends(get_db)):
    try:
        external_id = ensure_user_sync(request.max_user_id, request.username)
        return {
            "external_id": external_id,
            "message": "User synchronized with bot"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/bot-tasks")
async def get_bot_tasks(max_user_id: str, db: Session = Depends(get_db)):
    try:
        external_id = f"max_{max_user_id}"
        tasks = list_tasks(external_id)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync/users")
async def sync_users(source_external_id: str, target_external_id: str, db: Session = Depends(get_db)):
    try:
        success = sync_tasks_between_users(source_external_id, target_external_id)
        if not success:
            raise HTTPException(status_code=404, detail="Users not found or sync failed")
        return {"message": "Users synchronized successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/user/daily-stats")
async def get_daily_stats(external_id: str, db: Session = Depends(get_db)):
    try:
        today = datetime.datetime.utcnow().date()
        tasks = list_tasks(external_id)
        
        today_tasks = [t for t in tasks if t.created_at.date() == today]
        completed_today = len([t for t in today_tasks if t.status == 'done'])
        pending_today = len([t for t in today_tasks if t.status != 'done'])
        
        if completed_today == 0 and pending_today == 0:
            analysis = {
                "message": "Сегодня еще нет задач. Начни с чего-то маленького!",
                "emoji": "🤔",
                "is_positive": False
            }
        elif completed_today >= pending_today * 2:
            analysis = {
                "message": "Отличная работа! Ты сегодня просто машина продуктивности!",
                "emoji": "🎉",
                "is_positive": True
            }
        elif completed_today > pending_today:
            analysis = {
                "message": "Хороший день! Продолжай в том же духе!",
                "emoji": "👍",
                "is_positive": True
            }
        else:
            analysis = {
                "message": "Эй, нубик! Больше незавершенных задач, чем выполненных. Соберись!",
                "emoji": "💀",
                "is_positive": False
            }
        
        return {
            "completed_today": completed_today,
            "pending_today": pending_today,
            "total_today": len(today_tasks),
            "analysis": analysis
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/productivity-stats")
async def get_productivity_stats(external_id: str, db: Session = Depends(get_db)):
    try:
        tasks = list_tasks(external_id)
        completed_tasks = [t for t in tasks if t.status == 'done']
        pending_tasks = [t for t in tasks if t.status != 'done']
        
        total_energy = sum(t.difficulty for t in tasks) if tasks else 1
        completed_energy = sum(t.difficulty for t in completed_tasks)
        productivity_score = round((completed_energy / total_energy) * 100) if total_energy > 0 else 0
        
        if productivity_score >= 80:
            temperature = 5
            temperature_label = "🔥 Горячий перфекционист!"
        elif productivity_score >= 60:
            temperature = 4
            temperature_label = "😎 Теплый профессионал"
        elif productivity_score >= 40:
            temperature = 3
            temperature_label = "😊 Стабильный работник"
        elif productivity_score >= 20:
            temperature = 2
            temperature_label = "🤔 Нагревающийся"
        else:
            temperature = 1
            temperature_label = "❄️ Охлажденный"
        
        completed_dates = [t.created_at.date() for t in completed_tasks]
        unique_dates = sorted(set(completed_dates), reverse=True)
        
        streak = 0
        today = datetime.datetime.utcnow().date()
        for i, date in enumerate(unique_dates):
            if (today - date).days == i:
                streak += 1
            else:
                break
        
        return {
            "completed_tasks": len(completed_tasks),
            "pending_tasks": len(pending_tasks),
            "completion_rate": round((len(completed_tasks) / len(tasks)) * 100) if tasks else 0,
            "productivity_score": productivity_score,
            "temperature": temperature,
            "temperature_label": temperature_label,
            "streak": streak,
            "total_tasks": len(tasks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kanban/projects")
async def get_projects(external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        projects = get_user_projects(external_id)
        
        result = []
        for project in projects:
            project_details = get_project_with_details(project.id, external_id)
            if project_details:
                result.append(project_details)
        
        return {"projects": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/kanban/projects")
async def create_project_endpoint(project_data: ProjectCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        project = Project(
            user_id=user.id,
            title=project_data.title,
            description=project_data.description,
            color=project_data.color
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
        
        project_details = get_project_with_details(project.id, external_id)
        
        return {
            "project": project_details,
            "message": "Project created successfully"
        }
    except Exception as e:
        db.rollback()
        print(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating project: {str(e)}")

@app.post("/kanban/projects/{project_id}/columns")
async def create_column_endpoint(project_id: int, column_data: ColumnCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        project = db.query(Project).filter_by(id=project_id, user_id=user.id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        max_position = db.query(func.max(BoardColumn.position)).filter_by(project_id=project_id).scalar() or 0
        
        column = BoardColumn(
            project_id=project_id,
            title=column_data.title,
            color=column_data.color,
            position=max_position + 1
        )
        db.add(column)
        db.commit()
        db.refresh(column)
        
        return {"column": column, "message": "Column created successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/kanban/columns/{column_id}/cards")
async def create_card_endpoint(column_id: int, card_data: CardCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        card = create_card(
            column_id,
            external_id,
            card_data.title,
            card_data.description,
            card_data.color,
            card_data.tags,
            card_data.due_date,
            card_data.estimated_minutes,
            card_data.priority
        )
        
        if not card:
            raise HTTPException(status_code=404, detail="Column not found or access denied")
        
        card_response = {
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
        
        return {"card": card_response, "message": "Card created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/kanban/cards/{card_id}")
async def update_card_endpoint(card_id: int, card_data: CardUpdate, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        card = db.query(BoardCard).join(BoardColumn).join(Project).filter(
            BoardCard.id == card_id,
            Project.user_id == user.id
        ).first()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        
        if card_data.title is not None:
            card.title = card_data.title
        if card_data.description is not None:
            card.description = card_data.description
        if card_data.color is not None:
            card.color = card_data.color
        if card_data.tags is not None:
            card.tags = ','.join(card_data.tags)
        if card_data.due_date is not None:
            card.due_date = card_data.due_date
        if card_data.estimated_minutes is not None:
            card.estimated_minutes = card_data.estimated_minutes
        if card_data.priority is not None:
            card.priority = card_data.priority
        if card_data.column_id is not None:
            card.column_id = card_data.column_id
        if card_data.position is not None:
            card.position = card_data.position
        
        card.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(card)
        
        card_response = {
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
        
        return {"card": card_response, "message": "Card updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/kanban/cards/{card_id}")
async def delete_card_endpoint(card_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        success = delete_card(card_id, external_id)
        if not success:
            raise HTTPException(status_code=404, detail="Card not found")
        
        return {"message": "Card deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/kanban/projects/{project_id}")
async def delete_project_endpoint(project_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        success = delete_project(project_id, external_id)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return {"message": "Project deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/kanban/projects/{project_id}/columns/reorder")
async def reorder_columns(project_id: int, request: ColumnReorderRequest, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        project = db.query(Project).filter_by(id=project_id, user_id=user.id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        for col_data in request.columns:
            column = db.query(BoardColumn).filter_by(id=col_data["id"], project_id=project_id).first()
            if column:
                column.position = col_data["position"]
        
        db.commit()
        
        return {"message": "Columns reordered successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/kanban/columns/{column_id}/cards/reorder")
async def reorder_cards(column_id: int, request: CardReorderRequest, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        column = db.query(BoardColumn).join(Project).filter(
            BoardColumn.id == column_id,
            Project.user_id == user.id
        ).first()
        if not column:
            raise HTTPException(status_code=404, detail="Column not found")
        
        for card_data in request.cards:
            card = db.query(BoardCard).filter_by(id=card_data["id"]).first()
            if card:
                card.position = card_data["position"]
                if "column_id" in card_data and card_data["column_id"] != column_id:
                    new_column = db.query(BoardColumn).join(Project).filter(
                        BoardColumn.id == card_data["column_id"],
                        Project.user_id == user.id
                    ).first()
                    if new_column:
                        card.column_id = card_data["column_id"]
        
        db.commit()
        
        return {"message": "Cards reordered successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/kanban/projects/{project_id}")
async def update_project_endpoint(project_id: int, project_data: ProjectCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        project = db.query(Project).filter_by(id=project_id, user_id=user.id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if project_data.title is not None:
            project.title = project_data.title
        if project_data.description is not None:
            project.description = project_data.description
        if project_data.color is not None:
            project.color = project_data.color
        
        project.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(project)
        
        return {"project": project, "message": "Project updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/kanban/columns/{column_id}")
async def update_column_endpoint(column_id: int, column_data: ColumnCreate, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        column = db.query(BoardColumn).join(Project).filter(
            BoardColumn.id == column_id,
            Project.user_id == user.id
        ).first()
        if not column:
            raise HTTPException(status_code=404, detail="Column not found")
        
        if column_data.title is not None:
            column.title = column_data.title
        if column_data.color is not None:
            column.color = column_data.color
        
        db.commit()
        db.refresh(column)
        
        return {"column": column, "message": "Column updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/kanban/columns/{column_id}")
async def delete_column_endpoint(column_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        column = db.query(BoardColumn).join(Project).filter(
            BoardColumn.id == column_id,
            Project.user_id == user.id
        ).first()
        if not column:
            raise HTTPException(status_code=404, detail="Column not found")
        
        db.query(BoardCard).filter_by(column_id=column_id).delete()
        db.delete(column)
        db.commit()
        
        return {"message": "Column deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kanban/projects/{project_id}/stats")
async def get_project_stats(project_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        project = db.query(Project).filter_by(id=project_id, user_id=user.id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        cards = db.query(BoardCard).join(BoardColumn).filter(
            BoardColumn.project_id == project_id
        ).all()
        
        total_cards = len(cards)
        
        priority_stats = {
            1: len([c for c in cards if c.priority == 1]),
            2: len([c for c in cards if c.priority == 2]),
            3: len([c for c in cards if c.priority == 3]),
            4: len([c for c in cards if c.priority == 4]),
            5: len([c for c in cards if c.priority == 5])
        }
        
        columns = db.query(BoardColumn).filter_by(project_id=project_id).all()
        column_stats = {}
        for column in columns:
            column_cards = db.query(BoardCard).filter_by(column_id=column.id).all()
            column_stats[column.title] = len(column_cards)
        
        total_estimated_minutes = sum(card.estimated_minutes for card in cards)
        
        return {
            "project_id": project_id,
            "total_cards": total_cards,
            "priority_stats": priority_stats,
            "column_stats": column_stats,
            "total_estimated_minutes": total_estimated_minutes,
            "total_estimated_hours": round(total_estimated_minutes / 60, 1)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/kanban/columns/{column_id}")
async def debug_column(column_id: int, external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return {"error": "User not found"}
        
        column = db.query(BoardColumn).join(Project).filter(
            BoardColumn.id == column_id,
            Project.user_id == user.id
        ).first()
        
        if not column:
            return {"error": "Column not found or access denied"}
        
        return {
            "column": {
                "id": column.id,
                "title": column.title,
                "project_id": column.project_id,
                "project_title": column.project.title,
                "user_id": column.project.user_id
            },
            "user": {
                "id": user.id,
                "external_id": user.external_id,
                "name": user.name
            }
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/kanban/projects")
async def debug_projects(external_id: str, db: Session = Depends(get_db)):
    try:
        user = get_user_by_external_id(external_id)
        if not user:
            return {"error": "User not found"}
        
        projects = db.query(Project).filter_by(user_id=user.id).all()
        
        result = []
        for project in projects:
            columns = db.query(BoardColumn).filter_by(project_id=project.id).all()
            result.append({
                "id": project.id,
                "title": project.title,
                "user_id": project.user_id,
                "columns_count": len(columns),
                "columns": [{"id": c.id, "title": c.title} for c in columns]
            })
        
        return {
            "user": {
                "id": user.id,
                "external_id": user.external_id,
                "name": user.name
            },
            "projects": result
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)