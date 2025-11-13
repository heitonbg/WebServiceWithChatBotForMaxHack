from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Text, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, backref
import datetime
import os

def get_db_path():
    if os.path.exists('/data'):
        return "/data/taskbot.db"
    else:
        db_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(db_dir, exist_ok=True)
        return os.path.join(db_dir, 'taskbot.db')

DB_PATH = get_db_path()
SQLITE_URL = f"sqlite:///{DB_PATH}"

print(f"🔗 Using database: {DB_PATH}")

engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    energy = Column(Integer, default=50)
    level = Column(Integer, default=1)
    tasks = relationship('Task', back_populates='user')
    analytics = relationship('Analytics', back_populates='user')
    projects = relationship('Project', back_populates='user')

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    difficulty = Column(Integer, default=1)
    status = Column(String, default="pending")
    estimated_minutes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    task_date = Column(DateTime, default=datetime.datetime.utcnow)

    parent_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)  
    is_parent = Column(Boolean, default=False)  

    user = relationship('User', back_populates='tasks')
    subtasks = relationship('Task', 
                          backref=backref('parent', remote_side=[id]),
                          cascade="all, delete-orphan")  

class Analytics(Base):
    __tablename__ = "analytics"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(DateTime, default=datetime.datetime.utcnow)
    summary = Column(Text)
    result = Column(String)
    user = relationship('User', back_populates='analytics')

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, default="#3b82f6")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    user = relationship('User', back_populates='projects')
    columns = relationship('BoardColumn', back_populates='project', cascade="all, delete-orphan")

class BoardColumn(Base):
    __tablename__ = "board_columns"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String, nullable=False)
    position = Column(Integer, default=0)
    color = Column(String, default="#6b7280")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    project = relationship('Project', back_populates='columns')
    cards = relationship('BoardCard', back_populates='column', cascade="all, delete-orphan")

class BoardCard(Base):
    __tablename__ = "board_cards"
    id = Column(Integer, primary_key=True, index=True)
    column_id = Column(Integer, ForeignKey("board_columns.id"))
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    position = Column(Integer, default=0)
    color = Column(String, default="#ffffff")
    tags = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    estimated_minutes = Column(Integer, default=0)
    priority = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    column = relationship('BoardColumn', back_populates='cards')

def init_db():
    Base.metadata.create_all(bind=engine)