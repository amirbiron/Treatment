"""
Database models and setup for Medicine Reminder Bot
Using SQLAlchemy 2.0 with modern typing and async support
"""

import os
from datetime import datetime, time, timedelta, date
from typing import List, Optional

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    Time,
    Text,
    ForeignKey,
    Float,
    select,
    func,
    and_,
    or_,
)
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
    pack_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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

    medicine: Mapped["Medicine"] = relationship("Medicine", back_populates="doses")


class SymptomLog(Base):
    """Daily symptom and side effects log"""

    __tablename__ = "symptom_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    log_date: Mapped[datetime] = mapped_column(DateTime)
    mood_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    side_effects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    medicine_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("medicines.id"), nullable=True)
    medicine: Mapped[Optional["Medicine"]] = relationship("Medicine")

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

    user: Mapped["User"] = relationship("User")


class Caregiver(Base):
    """Caregiver/family member access for monitoring"""

    __tablename__ = "caregivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    caregiver_telegram_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    caregiver_name: Mapped[str] = mapped_column(String(100))
    relationship_type: Mapped[str] = mapped_column("relationship", String(50))
    permissions: Mapped[str] = mapped_column(String(200), default="view")
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    preferred_channel: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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

    user: Mapped["User"] = relationship("User")


class Invite(Base):
    """One-time caregiver invite token"""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    caregiver_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User")


# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./medicine_bot.db")

engine = create_async_engine(DATABASE_URL, echo=os.getenv("DEBUG", "False").lower() == "true", future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_database():
    """Initialize the database and create all tables with minimal migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations for SQLite
        try:
            res = await conn.exec_driver_sql("PRAGMA table_info(symptom_logs)")
            cols = [row[1] for row in res.fetchall()]
            if "medicine_id" not in cols:
                await conn.exec_driver_sql("ALTER TABLE symptom_logs ADD COLUMN medicine_id INTEGER NULL")
        except Exception:
            pass
        try:
            res2 = await conn.exec_driver_sql("PRAGMA table_info(medicines)")
            cols2 = [row[1] for row in res2.fetchall()]
            if "pack_size" not in cols2:
                await conn.exec_driver_sql("ALTER TABLE medicines ADD COLUMN pack_size INTEGER NULL")
        except Exception:
            pass
        try:
            res3 = await conn.exec_driver_sql("PRAGMA table_info(appointments)")
            cols3 = [row[1] for row in res3.fetchall()]
            if "remind_same_day" not in cols3:
                await conn.exec_driver_sql("ALTER TABLE appointments ADD COLUMN remind_same_day BOOLEAN DEFAULT 1")
            if "same_day_reminder_time" not in cols3:
                await conn.exec_driver_sql("ALTER TABLE appointments ADD COLUMN same_day_reminder_time TIME NULL")
        except Exception:
            pass
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


class DatabaseManager:
    """Helper class for database operations (SQLAlchemy backend)."""

    @staticmethod
    async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            return result.scalars().first()

    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[User]:
        async with async_session() as session:
            return await session.get(User, user_id)

    @staticmethod
    async def create_user(telegram_id: int, username: str, first_name: str, last_name: str = None) -> User:
        async with async_session() as session:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    @staticmethod
    async def get_user_medicines(user_id: int, active_only: bool = True) -> List[Medicine]:
        async with async_session() as session:
            stmt = select(Medicine).where(Medicine.user_id == user_id)
            if active_only:
                stmt = stmt.where(Medicine.is_active == True)
            result = await session.execute(stmt.order_by(Medicine.created_at.asc()))
            return list(result.scalars().all())

    @staticmethod
    async def get_medicine_by_id(medicine_id: int) -> Optional[Medicine]:
        async with async_session() as session:
            return await session.get(Medicine, medicine_id)

    @staticmethod
    async def get_medicine_schedules(medicine_id: int) -> List[MedicineSchedule]:
        async with async_session() as session:
            result = await session.execute(
                select(MedicineSchedule).where(
                    MedicineSchedule.medicine_id == medicine_id, MedicineSchedule.is_active == True
                )
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
    async def get_recent_doses(medicine_id: int, hours: int = None, days: int = None) -> List[DoseLog]:
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
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if medicine:
                medicine.inventory_count = new_count
                await session.commit()

    @staticmethod
    async def log_dose_taken(medicine_id: int, scheduled_time: datetime, taken_at: datetime = None) -> DoseLog:
        if taken_at is None:
            taken_at = datetime.utcnow()
        async with async_session() as session:
            dose_log = DoseLog(
                medicine_id=medicine_id, scheduled_time=scheduled_time, taken_at=taken_at, status="taken"
            )
            session.add(dose_log)
            await session.commit()
            await session.refresh(dose_log)
            return dose_log

    @staticmethod
    async def log_dose_skipped(medicine_id: int, scheduled_time: datetime, reason: Optional[str] = None) -> DoseLog:
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
        async with async_session() as session:
            dose_log = DoseLog(
                medicine_id=medicine_id, scheduled_time=scheduled_time, taken_at=None, status="missed"
            )
            session.add(dose_log)
            await session.commit()
            await session.refresh(dose_log)
            return dose_log

    @staticmethod
    async def get_missed_doses(user_id: int, days: int = 7) -> List[DoseLog]:
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
    async def get_user_caregivers(user_id: int, active_only: bool = True) -> List[Caregiver]:
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
    async def set_medicine_active(medicine_id: int, is_active: bool) -> bool:
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if not medicine:
                return False
            medicine.is_active = is_active
            await session.commit()
            return True

    @staticmethod
    async def update_user_timezone(user_id: int, timezone: str) -> bool:
        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return False
            user.timezone = timezone
            await session.commit()
            return True

    @staticmethod
    async def delete_medicine_schedule(schedule_id: int) -> bool:
        async with async_session() as session:
            schedule = await session.get(MedicineSchedule, schedule_id)
            if not schedule:
                return False
            await session.delete(schedule)
            await session.commit()
            return True

    @staticmethod
    async def get_medicine_schedule_rows(medicine_id: int) -> List[MedicineSchedule]:
        async with async_session() as session:
            result = await session.execute(select(MedicineSchedule).where(MedicineSchedule.medicine_id == medicine_id))
            return list(result.scalars().all())

    @staticmethod
    async def replace_medicine_schedules(medicine_id: int, times: List[time]) -> None:
        async with async_session() as session:
            existing = await session.execute(select(MedicineSchedule).where(MedicineSchedule.medicine_id == medicine_id))
            for row in existing.scalars().all():
                await session.delete(row)
            for t in times:
                session.add(
                    MedicineSchedule(medicine_id=medicine_id, time_to_take=t, is_active=True, reminder_minutes_before=0)
                )
            await session.commit()

    @staticmethod
    async def delete_medicine(medicine_id: int) -> bool:
        async with async_session() as session:
            medicine = await session.get(Medicine, medicine_id)
            if not medicine:
                return False
            await session.delete(medicine)
            await session.commit()
            return True

    @staticmethod
    async def get_user_settings(user_id: int) -> UserSettings:
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
        async with async_session() as session:
            log = await session.get(SymptomLog, log_id)
            if not log:
                return False
            await session.delete(log)
            await session.commit()
            return True

    @staticmethod
    async def get_low_stock_medicines() -> List[Medicine]:
        async with async_session() as session:
            result = await session.execute(
                select(Medicine).where(Medicine.is_active == True, Medicine.inventory_count <= Medicine.low_stock_threshold)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_medicine_doses_in_range(medicine_id: int, start_date, end_date) -> List[DoseLog]:
        day_start = datetime.combine(start_date, datetime.min.time())
        day_end = datetime.combine(end_date, datetime.max.time())
        async with async_session() as session:
            result = await session.execute(
                select(DoseLog)
                .where(
                    and_(
                        DoseLog.medicine_id == medicine_id,
                        or_(
                            and_(DoseLog.scheduled_time >= day_start, DoseLog.scheduled_time <= day_end),
                            and_(DoseLog.created_at >= day_start, DoseLog.created_at <= day_end),
                        ),
                    )
                )
                .order_by(DoseLog.scheduled_time.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_symptom_logs_in_range(user_id: int, start_date, end_date, medicine_id: Optional[int] = None) -> List[SymptomLog]:
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
    async def get_doses_for_date(user_id: int, day_date) -> List[DoseLog]:
        day_start = datetime.combine(day_date, datetime.min.time())
        day_end = datetime.combine(day_date, datetime.max.time())
        async with async_session() as session:
            result = await session.execute(
                select(DoseLog)
                .join(Medicine, DoseLog.medicine_id == Medicine.id)
                .where(
                    Medicine.user_id == user_id,
                    or_(
                        and_(DoseLog.scheduled_time >= day_start, DoseLog.scheduled_time <= day_end),
                        and_(DoseLog.created_at >= day_start, DoseLog.created_at <= day_end),
                    ),
                )
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
    ) -> SymptomLog:
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
    async def create_invite(user_id: int, caregiver_name: Optional[str] = None, ttl_hours: int = 72) -> Invite:
        import random

        code = f"MED-{random.randint(10000, 99999)}"
        expires_at = datetime.utcnow() + timedelta(hours=max(1, int(ttl_hours)))
        async with async_session() as session:
            inv = Invite(code=code, user_id=user_id, caregiver_name=caregiver_name, status="active", expires_at=expires_at)
            session.add(inv)
            await session.commit()
            await session.refresh(inv)
            return inv

    @staticmethod
    async def get_invite_by_code(code: str) -> Optional[Invite]:
        async with async_session() as session:
            result = await session.execute(select(Invite).where(Invite.code == code))
            inv = result.scalars().first()
            return inv

    @staticmethod
    async def mark_invite_used(code: str) -> bool:
        async with async_session() as session:
            result = await session.execute(select(Invite).where(Invite.code == code))
            inv = result.scalars().first()
            if not inv:
                return False
            inv.status = "used"
            await session.commit()
            return True

    @staticmethod
    async def cancel_invite(code: str) -> bool:
        async with async_session() as session:
            result = await session.execute(select(Invite).where(Invite.code == code))
            inv = result.scalars().first()
            if not inv:
                return False
            inv.status = "canceled"
            await session.commit()
            return True

    @staticmethod
    async def get_user_appointments(
        user_id: int, start_date: date = None, end_date: date = None, offset: int = 0, limit: int = 10
    ) -> List[Appointment]:
        async with async_session() as session:
            query = select(Appointment).where(Appointment.user_id == user_id)
            if start_date is not None or end_date is not None:
                rng = {}
                if start_date is not None:
                    rng["$gte"] = datetime.combine(start_date, datetime.min.time())
                if end_date is not None:
                    rng["$lte"] = datetime.combine(end_date, datetime.max.time())
            result = await session.execute(query.order_by(Appointment.when_at.asc()))
            rows = list(result.scalars().all())
            return rows[offset : offset + max(1, limit)]

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
    ) -> Appointment:
        async with async_session() as session:
            appt = Appointment(
                user_id=user_id,
                category=category,
                title=title,
                when_at=when_at,
                remind_day_before=remind_day_before,
                remind_3days_before=remind_3days_before,
                remind_same_day=remind_same_day,
                same_day_reminder_time=same_day_reminder_time,
                notes=notes,
            )
            session.add(appt)
            await session.commit()
            await session.refresh(appt)
            return appt

    @staticmethod
    async def get_appointment_by_id(appointment_id: int) -> Optional[Appointment]:
        async with async_session() as session:
            return await session.get(Appointment, appointment_id)

    @staticmethod
    async def update_appointment(
        appointment_id: int,
        when_at: datetime = None,
        title: str = None,
        category: str = None,
        remind_day_before: bool = None,
        remind_3days_before: bool = None,
        remind_same_day: bool = None,
        same_day_reminder_time: time = None,
        notes: str = None,
    ):
        async with async_session() as session:
            appt = await session.get(Appointment, appointment_id)
            if not appt:
                return None
            if when_at is not None:
                appt.when_at = when_at
            if title is not None:
                appt.title = title
            if category is not None:
                appt.category = category
            if remind_day_before is not None:
                appt.remind_day_before = bool(remind_day_before)
            if remind_3days_before is not None:
                appt.remind_3days_before = bool(remind_3days_before)
            if remind_same_day is not None:
                appt.remind_same_day = bool(remind_same_day)
            if same_day_reminder_time is not None:
                appt.same_day_reminder_time = same_day_reminder_time
            if notes is not None:
                appt.notes = notes
            await session.commit()
            return appt

    @staticmethod
    async def delete_appointment(appointment_id: int) -> bool:
        async with async_session() as session:
            appt = await session.get(Appointment, appointment_id)
            if not appt:
                return False
            await session.delete(appt)
            await session.commit()
            return True

    @staticmethod
    async def get_upcoming_appointments(user_id: int, until_days: int = 60):
        async with async_session() as session:
            now = datetime.utcnow()
            until = now + timedelta(days=until_days)
            result = await session.execute(
                select(Appointment)
                .where(Appointment.user_id == user_id, Appointment.when_at >= now, Appointment.when_at <= until)
                .order_by(Appointment.when_at.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_all_upcoming_appointments(until_days: int = 60) -> List[Appointment]:
        async with async_session() as session:
            now = datetime.utcnow()
            until = now + timedelta(days=until_days)
            result = await session.execute(
                select(Appointment).where(Appointment.when_at >= now, Appointment.when_at <= until).order_by(Appointment.when_at.asc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_all_active_users() -> List[User]:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.is_active == True))
            return list(result.scalars().all())

    @staticmethod
    async def get_all_active_caregivers() -> List[Caregiver]:
        async with async_session() as session:
            result = await session.execute(select(Caregiver).where(Caregiver.is_active == True))
            return list(result.scalars().all())


# Note: MongoDB alternate backend definition omitted for brevity since default backend is SQLite.
# If needed, a Mongo implementation can be reintroduced and toggled via config.DB_BACKEND == "mongo".

