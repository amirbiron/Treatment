"""
Lightweight in-memory database layer for the Medicine Reminder Bot.

This module provides minimal async implementations required by the rest of the
application to run. It defines model dataclasses and a `DatabaseManager` with
async CRUD-style methods used throughout the handlers and scheduler.

Note: This is an in-memory store intended for development and to keep
deployments unblocked. It can be replaced with a real DB (e.g., SQLAlchemy +
aiosqlite or Mongo via motor) without changing call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Sequence
import secrets


# -------------------------
# Model definitions
# -------------------------


@dataclass
class User:
    id: int
    telegram_id: int
    first_name: str = ""
    last_name: str = ""
    timezone: str = "UTC"
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Medicine:
    id: int
    user_id: int
    name: str
    dosage: str
    inventory_count: float = 0.0
    low_stock_threshold: float = 5.0
    is_active: bool = True
    notes: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MedicineSchedule:
    id: int
    medicine_id: int
    time_to_take: time


@dataclass
class DoseLog:
    id: int
    medicine_id: int
    status: str  # "taken" | "missed" | "skipped"
    scheduled_time: datetime
    taken_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Caregiver:
    id: int
    user_id: int
    caregiver_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    permissions: str = "view"  # view | manage | admin
    is_active: bool = True
    caregiver_telegram_id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Appointment:
    id: int
    user_id: int
    category: str
    title: str
    when_at: datetime
    remind_day_before: bool = False
    remind_3days_before: bool = False
    remind_same_day: bool = True
    same_day_reminder_time: Optional[time] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SymptomLog:
    id: int
    user_id: int
    medicine_id: Optional[int] = None
    symptoms: Optional[str] = None
    side_effects: Optional[str] = None
    mood_score: Optional[int] = None  # 0..10
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Invite:
    id: int
    user_id: int
    code: str
    created_at: datetime = field(default_factory=datetime.utcnow)


# -------------------------
# Database manager (in-memory)
# -------------------------


class DatabaseManager:
    """Minimal async in-memory implementation of the database API.

    Stored IDs are integers incremented per-entity. Users use `telegram_id` as
    their primary identifier. For convenience and compatibility, we set
    `User.id == User.telegram_id` when auto-creating users via Telegram ID.
    """

    # Entity stores
    _users: Dict[int, User] = {}
    _user_by_telegram: Dict[int, int] = {}
    _medicines: Dict[int, Medicine] = {}
    _schedules: Dict[int, MedicineSchedule] = {}
    _dose_logs: Dict[int, DoseLog] = {}
    _caregivers: Dict[int, Caregiver] = {}
    _appointments: Dict[int, Appointment] = {}
    _symptom_logs: Dict[int, SymptomLog] = {}
    _invites_by_code: Dict[str, Invite] = {}

    # ID counters
    _next_medicine_id: int = 1
    _next_schedule_id: int = 1
    _next_dose_id: int = 1
    _next_caregiver_id: int = 1
    _next_appointment_id: int = 1
    _next_symptom_log_id: int = 1
    _next_invite_id: int = 1

    @classmethod
    async def get_user_by_telegram_id(cls, telegram_id: int) -> Optional[User]:
        """Get-or-create user by Telegram ID.

        For convenience, the created user's `id` equals their `telegram_id`.
        """
        if telegram_id in cls._user_by_telegram:
            uid = cls._user_by_telegram[telegram_id]
            return cls._users.get(uid)
        # Auto-create a basic user to unblock flows
        user = User(id=telegram_id, telegram_id=telegram_id)
        cls._users[user.id] = user
        cls._user_by_telegram[telegram_id] = user.id
        return user

    @classmethod
    async def get_user_by_id(cls, user_id: int) -> Optional[User]:
        return cls._users.get(int(user_id))

    @classmethod
    async def get_all_active_users(cls) -> List[User]:
        return [u for u in cls._users.values() if u.is_active]

    # Medicines
    @classmethod
    async def create_medicine(
        cls,
        user_id: int,
        name: str,
        dosage: str,
        inventory_count: float = 0.0,
        low_stock_threshold: float = 5.0,
    ) -> Medicine:
        med = Medicine(
            id=cls._next_medicine_id,
            user_id=int(user_id),
            name=name,
            dosage=dosage,
            inventory_count=float(inventory_count),
            low_stock_threshold=float(low_stock_threshold),
        )
        cls._medicines[med.id] = med
        cls._next_medicine_id += 1
        return med

    @classmethod
    async def get_medicine_by_id(cls, medicine_id: int) -> Optional[Medicine]:
        return cls._medicines.get(int(medicine_id))

    @classmethod
    async def get_user_medicines(cls, user_id: int, active_only: bool = True) -> List[Medicine]:
        meds = [m for m in cls._medicines.values() if m.user_id == int(user_id)]
        if active_only:
            meds = [m for m in meds if m.is_active]
        # Sort by creation date for stable order
        meds.sort(key=lambda m: (m.created_at, m.id))
        return meds

    @classmethod
    async def update_inventory(cls, medicine_id: int, new_count: float) -> Optional[Medicine]:
        med = cls._medicines.get(int(medicine_id))
        if not med:
            return None
        med.inventory_count = max(0.0, float(new_count))
        return med

    @classmethod
    async def get_low_stock_medicines(cls) -> List[Medicine]:
        return [m for m in cls._medicines.values() if m.inventory_count <= m.low_stock_threshold and m.is_active]

    # Medicine schedules
    @classmethod
    async def create_medicine_schedule(cls, medicine_id: int, time_to_take: time) -> MedicineSchedule:
        sched = MedicineSchedule(id=cls._next_schedule_id, medicine_id=int(medicine_id), time_to_take=time_to_take)
        cls._schedules[sched.id] = sched
        cls._next_schedule_id += 1
        return sched

    @classmethod
    async def get_medicine_schedules(cls, medicine_id: int) -> List[MedicineSchedule]:
        lst = [s for s in cls._schedules.values() if s.medicine_id == int(medicine_id)]
        # Sort by time of day for consistent order
        lst.sort(key=lambda s: (s.time_to_take.hour, s.time_to_take.minute, s.id))
        return lst

    # Dose logs
    @classmethod
    async def log_dose_taken(
        cls, medicine_id: int, scheduled_time: datetime, taken_at: Optional[datetime] = None
    ) -> DoseLog:
        log = DoseLog(
            id=cls._next_dose_id,
            medicine_id=int(medicine_id),
            status="taken",
            scheduled_time=scheduled_time,
            taken_at=taken_at or scheduled_time,
        )
        cls._dose_logs[log.id] = log
        cls._next_dose_id += 1
        return log

    @classmethod
    async def log_dose_skipped(cls, medicine_id: int, scheduled_time: datetime) -> DoseLog:
        log = DoseLog(
            id=cls._next_dose_id,
            medicine_id=int(medicine_id),
            status="skipped",
            scheduled_time=scheduled_time,
            taken_at=None,
        )
        cls._dose_logs[log.id] = log
        cls._next_dose_id += 1
        return log

    @classmethod
    async def log_dose_missed(cls, medicine_id: int, scheduled_time: datetime) -> DoseLog:
        log = DoseLog(
            id=cls._next_dose_id,
            medicine_id=int(medicine_id),
            status="missed",
            scheduled_time=scheduled_time,
            taken_at=None,
        )
        cls._dose_logs[log.id] = log
        cls._next_dose_id += 1
        return log

    @classmethod
    async def get_recent_doses(
        cls, medicine_id: int, days: Optional[int] = None, hours: Optional[int] = None
    ) -> List[DoseLog]:
        now = datetime.utcnow()
        if hours is not None:
            cutoff = now - timedelta(hours=max(0, int(hours)))
        else:
            cutoff = now - timedelta(days=max(0, int(days or 7)))
        result = [
            d
            for d in cls._dose_logs.values()
            if d.medicine_id == int(medicine_id) and d.scheduled_time >= cutoff
        ]
        result.sort(key=lambda d: (d.scheduled_time, d.id), reverse=True)
        return result

    @classmethod
    async def get_missed_doses(cls, user_id: int, days: int = 7) -> List[DoseLog]:
        cutoff = datetime.utcnow() - timedelta(days=max(0, int(days)))
        user_meds = {m.id for m in await cls.get_user_medicines(int(user_id), active_only=False)}
        result = [
            d
            for d in cls._dose_logs.values()
            if d.medicine_id in user_meds and d.scheduled_time >= cutoff and d.status in {"missed", "skipped"}
        ]
        result.sort(key=lambda d: (d.scheduled_time, d.id), reverse=True)
        return result

    @classmethod
    async def get_medicine_doses_in_range(cls, medicine_id: int, start_date: date, end_date: date) -> List[DoseLog]:
        start_dt = datetime.combine(start_date, time(0, 0))
        end_dt = datetime.combine(end_date, time(23, 59, 59))
        result = [
            d
            for d in cls._dose_logs.values()
            if d.medicine_id == int(medicine_id) and start_dt <= d.scheduled_time <= end_dt
        ]
        result.sort(key=lambda d: (d.scheduled_time, d.id))
        return result

    @classmethod
    async def get_doses_for_date(cls, user_id: int, d: date) -> List[DoseLog]:
        meds = {m.id for m in await cls.get_user_medicines(int(user_id), active_only=False)}
        start_dt = datetime.combine(d, time(0, 0))
        end_dt = datetime.combine(d, time(23, 59, 59))
        items = [
            log
            for log in cls._dose_logs.values()
            if log.medicine_id in meds and start_dt <= log.scheduled_time <= end_dt
        ]
        items.sort(key=lambda l: (l.scheduled_time, l.id))
        return items

    # Caregivers
    @classmethod
    async def create_caregiver(
        cls,
        user_id: int,
        caregiver_name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        permissions: str = "view",
        caregiver_telegram_id: Optional[int] = None,
    ) -> Caregiver:
        cg = Caregiver(
            id=cls._next_caregiver_id,
            user_id=int(user_id),
            caregiver_name=caregiver_name,
            phone=phone,
            email=email,
            permissions=permissions,
            caregiver_telegram_id=caregiver_telegram_id,
        )
        cls._caregivers[cg.id] = cg
        cls._next_caregiver_id += 1
        return cg

    @classmethod
    async def update_caregiver(
        cls,
        caregiver_id: int,
        caregiver_name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        permissions: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Caregiver]:
        cg = cls._caregivers.get(int(caregiver_id))
        if not cg:
            return None
        if caregiver_name is not None:
            cg.caregiver_name = caregiver_name
        if phone is not None:
            cg.phone = phone
        if email is not None:
            cg.email = email
        if permissions is not None:
            cg.permissions = permissions
        if is_active is not None:
            cg.is_active = bool(is_active)
        return cg

    @classmethod
    async def get_user_caregivers(cls, user_id: int, active_only: bool = False) -> List[Caregiver]:
        cgs = [c for c in cls._caregivers.values() if c.user_id == int(user_id)]
        if active_only:
            cgs = [c for c in cgs if c.is_active]
        cgs.sort(key=lambda c: (c.created_at, c.id))
        return cgs

    @classmethod
    async def get_all_active_caregivers(cls) -> List[Caregiver]:
        return [c for c in cls._caregivers.values() if c.is_active]

    @classmethod
    async def get_caregiver_by_id(cls, caregiver_id: int) -> Optional[Caregiver]:
        return cls._caregivers.get(int(caregiver_id))

    @classmethod
    async def delete_caregiver(cls, caregiver_id: int) -> bool:
        return bool(cls._caregivers.pop(int(caregiver_id), None))

    # Invites
    @classmethod
    async def create_invite(cls, user_id: int) -> Invite:
        # Short friendly code
        code = secrets.token_urlsafe(6)
        inv = Invite(id=cls._next_invite_id, user_id=int(user_id), code=code)
        cls._invites_by_code[code] = inv
        cls._next_invite_id += 1
        return inv

    # Appointments
    @classmethod
    async def create_appointment(
        cls,
        user_id: int,
        category: str,
        title: str,
        when_at: datetime,
        remind_day_before: bool = False,
        remind_3days_before: bool = False,
        remind_same_day: bool = True,
        same_day_reminder_time: Optional[time] = None,
    ) -> Appointment:
        appt = Appointment(
            id=cls._next_appointment_id,
            user_id=int(user_id),
            category=category,
            title=title,
            when_at=when_at,
            remind_day_before=bool(remind_day_before),
            remind_3days_before=bool(remind_3days_before),
            remind_same_day=bool(remind_same_day),
            same_day_reminder_time=same_day_reminder_time,
        )
        cls._appointments[appt.id] = appt
        cls._next_appointment_id += 1
        return appt

    @classmethod
    async def get_appointment_by_id(cls, appt_id: int) -> Optional[Appointment]:
        return cls._appointments.get(int(appt_id))

    @classmethod
    async def update_appointment(
        cls, appt_id: int, when_at: Optional[datetime] = None, title: Optional[str] = None
    ) -> Optional[Appointment]:
        appt = cls._appointments.get(int(appt_id))
        if not appt:
            return None
        if when_at is not None:
            appt.when_at = when_at
        if title is not None:
            appt.title = title
        return appt

    @classmethod
    async def delete_appointment(cls, appt_id: int) -> bool:
        return bool(cls._appointments.pop(int(appt_id), None))

    @classmethod
    async def get_user_appointments(
        cls,
        user_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> List[Appointment]:
        items = [a for a in cls._appointments.values() if a.user_id == int(user_id)]
        # Filter by date range if provided
        if start_date is not None:
            start_dt = datetime.combine(start_date, time(0, 0))
            items = [a for a in items if a.when_at >= start_dt]
        if end_date is not None:
            end_dt = datetime.combine(end_date, time(23, 59, 59))
            items = [a for a in items if a.when_at <= end_dt]
        # Upcoming first
        items.sort(key=lambda a: (a.when_at, a.id))
        return items[offset : max(offset, 0) + max(limit, 0)]

    @classmethod
    async def get_upcoming_appointments(cls, user_id: int, until_days: int = 365) -> List[Appointment]:
        now = datetime.utcnow()
        end = now + timedelta(days=max(0, int(until_days)))
        items = [a for a in cls._appointments.values() if a.user_id == int(user_id) and now < a.when_at <= end]
        items.sort(key=lambda a: (a.when_at, a.id))
        return items

    @classmethod
    async def get_all_upcoming_appointments(cls, until_days: int = 90) -> List[Appointment]:
        now = datetime.utcnow()
        end = now + timedelta(days=max(0, int(until_days)))
        items = [a for a in cls._appointments.values() if now < a.when_at <= end]
        items.sort(key=lambda a: (a.when_at, a.id))
        return items

    # Symptoms
    @classmethod
    async def get_symptom_logs_in_range(cls, user_id: int, start_date: date, end_date: date) -> List[SymptomLog]:
        start_dt = datetime.combine(start_date, time(0, 0))
        end_dt = datetime.combine(end_date, time(23, 59, 59))
        items = [
            s
            for s in cls._symptom_logs.values()
            if s.user_id == int(user_id) and start_dt <= s.created_at <= end_dt
        ]
        items.sort(key=lambda s: (s.created_at, s.id))
        return items


# -------------------------
# Initialization API
# -------------------------


async def init_database() -> None:
    """Initialize the database layer.

    This stub initializes in-memory stores. Replace with real DB bootstrapping
    (e.g., create engine, run migrations) when needed.
    """
    # No-op for in-memory backend; method kept async for compatibility
    return None


__all__ = [
    "User",
    "Medicine",
    "MedicineSchedule",
    "DoseLog",
    "Caregiver",
    "Appointment",
    "SymptomLog",
    "Invite",
    "DatabaseManager",
    "init_database",
]

