"""
Database models and setup for Medicine Reminder Bot
Using SQLAlchemy 2.0 with modern typing and async support
"""

import os
from datetime import datetime, time, timedelta
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Time, Text, ForeignKey, Float, select, func
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
    relationship_type: Mapped[str] = mapped_column("relationship", String(50))  # family, doctor, nurse, etc.
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
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalars().first()
    
    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[User]:
        """Get user by primary key"""
        async with async_session() as session:
            return await session.get(User, user_id)
    
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
    async def get_user_medicines(user_id: int, active_only: bool = True) -> List["Medicine"]:
        """Get all medicines for a user"""
        async with async_session() as session:
            stmt = select(Medicine).where(Medicine.user_id == user_id)
            if active_only:
                stmt = stmt.where(Medicine.is_active == True)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    
    @staticmethod
    async def get_medicine_by_id(medicine_id: int) -> Optional["Medicine"]:
        """Get medicine by primary key"""
        async with async_session() as session:
            return await session.get(Medicine, medicine_id)
    
    @staticmethod
    async def get_medicine_schedules(medicine_id: int) -> List["MedicineSchedule"]:
        """Get schedules for a medicine"""
        async with async_session() as session:
            result = await session.execute(
                select(MedicineSchedule).where(MedicineSchedule.medicine_id == medicine_id, MedicineSchedule.is_active == True)
            )
            return list(result.scalars().all())
    
    @staticmethod
    async def create_medicine(
        user_id: int,
        name: str,
        dosage: str,
        inventory_count: float = 0.0,
        low_stock_threshold: float = 5.0,
        notes: Optional[str] = None
    ) -> Medicine:
        """Create a new medicine for a user."""
        async with async_session() as session:
            medicine = Medicine(
                user_id=user_id,
                name=name,
                dosage=dosage,
                inventory_count=inventory_count,
                low_stock_threshold=low_stock_threshold,
                notes=notes,
                is_active=True
            )
            session.add(medicine)
            await session.commit()
            await session.refresh(medicine)
            return medicine

    @staticmethod
    async def create_medicine_schedule(
        medicine_id: int,
        time_to_take: time,
        reminder_minutes_before: int = 0,
        is_active: bool = True
    ) -> MedicineSchedule:
        """Create a new schedule time for a medicine."""
        async with async_session() as session:
            schedule = MedicineSchedule(
                medicine_id=medicine_id,
                time_to_take=time_to_take,
                reminder_minutes_before=reminder_minutes_before,
                is_active=is_active
            )
            session.add(schedule)
            await session.commit()
            await session.refresh(schedule)
            return schedule
    
    @staticmethod
    async def get_recent_doses(medicine_id: int, hours: int = None, days: int = None) -> List["DoseLog"]:
        """Get recent dose logs for a medicine in the last N hours or days."""
        assert hours is not None or days is not None, "Specify hours or days"
        since = None
        if hours is not None:
            since = datetime.utcnow() - timedelta(hours=hours)
        if days is not None:
            since = datetime.utcnow() - timedelta(days=days)
        async with async_session() as session:
            result = await session.execute(
                select(DoseLog)
                .where(DoseLog.medicine_id == medicine_id, DoseLog.scheduled_time >= since)
                .order_by(DoseLog.scheduled_time.desc())
            )
            return list(result.scalars().all())
    
    @staticmethod
    async def update_inventory(medicine_id: int, new_count: float):
        """Update medicine inventory count"""
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if medicine:
                medicine.inventory_count = new_count
                await session.commit()
    
    @staticmethod
    async def log_dose_taken(medicine_id: int, scheduled_time: datetime, taken_at: datetime = None) -> DoseLog:
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
            await session.refresh(dose_log)
            return dose_log
    
    @staticmethod
    async def log_dose_skipped(medicine_id: int, scheduled_time: datetime, reason: Optional[str] = None) -> DoseLog:
        """Log that a dose was skipped"""
        async with async_session() as session:
            dose_log = DoseLog(
                medicine_id=medicine_id,
                scheduled_time=scheduled_time,
                taken_at=None,
                status="skipped",
                notes=reason
            )
            session.add(dose_log)
            await session.commit()
            await session.refresh(dose_log)
            return dose_log
    
    @staticmethod
    async def log_dose_missed(medicine_id: int, scheduled_time: datetime) -> DoseLog:
        """Log that a dose was missed"""
        async with async_session() as session:
            dose_log = DoseLog(
                medicine_id=medicine_id,
                scheduled_time=scheduled_time,
                taken_at=None,
                status="missed"
            )
            session.add(dose_log)
            await session.commit()
            await session.refresh(dose_log)
            return dose_log
    
    @staticmethod
    async def get_missed_doses(user_id: int, days: int = 7) -> List["DoseLog"]:
        """Get missed doses for a user in the last N days"""
        since = datetime.utcnow() - timedelta(days=days)
        async with async_session() as session:
            result = await session.execute(
                select(DoseLog)
                .join(Medicine, DoseLog.medicine_id == Medicine.id)
                .where(
                    Medicine.user_id == user_id,
                    DoseLog.status == "missed",
                    DoseLog.scheduled_time >= since
                )
                .order_by(DoseLog.scheduled_time.desc())
            )
            return list(result.scalars().all())
    
    @staticmethod
    async def get_user_caregivers(user_id: int, active_only: bool = True) -> List["Caregiver"]:
        """Get caregivers for a user"""
        async with async_session() as session:
            stmt = select(Caregiver).where(Caregiver.user_id == user_id)
            if active_only:
                stmt = stmt.where(Caregiver.is_active == True)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    
    @staticmethod
    async def create_caregiver(
        user_id: int,
        caregiver_telegram_id: int,
        caregiver_name: str,
        relationship: str,
        permissions: str = "view"
    ) -> Caregiver:
        """Create a new caregiver (maps relationship to relationship_type)"""
        async with async_session() as session:
            caregiver = Caregiver(
                user_id=user_id,
                caregiver_telegram_id=caregiver_telegram_id,
                caregiver_name=caregiver_name,
                relationship_type=relationship,
                permissions=permissions,
                is_active=True
            )
            session.add(caregiver)
            await session.commit()
            await session.refresh(caregiver)
            return caregiver
    
    @staticmethod
    async def get_all_active_users() -> List[User]:
        """Return all active users"""
        async with async_session() as session:
            result = await session.execute(select(User).where(User.is_active == True))
            return list(result.scalars().all())
    
    @staticmethod
    async def get_all_active_caregivers() -> List[Caregiver]:
        """Return all active caregivers"""
        async with async_session() as session:
            result = await session.execute(select(Caregiver).where(Caregiver.is_active == True))
            return list(result.scalars().all())
    
    @staticmethod
    async def get_low_stock_medicines() -> List[Medicine]:
        """Return medicines with inventory below or equal to threshold"""
        async with async_session() as session:
            result = await session.execute(
                select(Medicine).where(
                    Medicine.is_active == True,
                    Medicine.inventory_count <= Medicine.low_stock_threshold
                )
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_medicine_doses_in_range(medicine_id: int, start_date, end_date) -> List["DoseLog"]:
        """Get dose logs for a medicine within a date range (inclusive)."""
        async with async_session() as session:
            result = await session.execute(
                select(DoseLog)
                .where(
                    DoseLog.medicine_id == medicine_id,
                    DoseLog.scheduled_time >= datetime.combine(start_date, datetime.min.time()),
                    DoseLog.scheduled_time <= datetime.combine(end_date, datetime.max.time())
                )
                .order_by(DoseLog.scheduled_time.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_symptom_logs_in_range(user_id: int, start_date, end_date) -> List["SymptomLog"]:
        """Get symptom logs for a user within a date range (inclusive)."""
        async with async_session() as session:
            result = await session.execute(
                select(SymptomLog)
                .where(
                    SymptomLog.user_id == user_id,
                    SymptomLog.log_date >= datetime.combine(start_date, datetime.min.time()),
                    SymptomLog.log_date <= datetime.combine(end_date, datetime.max.time())
                )
                .order_by(SymptomLog.log_date.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_doses_for_date(user_id: int, day_date) -> List["DoseLog"]:
        """Get all dose logs for a specific user on a specific date."""
        day_start = datetime.combine(day_date, datetime.min.time())
        day_end = datetime.combine(day_date, datetime.max.time())
        async with async_session() as session:
            result = await session.execute(
                select(DoseLog)
                .join(Medicine, DoseLog.medicine_id == Medicine.id)
                .where(
                    Medicine.user_id == user_id,
                    DoseLog.scheduled_time >= day_start,
                    DoseLog.scheduled_time <= day_end
                )
                .order_by(DoseLog.scheduled_time.asc())
            )
            return list(result.scalars().all())
