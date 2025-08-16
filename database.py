"""
Database models and setup for Medicine Reminder Bot
Using SQLAlchemy 2.0 with modern typing and async support
"""

import os
from datetime import datetime, time, timedelta
from datetime import date
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Time, Text, ForeignKey, Float, select, func
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from config import config


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
    pack_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # pills per package
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="medicines")
    schedules: Mapped[List["MedicineSchedule"]] = relationship(
        "MedicineSchedule", back_populates="medicine", cascade="all, delete-orphan"
    )
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
    # Optional link to a specific medicine
    medicine_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("medicines.id"), nullable=True)
    medicine: Mapped[Optional["Medicine"]] = relationship("Medicine")

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="symptom_logs")


class UserSettings(Base):
    """Per-user settings including reminder snooze, attempts, and silent mode."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)
    snooze_minutes: Mapped[int] = mapped_column(Integer, default=5)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    silent_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationship (no back_populates to avoid heavy graph)
    user: Mapped["User"] = relationship("User")


class Caregiver(Base):
    """Caregiver/family member access for monitoring"""

    __tablename__ = "caregivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    caregiver_telegram_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    caregiver_name: Mapped[str] = mapped_column(String(100))
    relationship_type: Mapped[str] = mapped_column("relationship", String(50))  # family, doctor, nurse, etc.
    permissions: Mapped[str] = mapped_column(String(200), default="view")  # view, manage, admin
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    preferred_channel: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'email' | 'phone' | 'telegram'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="caregivers")


class Appointment(Base):
    """Appointments such as doctor visits and tests"""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(30), default="custom")
    title: Mapped[str] = mapped_column(String(200))
    when_at: Mapped[datetime] = mapped_column(DateTime)
    remind_day_before: Mapped[bool] = mapped_column(Boolean, default=True)
    remind_3days_before: Mapped[bool] = mapped_column(Boolean, default=False)
    remind_same_day: Mapped[bool] = mapped_column(Boolean, default=True)
    same_day_reminder_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User")


class Invite(Base):
    """One-time caregiver invite token"""

    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    caregiver_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, used, canceled, expired
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User")


# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./medicine_bot.db")

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=os.getenv("DEBUG", "False").lower() == "true", future=True)

# Create async session factory
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_database():
    """Initialize the database and create all tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migration: add medicine_id to symptom_logs if missing (SQLite safe)
        try:
            res = await conn.exec_driver_sql("PRAGMA table_info(symptom_logs)")
            cols = [row[1] for row in res.fetchall()]
            if "medicine_id" not in cols:
                await conn.exec_driver_sql("ALTER TABLE symptom_logs ADD COLUMN medicine_id INTEGER NULL")
        except Exception:
            pass
        # Add pack_size to medicines if missing
        try:
            res2 = await conn.exec_driver_sql("PRAGMA table_info(medicines)")
            cols2 = [row[1] for row in res2.fetchall()]
            if "pack_size" not in cols2:
                await conn.exec_driver_sql("ALTER TABLE medicines ADD COLUMN pack_size INTEGER NULL")
        except Exception:
            pass
        # Add remind_same_day to appointments if missing
        try:
            res3 = await conn.exec_driver_sql("PRAGMA table_info(appointments)")
            cols3 = [row[1] for row in res3.fetchall()]
            if "remind_same_day" not in cols3:
                await conn.exec_driver_sql("ALTER TABLE appointments ADD COLUMN remind_same_day BOOLEAN DEFAULT 1")
            if "same_day_reminder_time" not in cols3:
                await conn.exec_driver_sql("ALTER TABLE appointments ADD COLUMN same_day_reminder_time TIME NULL")
        except Exception:
            pass
        # Add caregiver contact fields if missing
        try:
            res4 = await conn.exec_driver_sql("PRAGMA table_info(caregivers)")
            cols4 = [row[1] for row in res4.fetchall()]
            if "email" not in cols4:
                await conn.exec_driver_sql("ALTER TABLE caregivers ADD COLUMN email VARCHAR(200) NULL")
            if "phone" not in cols4:
                await conn.exec_driver_sql("ALTER TABLE caregivers ADD COLUMN phone VARCHAR(50) NULL")
            if "preferred_channel" not in cols4:
                await conn.exec_driver_sql("ALTER TABLE caregivers ADD COLUMN preferred_channel VARCHAR(20) NULL")
        except Exception:
            pass


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
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
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
            user = User(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
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
        notes: Optional[str] = None,
        pack_size: Optional[int] = None,
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
                pack_size=pack_size,
                is_active=True,
            )
            session.add(medicine)
            await session.commit()
            await session.refresh(medicine)
            return medicine

    @staticmethod
    async def create_medicine_schedule(
        medicine_id: int, time_to_take: time, reminder_minutes_before: int = 0, is_active: bool = True
    ) -> MedicineSchedule:
        """Create a new schedule time for a medicine."""
        async with async_session() as session:
            schedule = MedicineSchedule(
                medicine_id=medicine_id,
                time_to_take=time_to_take,
                reminder_minutes_before=reminder_minutes_before,
                is_active=is_active,
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
            dose_log = DoseLog(medicine_id=medicine_id, scheduled_time=scheduled_time, taken_at=taken_at, status="taken")
            session.add(dose_log)
            await session.commit()
            await session.refresh(dose_log)
            return dose_log

    @staticmethod
    async def log_dose_skipped(medicine_id: int, scheduled_time: datetime, reason: Optional[str] = None) -> DoseLog:
        """Log that a dose was skipped"""
        async with async_session() as session:
            dose_log = DoseLog(
                medicine_id=medicine_id, scheduled_time=scheduled_time, taken_at=None, status="skipped", notes=reason
            )
            session.add(dose_log)
            await session.commit()
            await session.refresh(dose_log)
            return dose_log

    @staticmethod
    async def log_dose_missed(medicine_id: int, scheduled_time: datetime) -> DoseLog:
        """Log that a dose was missed"""
        async with async_session() as session:
            dose_log = DoseLog(medicine_id=medicine_id, scheduled_time=scheduled_time, taken_at=None, status="missed")
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
                .where(Medicine.user_id == user_id, DoseLog.status == "missed", DoseLog.scheduled_time >= since)
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
        caregiver_telegram_id: Optional[int] = None,
        caregiver_name: str = "",
        relationship: str = "",
        permissions: str = "view",
        email: Optional[str] = None,
        phone: Optional[str] = None,
        preferred_channel: Optional[str] = None,
    ) -> Caregiver:
        """Create a new caregiver (maps relationship to relationship_type)"""
        async with async_session() as session:
            caregiver = Caregiver(
                user_id=user_id,
                caregiver_telegram_id=caregiver_telegram_id,
                caregiver_name=caregiver_name,
                relationship_type=relationship,
                permissions=permissions,
                email=email,
                phone=phone,
                preferred_channel=preferred_channel,
                is_active=True,
            )
            session.add(caregiver)
            await session.commit()
            await session.refresh(caregiver)
            return caregiver

    @staticmethod
    async def get_caregiver_by_id(caregiver_id: int) -> Optional[Caregiver]:
        """Get a caregiver by primary key."""
        async with async_session() as session:
            return await session.get(Caregiver, caregiver_id)

    @staticmethod
    async def update_caregiver(
        caregiver_id: int,
        caregiver_name: Optional[str] = None,
        relationship_type: Optional[str] = None,
        permissions: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        preferred_channel: Optional[str] = None,
    ) -> Optional[Caregiver]:
        """Update caregiver fields (name/relationship_type/permissions)."""
        async with async_session() as session:
            caregiver = await session.get(Caregiver, caregiver_id)
            if not caregiver:
                return None
            if caregiver_name is not None:
                caregiver.caregiver_name = caregiver_name
            if relationship_type is not None:
                caregiver.relationship_type = relationship_type
            if permissions is not None:
                caregiver.permissions = permissions
            if email is not None:
                caregiver.email = email
            if phone is not None:
                caregiver.phone = phone
            if preferred_channel is not None:
                caregiver.preferred_channel = preferred_channel
            await session.commit()
            await session.refresh(caregiver)
            return caregiver

    @staticmethod
    async def set_caregiver_active(caregiver_id: int, is_active: bool) -> bool:
        """Enable/disable a caregiver."""
        async with async_session() as session:
            caregiver = await session.get(Caregiver, caregiver_id)
            if not caregiver:
                return False
            caregiver.is_active = is_active
            await session.commit()
            return True

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
                select(Medicine).where(Medicine.is_active == True, Medicine.inventory_count <= Medicine.low_stock_threshold)
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
                    DoseLog.scheduled_time <= datetime.combine(end_date, datetime.max.time()),
                )
                .order_by(DoseLog.scheduled_time.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_symptom_logs_in_range(
        user_id: int, start_date, end_date, medicine_id: Optional[int] = None
    ) -> List["SymptomLog"]:
        """Get symptom logs for a user within a date range (inclusive)."""
        async with async_session() as session:
            conditions = [
                SymptomLog.user_id == user_id,
                SymptomLog.log_date >= datetime.combine(start_date, datetime.min.time()),
                SymptomLog.log_date <= datetime.combine(end_date, datetime.max.time()),
            ]
            if medicine_id is not None:
                conditions.append(SymptomLog.medicine_id == medicine_id)
            result = await session.execute(select(SymptomLog).where(*conditions).order_by(SymptomLog.log_date.asc()))
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
                .where(Medicine.user_id == user_id, DoseLog.scheduled_time >= day_start, DoseLog.scheduled_time <= day_end)
                .order_by(DoseLog.scheduled_time.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def create_symptom_log(
        user_id: int,
        log_date: datetime,
        symptoms: str = None,
        side_effects: str = None,
        mood_score: int = None,
        notes: str = None,
        medicine_id: Optional[int] = None,
    ) -> "SymptomLog":
        """Create a new symptom/side-effects log entry."""
        async with async_session() as session:
            log = SymptomLog(
                user_id=user_id,
                log_date=log_date,
                symptoms=symptoms,
                side_effects=side_effects,
                mood_score=mood_score,
                notes=notes,
                medicine_id=medicine_id,
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    @staticmethod
    async def update_medicine(
        medicine_id: int,
        name: Optional[str] = None,
        dosage: Optional[str] = None,
        notes: Optional[str] = None,
        pack_size: Optional[int] = None,
    ) -> Optional["Medicine"]:
        """Update medicine fields (name/dosage/notes/pack_size)."""
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if not medicine:
                return None
            if name is not None:
                medicine.name = name
            if dosage is not None:
                medicine.dosage = dosage
            if notes is not None:
                medicine.notes = notes
            if pack_size is not None:
                medicine.pack_size = int(pack_size)
            await session.commit()
            await session.refresh(medicine)
            return medicine

    @staticmethod
    async def set_medicine_active(medicine_id: int, is_active: bool) -> bool:
        """Enable/disable a medicine."""
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if not medicine:
                return False
            medicine.is_active = is_active
            await session.commit()
            return True

    @staticmethod
    async def update_user_timezone(user_id: int, timezone: str) -> bool:
        """Update user's timezone string."""
        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return False
            user.timezone = timezone
            await session.commit()
            return True

    @staticmethod
    async def delete_medicine_schedule(schedule_id: int) -> bool:
        """Delete a specific schedule row by ID."""
        async with async_session() as session:
            schedule = await session.get(MedicineSchedule, schedule_id)
            if not schedule:
                return False
            await session.delete(schedule)
            await session.commit()
            return True

    @staticmethod
    async def get_medicine_schedule_rows(medicine_id: int) -> List["MedicineSchedule"]:
        """Return all schedule rows (active and inactive) for a medicine."""
        async with async_session() as session:
            result = await session.execute(select(MedicineSchedule).where(MedicineSchedule.medicine_id == medicine_id))
            return list(result.scalars().all())

    @staticmethod
    async def replace_medicine_schedules(medicine_id: int, times: List[time]) -> None:
        """Replace all schedules for a medicine with provided times."""
        async with async_session() as session:
            await session.execute(select(MedicineSchedule).where(MedicineSchedule.medicine_id == medicine_id))
            # Delete existing schedules
            existing = await session.execute(select(MedicineSchedule).where(MedicineSchedule.medicine_id == medicine_id))
            for row in existing.scalars().all():
                await session.delete(row)
            # Create new schedules
            for t in times:
                new_row = MedicineSchedule(medicine_id=medicine_id, time_to_take=t, is_active=True)
                session.add(new_row)
            await session.commit()

    @staticmethod
    async def delete_medicine(medicine_id: int) -> bool:
        """Delete a medicine and all its related data."""
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if not medicine:
                return False
            await session.delete(medicine)
            await session.commit()
            return True

    @staticmethod
    async def get_user_settings(user_id: int) -> UserSettings:
        """Get or create user settings with defaults."""
        async with async_session() as session:
            result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
            settings = result.scalar_one_or_none()
            if not settings:
                settings = UserSettings(user_id=user_id)
                session.add(settings)
                await session.commit()
                await session.refresh(settings)
            return settings

    @staticmethod
    async def update_user_settings(
        user_id: int,
        snooze_minutes: Optional[int] = None,
        max_attempts: Optional[int] = None,
        silent_mode: Optional[bool] = None,
    ) -> UserSettings:
        """Update user settings fields."""
        async with async_session() as session:
            result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
            settings = result.scalar_one_or_none()
            if not settings:
                settings = UserSettings(user_id=user_id)
                session.add(settings)
            if snooze_minutes is not None:
                settings.snooze_minutes = max(1, min(120, int(snooze_minutes)))
            if max_attempts is not None:
                settings.max_attempts = max(1, min(10, int(max_attempts)))
            if silent_mode is not None:
                settings.silent_mode = bool(silent_mode)
            await session.commit()
            await session.refresh(settings)
            return settings

    @staticmethod
    async def update_symptom_log(log_id: int, symptoms: Optional[str] = None, side_effects: Optional[str] = None) -> bool:
        """Update a symptom log's text fields."""
        async with async_session() as session:
            log = await session.get(SymptomLog, log_id)
            if not log:
                return False
            if symptoms is not None:
                log.symptoms = symptoms
            if side_effects is not None:
                log.side_effects = side_effects
            await session.commit()
            return True

    @staticmethod
    async def delete_symptom_log(log_id: int) -> bool:
        """Delete a symptom log by id."""
        async with async_session() as session:
            log = await session.get(SymptomLog, log_id)
            if not log:
                return False
            await session.delete(log)
            await session.commit()
            return True

    @staticmethod
    async def create_invite(user_id: int, caregiver_name: Optional[str] = None, ttl_hours: int = 72) -> "Invite":
        """Create a one-time invite for caregiver onboarding."""
        async with async_session() as session:
            # generate simple code MED-XXXXX
            import random

            code = f"MED-{random.randint(10000, 99999)}"
            # ensure uniqueness
            while (await session.execute(select(Invite).where(Invite.code == code))).scalar_one_or_none():
                code = f"MED-{random.randint(10000, 99999)}"
            inv = Invite(
                code=code,
                user_id=int(user_id),
                caregiver_name=caregiver_name,
                status="active",
                expires_at=datetime.utcnow() + timedelta(hours=max(1, int(ttl_hours))),
            )
            session.add(inv)
            await session.commit()
            await session.refresh(inv)
            return inv

    @staticmethod
    async def get_invite_by_code(code: str) -> Optional["Invite"]:
        async with async_session() as session:
            result = await session.execute(select(Invite).where(Invite.code == code))
            return result.scalar_one_or_none()

    @staticmethod
    async def mark_invite_used(code: str) -> bool:
        async with async_session() as session:
            result = await session.execute(select(Invite).where(Invite.code == code))
            inv = result.scalar_one_or_none()
            if not inv:
                return False
            inv.status = "used"
            await session.commit()
            return True

    @staticmethod
    async def cancel_invite(code: str) -> bool:
        async with async_session() as session:
            result = await session.execute(select(Invite).where(Invite.code == code))
            inv = result.scalar_one_or_none()
            if not inv:
                return False
            inv.status = "canceled"
            await session.commit()
            return True


# ==============================
# MongoDB Backend (Motor)
# ==============================
try:
    from motor.motor_asyncio import AsyncIOMotorClient

    _mongo_available = True
except Exception:
    _mongo_available = False

_mongo_client = None
_mongo_db = None


async def _init_mongo():
    global _mongo_client, _mongo_db
    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(config.MONGODB_URI)
        _mongo_db = _mongo_client[config.MONGODB_DB]
        # Create indexes (idempotent)
        await _mongo_db.users.create_index("telegram_id", unique=True)
        await _mongo_db.medicines.create_index([("user_id", 1)])
        await _mongo_db.medicine_schedules.create_index([("medicine_id", 1)])
        await _mongo_db.dose_logs.create_index([("medicine_id", 1), ("scheduled_time", 1)])
        await _mongo_db.symptom_logs.create_index([("user_id", 1), ("log_date", 1)])
        await _mongo_db.symptom_logs.create_index([("medicine_id", 1)])
        await _mongo_db.caregivers.create_index([("user_id", 1)])
        await _mongo_db.caregivers.create_index([("email", 1)])
        await _mongo_db.caregivers.create_index([("phone", 1)])
        await _mongo_db.appointments.create_index([("user_id", 1), ("when_at", 1)])
        await _mongo_db.user_settings.create_index([("user_id", 1)], unique=True)


# Wrap SQLAlchemy models into dict converters for Mongo


def _user_doc(u: User) -> dict:
    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.username,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "is_active": u.is_active,
        "timezone": u.timezone,
        "created_at": u.created_at,
    }


# Database utility functions (overridden for Mongo when enabled)
class DatabaseManagerMongo:
    @staticmethod
    async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
        await _init_mongo()
        doc = await _mongo_db.users.find_one({"telegram_id": telegram_id})
        if not doc:
            return None
        # Minimal adapter object
        user = User()
        user.id = doc.get("_id") or doc.get("id")
        user.telegram_id = doc.get("telegram_id")
        user.username = doc.get("username")
        user.first_name = doc.get("first_name")
        user.last_name = doc.get("last_name")
        user.is_active = doc.get("is_active", True)
        user.timezone = doc.get("timezone", "UTC")
        user.created_at = doc.get("created_at") or datetime.utcnow()
        return user

    @staticmethod
    async def get_doses_for_date(user_id: int, day_date) -> List[DoseLog]:
        """Return all dose logs for the given user's medicines on a specific date (Mongo)."""
        await _init_mongo()
        # Collect medicine ids for the user
        med_rows = await _mongo_db.medicines.find({"user_id": int(user_id)}).to_list(10000)
        med_ids = [int(d.get("_id")) for d in med_rows if d.get("_id") is not None]
        if not med_ids:
            return []
        day_start = datetime.combine(day_date, datetime.min.time())
        day_end = datetime.combine(day_date, datetime.max.time())
        rows = (
            await _mongo_db.dose_logs.find(
                {"medicine_id": {"$in": med_ids}, "scheduled_time": {"$gte": day_start, "$lte": day_end}}
            )
            .sort("scheduled_time", 1)
            .to_list(10000)
        )
        result: List[DoseLog] = []
        for d in rows:
            log = DoseLog()
            log.id = d.get("_id")
            log.medicine_id = d.get("medicine_id")
            log.scheduled_time = d.get("scheduled_time")
            log.taken_at = d.get("taken_at")
            log.status = d.get("status", "pending")
            log.notes = d.get("notes")
            result.append(log)
        return result

    @staticmethod
    async def update_user_timezone(user_id: int, timezone: str) -> bool:
        await _init_mongo()
        res = await _mongo_db.users.update_one({"_id": int(user_id)}, {"$set": {"timezone": timezone}})
        return res.matched_count > 0

    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[User]:
        await _init_mongo()
        doc = await _mongo_db.users.find_one({"_id": user_id})
        if not doc:
            return None
        user = await DatabaseManagerMongo.get_user_by_telegram_id(doc.get("telegram_id", 0))
        return user

    @staticmethod
    async def create_user(telegram_id: int, username: str, first_name: str, last_name: str = None) -> User:
        await _init_mongo()
        # Generate simple numeric _id
        existing = await _mongo_db.users.find_one({"telegram_id": telegram_id})
        if existing:
            await _mongo_db.users.update_one(
                {"telegram_id": telegram_id},
                {
                    "$set": {
                        "username": username,
                        "first_name": first_name,
                        "last_name": last_name,
                        "is_active": True,
                        "timezone": "UTC",
                    }
                },
            )
            doc = await _mongo_db.users.find_one({"telegram_id": telegram_id})
            user = await DatabaseManagerMongo.get_user_by_telegram_id(telegram_id)
            return user
        else:
            # Compute next _id
            last = await _mongo_db.users.find().sort("_id", -1).limit(1).to_list(1)
            next_id = (last[0]["_id"] + 1) if last else 1
            doc = {
                "_id": next_id,
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "is_active": True,
                "timezone": "UTC",
                "created_at": datetime.utcnow(),
            }
            await _mongo_db.users.insert_one(doc)
            return await DatabaseManagerMongo.get_user_by_telegram_id(telegram_id)

    @staticmethod
    async def get_user_medicines(user_id: int, active_only: bool = True) -> List[Medicine]:
        await _init_mongo()
        q = {"user_id": user_id}
        if active_only:
            q["is_active"] = True

        rows = await _mongo_db.medicines.find(q).to_list(1000)
        result = []
        for d in rows:
            m = Medicine()
            m.id = d.get("_id")
            m.user_id = d.get("user_id")
            m.name = d.get("name")
            m.dosage = d.get("dosage")
            m.inventory_count = float(d.get("inventory_count", 0))
            m.low_stock_threshold = float(d.get("low_stock_threshold", 5))
            m.pack_size = int(d.get("pack_size")) if d.get("pack_size") is not None else None
            m.is_active = bool(d.get("is_active", True))
            m.notes = d.get("notes")
            m.created_at = d.get("created_at") or datetime.utcnow()
            result.append(m)
        return result

    @staticmethod
    async def get_medicine_by_id(medicine_id: int) -> Optional[Medicine]:
        await _init_mongo()
        d = await _mongo_db.medicines.find_one({"_id": int(medicine_id)})
        if not d:
            return None
        m = Medicine()
        m.id = d.get("_id")
        m.user_id = d.get("user_id")
        m.name = d.get("name")
        m.dosage = d.get("dosage")
        m.inventory_count = float(d.get("inventory_count", 0))
        m.low_stock_threshold = float(d.get("low_stock_threshold", 5))
        m.pack_size = int(d.get("pack_size")) if d.get("pack_size") is not None else None
        m.is_active = bool(d.get("is_active", True))
        m.notes = d.get("notes")
        m.created_at = d.get("created_at") or datetime.utcnow()
        return m

    @staticmethod
    async def get_medicine_schedules(medicine_id: int) -> List[MedicineSchedule]:
        await _init_mongo()
        rows = await _mongo_db.medicine_schedules.find({"medicine_id": int(medicine_id), "is_active": True}).to_list(100)
        result = []
        for d in rows:
            s = MedicineSchedule()
            s.id = d.get("_id")
            s.medicine_id = d.get("medicine_id")
            # store as HH:MM
            st = d.get("time_to_take")
            if isinstance(st, str):
                hh, mm = map(int, st.split(":"))
                st = time(hour=hh, minute=mm)
            s.time_to_take = st
            s.is_active = d.get("is_active", True)
            result.append(s)
        return result

    @staticmethod
    async def create_medicine(
        user_id: int,
        name: str,
        dosage: str,
        inventory_count: float = 0.0,
        low_stock_threshold: float = 5.0,
        notes: Optional[str] = None,
    ) -> Medicine:
        await _init_mongo()
        last = await _mongo_db.medicines.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "user_id": user_id,
            "name": name,
            "dosage": dosage,
            "inventory_count": float(inventory_count),
            "low_stock_threshold": float(low_stock_threshold),
            "is_active": True,
            "notes": notes,
            "created_at": datetime.utcnow(),
        }
        await _mongo_db.medicines.insert_one(doc)
        m = await DatabaseManagerMongo.get_medicine_by_id(next_id)
        return m

    @staticmethod
    async def create_medicine_schedule(
        medicine_id: int, time_to_take: time, reminder_minutes_before: int = 0, is_active: bool = True
    ) -> MedicineSchedule:
        await _init_mongo()
        last = await _mongo_db.medicine_schedules.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "medicine_id": int(medicine_id),
            "time_to_take": time_to_take.strftime("%H:%M"),
            "is_active": bool(is_active),
            "reminder_minutes_before": int(reminder_minutes_before),
            "created_at": datetime.utcnow(),
        }
        await _mongo_db.medicine_schedules.insert_one(doc)
        s = MedicineSchedule()
        s.id = next_id
        s.medicine_id = medicine_id
        s.time_to_take = time_to_take
        s.is_active = is_active
        return s

    @staticmethod
    async def replace_medicine_schedules(medicine_id: int, times: List[time]) -> None:
        """Replace all schedules for a medicine with provided times (Mongo)."""
        await _init_mongo()
        # Remove existing schedules for this medicine
        await _mongo_db.medicine_schedules.delete_many({"medicine_id": int(medicine_id)})
        # If no times provided, we are done (effectively clearing the schedule)
        if not times:
            return
        # Generate sequential ids and insert new schedules
        last = await _mongo_db.medicine_schedules.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        docs = []
        for t in times:
            docs.append(
                {
                    "_id": next_id,
                    "medicine_id": int(medicine_id),
                    "time_to_take": t.strftime("%H:%M"),
                    "is_active": True,
                    "reminder_minutes_before": 0,
                    "created_at": datetime.utcnow(),
                }
            )
            next_id += 1
        await _mongo_db.medicine_schedules.insert_many(docs)
        return

    @staticmethod
    async def get_recent_doses(medicine_id: int, hours: int = None, days: int = None) -> List[DoseLog]:
        await _init_mongo()
        assert hours is not None or days is not None
        since = None
        if hours is not None:
            since = datetime.utcnow() - timedelta(hours=hours)
        if days is not None:
            since = datetime.utcnow() - timedelta(days=days)
        rows = (
            await _mongo_db.dose_logs.find({"medicine_id": int(medicine_id), "scheduled_time": {"$gte": since}})
            .sort("scheduled_time", -1)
            .to_list(100)
        )
        result = []
        for d in rows:
            log = DoseLog()
            log.id = d.get("_id")
            log.medicine_id = d.get("medicine_id")
            log.scheduled_time = d.get("scheduled_time")
            log.taken_at = d.get("taken_at")
            log.status = d.get("status", "pending")
            log.notes = d.get("notes")
            log.created_at = d.get("created_at")
            result.append(log)
        return result

    @staticmethod
    async def update_inventory(medicine_id: int, new_count: float):
        await _init_mongo()
        await _mongo_db.medicines.update_one({"_id": int(medicine_id)}, {"$set": {"inventory_count": float(new_count)}})

    @staticmethod
    async def set_medicine_active(medicine_id: int, is_active: bool) -> bool:
        await _init_mongo()
        res = await _mongo_db.medicines.update_one({"_id": int(medicine_id)}, {"$set": {"is_active": bool(is_active)}})
        return res.modified_count >= 0

    @staticmethod
    async def update_medicine(
        medicine_id: int,
        name: Optional[str] = None,
        dosage: Optional[str] = None,
        notes: Optional[str] = None,
        pack_size: Optional[int] = None,
    ) -> Optional["Medicine"]:
        """Mongo: update medicine fields."""
        await _init_mongo()
        updates = {}
        if name is not None:
            updates["name"] = name
        if dosage is not None:
            updates["dosage"] = dosage
        if notes is not None:
            updates["notes"] = notes
        if pack_size is not None:
            updates["pack_size"] = int(pack_size)
        if not updates:
            return await DatabaseManagerMongo.get_medicine_by_id(medicine_id)
        res = await _mongo_db.medicines.update_one({"_id": int(medicine_id)}, {"$set": updates})
        if res.matched_count == 0:
            return None
        return await DatabaseManagerMongo.get_medicine_by_id(medicine_id)

    @staticmethod
    async def log_dose_taken(medicine_id: int, scheduled_time: datetime, taken_at: datetime = None) -> DoseLog:
        await _init_mongo()
        if taken_at is None:
            taken_at = datetime.utcnow()
        last = await _mongo_db.dose_logs.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "medicine_id": int(medicine_id),
            "scheduled_time": scheduled_time,
            "taken_at": taken_at,
            "status": "taken",
            "created_at": datetime.utcnow(),
        }
        await _mongo_db.dose_logs.insert_one(doc)
        log = DoseLog()
        log.id = next_id
        log.medicine_id = medicine_id
        log.scheduled_time = scheduled_time
        log.taken_at = taken_at
        log.status = "taken"
        log.created_at = doc["created_at"]
        return log

    @staticmethod
    async def log_dose_skipped(medicine_id: int, scheduled_time: datetime, reason: Optional[str] = None) -> DoseLog:
        await _init_mongo()
        last = await _mongo_db.dose_logs.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "medicine_id": int(medicine_id),
            "scheduled_time": scheduled_time,
            "taken_at": None,
            "status": "skipped",
            "notes": reason,
            "created_at": datetime.utcnow(),
        }
        await _mongo_db.dose_logs.insert_one(doc)
        log = DoseLog()
        log.id = next_id
        log.medicine_id = medicine_id
        log.scheduled_time = scheduled_time
        log.status = "skipped"
        log.notes = reason
        log.created_at = doc["created_at"]
        return log

    @staticmethod
    async def log_dose_missed(medicine_id: int, scheduled_time: datetime) -> DoseLog:
        await _init_mongo()
        last = await _mongo_db.dose_logs.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "medicine_id": int(medicine_id),
            "scheduled_time": scheduled_time,
            "taken_at": None,
            "status": "missed",
            "created_at": datetime.utcnow(),
        }
        await _mongo_db.dose_logs.insert_one(doc)
        log = DoseLog()
        log.id = next_id
        log.medicine_id = medicine_id
        log.scheduled_time = scheduled_time
        log.status = "missed"
        log.created_at = doc["created_at"]
        return log

    @staticmethod
    async def get_missed_doses(user_id: int, days: int = 7) -> List[DoseLog]:
        await _init_mongo()
        since = datetime.utcnow() - timedelta(days=days)
        # Find medicines of user
        med_ids = [m["_id"] async for m in _mongo_db.medicines.find({"user_id": user_id}, {"_id": 1})]
        rows = (
            await _mongo_db.dose_logs.find(
                {"medicine_id": {"$in": med_ids}, "status": "missed", "scheduled_time": {"$gte": since}}
            )
            .sort("scheduled_time", -1)
            .to_list(200)
        )
        result = []
        for d in rows:
            log = DoseLog()
            log.id = d.get("_id")
            log.medicine_id = d.get("medicine_id")
            log.scheduled_time = d.get("scheduled_time")
            log.status = d.get("status")
            result.append(log)
        return result

    @staticmethod
    async def get_user_caregivers(user_id: int, active_only: bool = True) -> List[Caregiver]:
        await _init_mongo()
        q = {"user_id": user_id}
        if active_only:
            q["is_active"] = True
        rows = await _mongo_db.caregivers.find(q).to_list(100)
        result = []
        for d in rows:
            cg = Caregiver()
            cg.id = d.get("_id")
            cg.user_id = d.get("user_id")
            cg.caregiver_telegram_id = d.get("caregiver_telegram_id")
            cg.caregiver_name = d.get("caregiver_name")
            cg.relationship_type = d.get("relationship_type")
            cg.permissions = d.get("permissions")
            cg.is_active = d.get("is_active", True)
            result.append(cg)
        return result

    @staticmethod
    async def create_caregiver(
        user_id: int,
        caregiver_telegram_id: Optional[int] = None,
        caregiver_name: str = "",
        relationship: str = "",
        permissions: str = "view",
        email: Optional[str] = None,
        phone: Optional[str] = None,
        preferred_channel: Optional[str] = None,
    ) -> Caregiver:
        await _init_mongo()
        last = await _mongo_db.caregivers.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "user_id": user_id,
            "caregiver_telegram_id": caregiver_telegram_id,
            "caregiver_name": caregiver_name,
            "relationship": relationship,
            "permissions": permissions,
            "is_active": True,
            "created_at": datetime.utcnow(),
        }
        if email is not None:
            doc["email"] = email
        if phone is not None:
            doc["phone"] = phone
        if preferred_channel is not None:
            doc["preferred_channel"] = preferred_channel
        await _mongo_db.caregivers.insert_one(doc)
        # Minimal return object
        cg = Caregiver()
        cg.id = next_id
        cg.user_id = user_id
        cg.caregiver_telegram_id = caregiver_telegram_id
        cg.caregiver_name = caregiver_name
        cg.relationship_type = relationship
        cg.permissions = permissions
        cg.email = email
        cg.phone = phone
        cg.preferred_channel = preferred_channel
        cg.is_active = True
        cg.created_at = datetime.utcnow()
        return cg

    @staticmethod
    async def update_caregiver(
        caregiver_id: int,
        caregiver_name: Optional[str] = None,
        relationship_type: Optional[str] = None,
        permissions: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        preferred_channel: Optional[str] = None,
    ) -> Optional[Caregiver]:
        await _init_mongo()
        updates = {}
        if caregiver_name is not None:
            updates["caregiver_name"] = caregiver_name
        if relationship_type is not None:
            updates["relationship"] = relationship_type
        if permissions is not None:
            updates["permissions"] = permissions
        if email is not None:
            updates["email"] = email
        if phone is not None:
            updates["phone"] = phone
        if preferred_channel is not None:
            updates["preferred_channel"] = preferred_channel
        if not updates:
            return await DatabaseManagerMongo.get_caregiver_by_id(caregiver_id)
        res = await _mongo_db.caregivers.update_one({"_id": int(caregiver_id)}, {"$set": updates})
        if res.modified_count == 0:
            return None
        return await DatabaseManagerMongo.get_caregiver_by_id(caregiver_id)

    @staticmethod
    async def set_caregiver_active(caregiver_id: int, is_active: bool) -> bool:
        await _init_mongo()
        res = await _mongo_db.caregivers.update_one({"_id": int(caregiver_id)}, {"$set": {"is_active": bool(is_active)}})
        return res.modified_count >= 0

    @staticmethod
    async def get_all_active_users() -> List[User]:
        await _init_mongo()
        rows = await _mongo_db.users.find({"is_active": True}).to_list(10000)
        result = []
        for d in rows:
            u = User()
            u.id = d.get("_id")
            u.telegram_id = d.get("telegram_id")
            u.username = d.get("username")
            u.first_name = d.get("first_name")
            u.last_name = d.get("last_name")
            u.is_active = d.get("is_active", True)
            u.timezone = d.get("timezone", "UTC")
            result.append(u)
        return result

    @staticmethod
    async def get_all_active_caregivers() -> List[Caregiver]:
        await _init_mongo()
        rows = await _mongo_db.caregivers.find({"is_active": True}).to_list(10000)
        result = []
        for d in rows:
            cg = Caregiver()
            cg.id = d.get("_id")
            cg.user_id = d.get("user_id")
            cg.caregiver_telegram_id = d.get("caregiver_telegram_id")
            cg.caregiver_name = d.get("caregiver_name")
            cg.relationship_type = d.get("relationship_type")
            cg.permissions = d.get("permissions")
            cg.is_active = d.get("is_active", True)
            result.append(cg)
        return result

    @staticmethod
    async def get_low_stock_medicines() -> List[Medicine]:
        await _init_mongo()
        rows = await _mongo_db.medicines.find(
            {"is_active": True, "inventory_count": {"$lte": {"$sum": "$low_stock_threshold"}}}
        ).to_list(1000)
        result = []
        for d in rows:
            m = Medicine()
            m.id = d.get("_id")
            m.user_id = d.get("user_id")
            m.name = d.get("name")
            m.dosage = d.get("dosage")
            m.inventory_count = float(d.get("inventory_count", 0))
            m.low_stock_threshold = float(d.get("low_stock_threshold", 5))
            m.pack_size = int(d.get("pack_size")) if d.get("pack_size") is not None else None
            m.is_active = bool(d.get("is_active", True))
            m.notes = d.get("notes")
            m.created_at = d.get("created_at") or datetime.utcnow()
            result.append(m)
        return result

    @staticmethod
    async def get_medicine_doses_in_range(medicine_id: int, start_date, end_date) -> List[DoseLog]:
        await _init_mongo()
        rows = (
            await _mongo_db.dose_logs.find(
                {
                    "medicine_id": int(medicine_id),
                    "scheduled_time": {
                        "$gte": datetime.combine(start_date, datetime.min.time()),
                        "$lte": datetime.combine(end_date, datetime.max.time()),
                    },
                }
            )
            .sort("scheduled_time", 1)
            .to_list(1000)
        )
        result = []
        for d in rows:
            log = DoseLog()
            log.id = d.get("_id")
            log.medicine_id = d.get("medicine_id")
            log.scheduled_time = d.get("scheduled_time")
            result.append(log)
        return result

    @staticmethod
    async def get_symptom_logs_in_range(
        user_id: int, start_date, end_date, medicine_id: Optional[int] = None
    ) -> List["SymptomLog"]:
        await _init_mongo()
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        query = {"user_id": int(user_id), "log_date": {"$gte": start_dt, "$lte": end_dt}}
        if medicine_id is not None:
            query["medicine_id"] = int(medicine_id)
        rows = await _mongo_db.symptom_logs.find(query).sort("log_date", 1).to_list(10000)
        result = []

        class _Sym:
            pass

        for d in rows:
            obj = _Sym()
            obj.id = d.get("_id")
            obj.user_id = d.get("user_id")
            obj.log_date = d.get("log_date")
            obj.symptoms = d.get("symptoms")
            obj.side_effects = d.get("side_effects")
            obj.mood_score = d.get("mood_score")
            obj.notes = d.get("notes")
            obj.medicine_id = d.get("medicine_id")
            result.append(obj)
        return result

    @staticmethod
    async def create_symptom_log(
        user_id: int,
        log_date: datetime,
        symptoms: str = None,
        side_effects: str = None,
        mood_score: int = None,
        notes: str = None,
        medicine_id: Optional[int] = None,
    ) -> "SymptomLog":
        await _init_mongo()
        last = await _mongo_db.symptom_logs.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "user_id": int(user_id),
            "log_date": log_date,
            "symptoms": symptoms,
            "side_effects": side_effects,
            "mood_score": mood_score,
            "notes": notes,
        }
        if medicine_id is not None:
            doc["medicine_id"] = int(medicine_id)
        await _mongo_db.symptom_logs.insert_one(doc)

        class _S:
            pass

        s = _S()
        s.id = next_id
        s.user_id = user_id
        s.log_date = log_date
        s.symptoms = symptoms
        s.side_effects = side_effects
        s.mood_score = mood_score
        s.notes = notes
        s.medicine_id = medicine_id
        return s  # type: ignore

    @staticmethod
    async def create_appointment(
        user_id: int,
        category: str,
        title: str,
        when_at: datetime,
        remind_day_before: bool = True,
        remind_3days_before: bool = False,
        remind_same_day: bool = True,
        same_day_reminder_time: Optional[time] = None,
        notes: Optional[str] = None,
    ):
        await _init_mongo()
        last = await _mongo_db.appointments.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "user_id": user_id,
            "category": category,
            "title": title,
            "when_at": when_at,
            "remind_day_before": bool(remind_day_before),
            "remind_3days_before": bool(remind_3days_before),
            "remind_same_day": bool(remind_same_day),
            "notes": notes,
            "created_at": datetime.utcnow(),
        }
        # optional same-day reminder time stored as HH:MM string in Mongo
        if isinstance(remind_same_day, bool) and remind_same_day and hasattr(config, "APPOINTMENT_SAME_DAY_REMINDER_HOUR"):
            default_hh = int(getattr(config, "APPOINTMENT_SAME_DAY_REMINDER_HOUR", 8))
            doc["same_day_reminder_time"] = f"{default_hh:02d}:00"
        await _mongo_db.appointments.insert_one(doc)
        # Return lightweight object
        appt = Appointment()
        appt.id = next_id
        appt.user_id = user_id
        appt.category = category
        appt.title = title
        appt.when_at = when_at
        appt.remind_day_before = bool(remind_day_before)
        appt.remind_3days_before = bool(remind_3days_before)
        appt.remind_same_day = bool(remind_same_day)
        # parse same_day_reminder_time
        val = doc.get("same_day_reminder_time")
        if isinstance(val, str) and ":" in val:
            hh, mm = map(int, val.split(":"))
            appt.same_day_reminder_time = time(hour=hh, minute=mm)
        return appt

    @staticmethod
    async def get_appointment_by_id(appointment_id: int) -> Optional["Appointment"]:
        await _init_mongo()
        d = await _mongo_db.appointments.find_one({"_id": int(appointment_id)})
        if not d:
            return None
        appt = Appointment()
        appt.id = d.get("_id")
        appt.user_id = d.get("user_id")
        appt.category = d.get("category", "custom")
        appt.title = d.get("title")
        appt.when_at = d.get("when_at")
        appt.remind_day_before = bool(d.get("remind_day_before", True))
        appt.remind_3days_before = bool(d.get("remind_3days_before", False))
        appt.remind_same_day = bool(d.get("remind_same_day", True))
        # parse time
        val = d.get("same_day_reminder_time")
        if isinstance(val, str) and ":" in val:
            hh, mm = map(int, val.split(":"))
            appt.same_day_reminder_time = time(hour=hh, minute=mm)
        appt.notes = d.get("notes")
        return appt

    @staticmethod
    async def update_appointment(
        appointment_id: int,
        when_at: datetime = None,
        title: str = None,
        category: str = None,
        remind_day_before: bool = None,
        remind_3days_before: bool = None,
        remind_same_day: bool = None,
        same_day_reminder_time: str = None,
        notes: str = None,
    ):
        await _init_mongo()
        updates = {}
        if when_at is not None:
            updates["when_at"] = when_at
        if title is not None:
            updates["title"] = title
        if category is not None:
            updates["category"] = category
        if remind_day_before is not None:
            updates["remind_day_before"] = bool(remind_day_before)
        if remind_3days_before is not None:
            updates["remind_3days_before"] = bool(remind_3days_before)
        if remind_same_day is not None:
            updates["remind_same_day"] = bool(remind_same_day)
        if same_day_reminder_time is not None:
            updates["same_day_reminder_time"] = same_day_reminder_time
        if notes is not None:
            updates["notes"] = notes
        if not updates:
            return await DatabaseManagerMongo.get_appointment_by_id(appointment_id)
        await _mongo_db.appointments.update_one({"_id": int(appointment_id)}, {"$set": updates})
        return await DatabaseManagerMongo.get_appointment_by_id(appointment_id)

    @staticmethod
    async def get_upcoming_appointments(user_id: int, until_days: int = 60):
        await _init_mongo()
        now = datetime.utcnow()
        until = now + timedelta(days=until_days)
        rows = (
            await _mongo_db.appointments.find({"user_id": user_id, "when_at": {"$gte": now, "$lte": until}})
            .sort("when_at", 1)
            .to_list(1000)
        )
        result = []
        for d in rows:
            appt = Appointment()
            appt.id = d.get("_id")
            appt.user_id = d.get("user_id")
            appt.category = d.get("category", "custom")
            appt.title = d.get("title")
            appt.when_at = d.get("when_at")
            appt.remind_day_before = bool(d.get("remind_day_before", True))
            appt.remind_3days_before = bool(d.get("remind_3days_before", False))
            appt.remind_same_day = bool(d.get("remind_same_day", True))
            val = d.get("same_day_reminder_time")
            if isinstance(val, str) and ":" in val:
                hh, mm = map(int, val.split(":"))
                appt.same_day_reminder_time = time(hour=hh, minute=mm)
            result.append(appt)
        return result

    @staticmethod
    async def get_all_upcoming_appointments(until_days: int = 60) -> List["Appointment"]:
        await _init_mongo()
        now = datetime.utcnow()
        until = now + timedelta(days=until_days)
        rows = await _mongo_db.appointments.find({"when_at": {"$gte": now, "$lte": until}}).sort("when_at", 1).to_list(1000)
        result = []
        for d in rows:
            appt = Appointment()
            appt.id = d.get("_id")
            appt.user_id = d.get("user_id")
            appt.category = d.get("category", "custom")
            appt.title = d.get("title")
            appt.when_at = d.get("when_at")
            appt.remind_day_before = bool(d.get("remind_day_before", False))
            appt.remind_3days_before = bool(d.get("remind_3days_before", False))
            val = d.get("same_day_reminder_time")
            if isinstance(val, str) and ":" in val:
                hh, mm = map(int, val.split(":"))
                appt.same_day_reminder_time = time(hour=hh, minute=mm)
            result.append(appt)
        return result

    @staticmethod
    async def get_user_appointments(
        user_id: int, start_date: date = None, end_date: date = None, offset: int = 0, limit: int = 10
    ) -> List[Appointment]:
        await _init_mongo()
        query = {"user_id": int(user_id)}
        if start_date is not None or end_date is not None:
            rng = {}
            if start_date is not None:
                rng["$gte"] = datetime.combine(start_date, datetime.min.time())
            if end_date is not None:
                rng["$lte"] = datetime.combine(end_date, datetime.max.time())
            query["when_at"] = rng
        cursor = _mongo_db.appointments.find(query).sort("when_at", 1).skip(int(max(0, offset))).limit(int(max(1, limit)))
        rows = await cursor.to_list(limit)
        result = []
        for d in rows:
            appt = Appointment()
            appt.id = d.get("_id")
            appt.user_id = d.get("user_id")
            appt.category = d.get("category", "custom")
            appt.title = d.get("title")
            appt.when_at = d.get("when_at")
            appt.remind_day_before = bool(d.get("remind_day_before", True))
            appt.remind_3days_before = bool(d.get("remind_3days_before", False))
            appt.remind_same_day = bool(d.get("remind_same_day", True))
            val = d.get("same_day_reminder_time")
            if isinstance(val, str) and ":" in val:
                hh, mm = map(int, val.split(":"))
                appt.same_day_reminder_time = time(hour=hh, minute=mm)
            result.append(appt)
        return result

    @staticmethod
    async def delete_appointment(appointment_id: int) -> bool:
        await _init_mongo()
        res = await _mongo_db.appointments.delete_one({"_id": int(appointment_id)})
        return res.deleted_count > 0

    @staticmethod
    async def get_user_settings(user_id: int) -> UserSettings:
        """Get or create user settings with defaults (Mongo)."""
        await _init_mongo()
        doc = await _mongo_db.user_settings.find_one({"user_id": int(user_id)})
        if not doc:
            default = {"user_id": int(user_id), "snooze_minutes": 10, "max_attempts": 3, "silent_mode": False}
            await _mongo_db.user_settings.insert_one(default)
            doc = default
        # Minimal return object compatible with SQLAlchemy model fields
        us = UserSettings()
        us.user_id = int(user_id)
        us.snooze_minutes = int(doc.get("snooze_minutes", 10))
        us.max_attempts = int(doc.get("max_attempts", 3))
        us.silent_mode = bool(doc.get("silent_mode", False))
        return us

    @staticmethod
    async def update_user_settings(
        user_id: int,
        snooze_minutes: Optional[int] = None,
        max_attempts: Optional[int] = None,
        silent_mode: Optional[bool] = None,
    ) -> UserSettings:
        """Update user settings fields (Mongo)."""
        await _init_mongo()
        updates = {}
        if snooze_minutes is not None:
            updates["snooze_minutes"] = max(1, min(120, int(snooze_minutes)))
        if max_attempts is not None:
            updates["max_attempts"] = max(1, min(10, int(max_attempts)))
        if silent_mode is not None:
            updates["silent_mode"] = bool(silent_mode)
        if updates:
            await _mongo_db.user_settings.update_one({"user_id": int(user_id)}, {"$set": updates}, upsert=True)
        return await DatabaseManagerMongo.get_user_settings(user_id)

    @staticmethod
    async def update_symptom_log(log_id: int, symptoms: Optional[str] = None, side_effects: Optional[str] = None) -> bool:
        """Update a symptom log's text fields."""
        async with async_session() as session:
            log = await session.get(SymptomLog, log_id)
            if not log:
                return False
            if symptoms is not None:
                log.symptoms = symptoms
            if side_effects is not None:
                log.side_effects = side_effects
            await session.commit()
            return True

    @staticmethod
    async def delete_symptom_log(log_id: int) -> bool:
        """Delete a symptom log by id."""
        async with async_session() as session:
            log = await session.get(SymptomLog, log_id)
            if not log:
                return False
            await session.delete(log)
            await session.commit()
            return True

    @staticmethod
    async def get_caregiver_by_id(caregiver_id: int) -> Optional[Caregiver]:
        await _init_mongo()
        d = await _mongo_db.caregivers.find_one({"_id": int(caregiver_id)})
        if not d:
            return None
        cg = Caregiver()
        cg.id = d.get("_id")
        cg.user_id = d.get("user_id")
        cg.caregiver_telegram_id = d.get("caregiver_telegram_id")
        cg.caregiver_name = d.get("caregiver_name")
        # map field 'relationship' in Mongo to relationship_type in model
        cg.relationship_type = d.get("relationship") or d.get("relationship_type")
        cg.permissions = d.get("permissions")
        cg.email = d.get("email")
        cg.phone = d.get("phone")
        cg.preferred_channel = d.get("preferred_channel")
        cg.is_active = d.get("is_active", True)
        cg.created_at = d.get("created_at") or datetime.utcnow()
        return cg

    @staticmethod
    async def create_invite(user_id: int, caregiver_name: Optional[str] = None, ttl_hours: int = 72) -> "Invite":
        await _init_mongo()
        import random

        code = f"MED-{random.randint(10000, 99999)}"
        # ensure uniqueness
        while await _mongo_db.invites.find_one({"code": code}):
            code = f"MED-{random.randint(10000, 99999)}"
        expires_at = datetime.utcnow() + timedelta(hours=max(1, int(ttl_hours)))
        last = await _mongo_db.invites.find().sort("_id", -1).limit(1).to_list(1)
        next_id = (last[0]["_id"] + 1) if last else 1
        doc = {
            "_id": next_id,
            "code": code,
            "user_id": int(user_id),
            "caregiver_name": caregiver_name,
            "status": "active",
            "expires_at": expires_at,
            "created_at": datetime.utcnow(),
        }
        await _mongo_db.invites.insert_one(doc)

        # Return lightweight object-like
        class _Inv:
            pass

        inv = _Inv()
        inv.id = next_id
        inv.code = code
        inv.user_id = user_id
        inv.caregiver_name = caregiver_name
        inv.status = "active"
        inv.expires_at = expires_at
        inv.created_at = doc["created_at"]
        return inv

    @staticmethod
    async def get_invite_by_code(code: str) -> Optional["Invite"]:
        await _init_mongo()
        d = await _mongo_db.invites.find_one({"code": code})
        if not d:
            return None

        class _Inv:
            pass

        inv = _Inv()
        inv.id = d.get("_id")
        inv.code = d.get("code")
        inv.user_id = d.get("user_id")
        inv.caregiver_name = d.get("caregiver_name")
        inv.status = d.get("status")
        inv.expires_at = d.get("expires_at")
        inv.created_at = d.get("created_at")
        return inv

    @staticmethod
    async def mark_invite_used(code: str) -> bool:
        await _init_mongo()
        res = await _mongo_db.invites.update_one({"code": code}, {"$set": {"status": "used"}})
        return res.matched_count > 0

    @staticmethod
    async def cancel_invite(code: str) -> bool:
        await _init_mongo()
        res = await _mongo_db.invites.update_one({"code": code}, {"$set": {"status": "canceled"}})
        return res.matched_count > 0


# Select backend at runtime
if config.DB_BACKEND == "mongo":
    if not _mongo_available:
        raise RuntimeError("motor is required for MongoDB backend")
    # Expose mongo versions of DatabaseManager functions
    DatabaseManager = DatabaseManagerMongo  # type: ignore
else:
    # Keep SQLAlchemy-based DatabaseManager
    pass
