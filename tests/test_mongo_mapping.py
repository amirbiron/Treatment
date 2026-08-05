"""Unit tests for the Mongo document-to-model helpers and id allocation.

These run without a Mongo server. The mapping helpers are pure functions over a
dict, and the id allocator is exercised against a small fake collection, so the
parts most likely to diverge from the SQL backend stay covered even though the
Mongo backend itself cannot be integration-tested here.
"""

from datetime import datetime, time
from unittest.mock import AsyncMock, patch

import pytest

from database import DatabaseManagerMongo


# --- notes ---------------------------------------------------------------


def test_note_doc_maps_every_field():
    now = datetime(2026, 8, 5, 10, 30)
    note = DatabaseManagerMongo._doc_to_note(
        {"_id": 3, "user_id": 11, "content": "טקסט", "created_at": now, "updated_at": now}
    )

    assert note.id == 3
    assert note.user_id == 11
    assert note.content == "טקסט"
    assert note.created_at == now
    assert note.updated_at == now


def test_note_doc_tolerates_missing_fields():
    note = DatabaseManagerMongo._doc_to_note({"_id": 1})
    assert note.id == 1
    assert note.content is None
    assert note.created_at is None


# --- custom reminders ----------------------------------------------------


def test_reminder_doc_parses_hhmm_into_a_time():
    """Mongo stores the hour as a string; the rest of the code expects a time."""
    reminder = DatabaseManagerMongo._doc_to_custom_reminder(
        {"_id": 5, "user_id": 11, "text": "שקילה", "repeat": "daily", "remind_time": "07:05"}
    )

    assert isinstance(reminder.remind_time, time)
    assert reminder.remind_time == time(7, 5)


def test_reminder_doc_leaves_remind_time_none_for_a_one_off():
    reminder = DatabaseManagerMongo._doc_to_custom_reminder(
        {"_id": 5, "repeat": "once", "remind_at": datetime(2030, 1, 1, 9, 0), "remind_time": None}
    )

    assert reminder.remind_time is None
    assert reminder.remind_at == datetime(2030, 1, 1, 9, 0)


@pytest.mark.parametrize("bad", ["", "not-a-time", 815, None])
def test_reminder_doc_survives_an_unparsable_time(bad):
    """A malformed value must not take down the whole reminder list."""
    reminder = DatabaseManagerMongo._doc_to_custom_reminder({"_id": 5, "remind_time": bad})
    assert reminder.remind_time is None


def test_reminder_doc_defaults_repeat_and_active():
    reminder = DatabaseManagerMongo._doc_to_custom_reminder({"_id": 5})
    assert reminder.repeat == "once"
    assert reminder.is_active is True


def test_reminder_doc_respects_an_explicit_inactive_flag():
    reminder = DatabaseManagerMongo._doc_to_custom_reminder({"_id": 5, "is_active": False})
    assert reminder.is_active is False


def test_reminder_doc_keeps_the_weekday():
    reminder = DatabaseManagerMongo._doc_to_custom_reminder(
        {"_id": 5, "repeat": "weekly", "remind_time": "07:30", "weekday": 6}
    )
    assert reminder.weekday == 6


# --- id allocation -------------------------------------------------------


class _FakeCounters:
    """Stands in for the counters collection, incrementing in memory."""

    def __init__(self):
        self.seqs = {}

    async def find_one_and_update(self, filter_, update, **kwargs):
        key = filter_["_id"]
        if "$inc" in update:
            self.seqs[key] = self.seqs.get(key, 0) + update["$inc"]["seq"]
        if "$set" in update:
            self.seqs[key] = update["$set"]["seq"]
        return {"_id": key, "seq": self.seqs[key]}


class _FakeCollection:
    def __init__(self, name, existing_ids=()):
        self.name = name
        self._ids = sorted(existing_ids, reverse=True)

    def find(self):
        return self

    def sort(self, *_args):
        return self

    def limit(self, *_args):
        return self

    async def to_list(self, _n):
        return [{"_id": self._ids[0]}] if self._ids else []


@pytest.mark.asyncio
async def test_ids_are_handed_out_once_each():
    """max(_id)+1 read client-side hands the same id to concurrent writers."""
    counters = _FakeCounters()
    collection = _FakeCollection("notes")

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.counters = counters
        ids = [await DatabaseManagerMongo._next_mongo_id(collection) for _ in range(5)]

    assert ids == [1, 2, 3, 4, 5]
    assert len(set(ids)) == len(ids)


@pytest.mark.asyncio
async def test_concurrent_allocations_never_collide():
    import asyncio

    counters = _FakeCounters()
    collection = _FakeCollection("notes")

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.counters = counters
        ids = await asyncio.gather(
            *[DatabaseManagerMongo._next_mongo_id(collection) for _ in range(50)]
        )

    assert len(set(ids)) == 50, "two writers were handed the same _id"


@pytest.mark.asyncio
async def test_a_fresh_counter_starts_above_pre_existing_documents():
    """A collection written before the counter existed must not be overwritten."""
    counters = _FakeCounters()
    collection = _FakeCollection("notes", existing_ids=[7, 3, 1])

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.counters = counters
        first = await DatabaseManagerMongo._next_mongo_id(collection)
        second = await DatabaseManagerMongo._next_mongo_id(collection)

    assert first == 8, "would have collided with the existing _id 7"
    assert second == 9


@pytest.mark.asyncio
async def test_counters_are_kept_per_collection():
    counters = _FakeCounters()
    notes = _FakeCollection("notes")
    reminders = _FakeCollection("custom_reminders")

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.counters = counters
        assert await DatabaseManagerMongo._next_mongo_id(notes) == 1
        assert await DatabaseManagerMongo._next_mongo_id(reminders) == 1
        assert await DatabaseManagerMongo._next_mongo_id(notes) == 2


def test_note_doc_maps_the_optional_title():
    named = DatabaseManagerMongo._doc_to_note({"_id": 1, "title": "רופא משפחה", "content": "גוף"})
    assert named.title == "רופא משפחה"

    unnamed = DatabaseManagerMongo._doc_to_note({"_id": 2, "content": "גוף"})
    assert unnamed.title is None, "a note written before titles existed must not break"


# --- appending (pipeline update) -----------------------------------------


class _CapturingNotes:
    """Records the update document instead of talking to Mongo."""

    def __init__(self):
        self.filter = None
        self.update = None

    async def update_one(self, filter_, update, **kwargs):
        self.filter = filter_
        self.update = update

        class _Res:
            matched_count = 1

        return _Res()


async def _append(text, note_id=5, user_id=11):
    notes = _CapturingNotes()
    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.notes = notes
        await DatabaseManagerMongo.append_to_note_for_user(note_id, user_id, text)
    return notes


@pytest.mark.asyncio
async def test_append_is_a_single_server_side_update():
    """Read-modify-write would let two quick additions overwrite each other."""
    notes = await _append("עוד שורה")

    assert isinstance(notes.update, list), "expected an aggregation pipeline, not a plain $set"
    assert notes.filter == {"_id": 5, "user_id": 11}, "the filter carries ownership"


@pytest.mark.asyncio
async def test_appended_text_is_wrapped_in_literal():
    """Text starting with $ would otherwise be read as a field path by Mongo."""
    notes = await _append("$content")

    rendered = repr(notes.update)
    assert "'$literal': '$content'" in rendered, "user text reached the pipeline unquoted"


@pytest.mark.asyncio
async def test_append_handles_an_empty_note_without_a_leading_newline():
    notes = await _append("ראשונה")
    stage = notes.update[0]["$set"]["content"]

    assert "$cond" in stage, "no branch for a note that has no content yet"
    empty_branch, non_empty_branch = stage["$cond"][1], stage["$cond"][2]
    assert empty_branch == {"$literal": "ראשונה"}
    assert "$concat" in non_empty_branch


@pytest.mark.asyncio
async def test_append_trims_trailing_newlines_like_the_sql_backend():
    """Without this the same note ends up formatted differently per backend."""
    import database

    notes = await _append("עוד")
    stage = notes.update[0]["$set"]["content"]
    existing = stage["$cond"][2]["$concat"][0]

    assert "$rtrim" in existing, "existing content is concatenated untrimmed"
    assert existing["$rtrim"]["chars"] == database.NOTE_TRAILING_CHARS


@pytest.mark.asyncio
async def test_the_emptiness_check_uses_the_trimmed_value():
    """A note holding only newlines must count as empty, or it gains a blank first line."""
    notes = await _append("ראשונה")
    stage = notes.update[0]["$set"]["content"]
    compared = stage["$cond"][0]["$eq"][0]

    assert "$rtrim" in compared
