"""
Database models and setup for Medicine Reminder Bot
Using SQLAlchemy 2.0 with modern typing and async support
"""

import os
from datetime import datetime, time
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Time, Text, ForeignKey, Float
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models"""
    pass


class User(Base):
    """User model for storing Telegram user information"""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(50), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    medicines: Mapped[List["Medicine"]] = relationship("Medicine", back_populates="user", cascade="all, delete-orphan")
    caregivers: Mapped[List["Caregiver"]] = relationship("Caregiver", back_populates="user", cascade="all, delete-orphan")
    symptom_logs: Mapped[List["SymptomLog"]] = relationship("SymptomLog", back_populates="user", cascade="all, delete-orphan")


class Medicine(Base):
    """Medicine model for storing medicine information"""
    __tablename__ = "medicines"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    dosage: Mapped[str] = mapped_column(String(100))
    inventory_count: Mapped[float] = mapped_column(Float, default=0.0)
    low_stock_threshold: Mapped[float] = mapped_column(Float, default=5.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="medicines")
    schedules: Mapped[List["MedicineSchedule"]] = relationship("MedicineSchedule", back_populates="medicine", cascade="all, delete-orphan")
    doses: Mapped[List["DoseLog"]] = relationship("DoseLog", back_populates="medicine", cascade="all, delete-orphan")


class MedicineSchedule(Base):
    """Schedule for taking medicines"""
    __tablename__ = "medicine_schedules"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    medicine_id: Mapped[int] = mapped_column(Integer, ForeignKey("medicines.id"))
    time_to_take: Mapped[time] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_minutes_before: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    medicine: Mapped["Medicine"] = relationship("Medicine", back_populates="schedules")


class DoseLog(Base):
    """Log of taken/missed medicine doses"""
    __tablename__ = "dose_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    medicine_id: Mapped[int] = mapped_column(Integer, ForeignKey("medicines.id"))
    scheduled_time: Mapped[datetime] = mapped_column(DateTime)
    taken_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, taken, missed, skipped
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    medicine: Mapped["Medicine"] = relationship("Medicine", back_populates="doses")


class SymptomLog(Base):
    """Daily symptom and side effects log"""
    __tablename__ = "symptom_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    log_date: Mapped[datetime] = mapped_column(DateTime)
    mood_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-10 scale
    symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    side_effects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="symptom_logs")


class Caregiver(Base):
    """Caregiver/family member access for monitoring"""
    __tablename__ = "caregivers"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    caregiver_telegram_id: Mapped[int] = mapped_column(Integer)
    caregiver_name: Mapped[str] = mapped_column(String(100))
    relationship: Mapped[str] = mapped_column(String(50))  # family, doctor, nurse, etc.
    permissions: Mapped[str] = mapped_column(String(200), default="view")  # view, manage, admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="caregivers")


# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./medicine_bot.db")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("DEBUG", "False").lower() == "true",
    future=True
)

# Create async session factory
async_session = async_sessionmaker(
    engine,
    expire_on_commit=False
)


async def init_database():
    """Initialize the database and create all tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    """Get an async database session"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# Database utility functions
class DatabaseManager:
    """Helper class for database operations"""
    
    @staticmethod
    async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID"""
        async with async_session() as session:
            result = await session.get(User, {"telegram_id": telegram_id})
            return result
    
    @staticmethod
    async def create_user(telegram_id: int, username: str, first_name: str, last_name: str = None) -> User:
        """Create a new user"""
        async with async_session() as session:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    
    @staticmethod
    async def get_user_medicines(user_id: int, active_only: bool = True) -> List[Medicine]:
        """Get all medicines for a user"""
        async with async_session() as session:
            query = session.query(Medicine).filter(Medicine.user_id == user_id)
            if active_only:
                query = query.filter(Medicine.is_active == True)
            result = await session.execute(query)
            return result.scalars().all()
    
    @staticmethod
    async def update_inventory(medicine_id: int, new_count: float):
        """Update medicine inventory count"""
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if medicine:
                medicine.inventory_count = new_count
                await session.commit()
    
    @staticmethod
    async def log_dose_taken(medicine_id: int, scheduled_time: datetime, taken_at: datetime = None):
        """Log that a dose was taken"""
        if taken_at is None:
            taken_at = datetime.utcnow()
            
        async with async_session() as session:
            dose_log = DoseLog(
                medicine_id=medicine_id,
                scheduled_time=scheduled_time,
                taken_at=taken_at,
                status="taken"
            )
            session.add(dose_log)
            await session.commit()
