"""Tests for the Israeli emergency guide agent.

The thing worth testing here is not that the agent answers, but that it cannot
answer wrongly in the ways that matter: an invented emergency number, a
confident answer about a scenario the guide never covered, and an API round trip
standing between a person who is not breathing and the digits 101.
"""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

agent = importlib.import_module("handlers.emergency_agent")


def _ctx(answer="תשובה"):
    response = MagicMock()
    response.text = answer
    chat = MagicMock()
    chat.send_message_async = AsyncMock(return_value=response)
    model = MagicMock()
    model.start_chat = MagicMock(return_value=chat)

    ctx = MagicMock()
    ctx.user_data = {"emerg_model": model, "emerg_chat_history": []}
    return ctx


def _message(text):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    return update


# --- the guide is really loaded --------------------------------------------


def test_the_guide_is_present_and_not_empty():
    """Everything else is meaningless if the docs did not ship."""
    assert agent.is_guide_available()
    assert len(agent.GUIDE_TEXT) > 10_000


def test_the_hospital_directory_is_included():
    assert "סורוקה" in agent.GUIDE_TEXT or "Soroka" in agent.GUIDE_TEXT


def test_the_coverage_contract_is_not_fed_to_the_model():
    """domain-checklist.md is a reviewer document, not answer material."""
    assert "domain-checklist" not in "".join(agent.GUIDE_FILES)
    assert "Coverage Contract" not in agent.GUIDE_TEXT


@pytest.mark.parametrize("number", [n for n, _s, _w in agent.EMERGENCY_NUMBERS])
def test_every_quick_reference_number_appears_in_the_guide(number):
    """The hardcoded card and the guide must not drift apart silently."""
    for part in number.split("/"):
        assert part.strip() in agent.GUIDE_TEXT


# --- an invented phone number never reaches the user ------------------------


@pytest.mark.asyncio
async def test_an_invented_emergency_number_is_rejected():
    """The failure that matters most: a plausible number that does not exist."""
    ctx = _ctx("במקרה חירום חייגו 108 מיד.")

    reply, is_real = await agent.ask_guide(ctx, "למי מתקשרים?")

    assert "108" not in reply
    assert reply == agent._ERR_UNVERIFIED
    assert is_real is False, "an unverified answer must not enter chat history"


@pytest.mark.asyncio
async def test_a_real_number_passes_through():
    ctx = _ctx('חייגו 101 למד"א.')

    reply, is_real = await agent.ask_guide(ctx, "למי מתקשרים?")

    assert "101" in reply and is_real is True


@pytest.mark.asyncio
async def test_an_invented_hospital_phone_is_rejected():
    ctx = _ctx("חדר המיון בסורוקה: 08-1234567")

    reply, _ = await agent.ask_guide(ctx, "טלפון לסורוקה")

    assert reply == agent._ERR_UNVERIFIED


def test_a_real_hospital_phone_verifies():
    assert agent.verify_answer("סורוקה: 08-6400111").ok


@pytest.mark.parametrize(
    "text",
    [
        "ההשתתפות העצמית היא 1,199 ש\"ח",
        "זמן התגובה הוא כ-8 דקות",
        "ברזילי שודרג ב-2023",
        "חום של 39.5 מעלות",
        "נשארים 10 דקות במרחב המוגן",
    ],
)
def test_amounts_years_and_durations_are_not_mistaken_for_numbers(text):
    """A validator that rejects good answers would just get switched off."""
    assert agent.verify_answer(text).ok, f"false positive on {text!r}"


def test_the_star_code_for_natal_verifies():
    assert agent.verify_answer("נט\"ל *3362").ok


def test_an_invented_star_code_is_caught():
    assert agent.verify_answer("חייגו *9999").ok is False


def test_the_verdict_names_the_offending_number():
    verdict = agent.verify_answer("חייגו 108")
    assert verdict.bad == "108"


# --- life-threatening messages never wait for the model ---------------------


@pytest.mark.parametrize(
    "text",
    [
        "אבא שלי לא נושם",
        "היא לא מגיבה בכלל",
        "יש לו כאבים בחזה",
        "מישהו התעלף פה",
        "דימום חמור מהיד",
        "חשד לשבץ",
        "הילד נחנק",
    ],
)
def test_a_life_threatening_message_is_classified_critical(text):
    assert agent.classify(text) == "critical"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("הוא לא נושם", "critical"),          # ends in final mem
        ("היא לא נושמת", "critical"),         # same stem, regular mem
        ("יש פה חומר מסוכן", "uncovered"),    # ends in final nun
        ("יש פה חומרים מסוכנים", "uncovered"),
    ],
)
def test_final_letter_forms_match_too(text, expected):
    """A stem written without its final form silently matches nothing in Hebrew."""
    assert agent.classify(text) == expected


@pytest.mark.asyncio
async def test_a_critical_message_does_not_call_the_model():
    """Seconds of API latency are not acceptable when someone is not breathing."""
    ctx = _ctx()
    update = _message("אבא שלי לא נושם")

    await agent.handle_message(update, ctx)

    ctx.user_data["emerg_model"].start_chat.assert_not_called()
    sent = update.message.reply_text.await_args.args[0]
    assert "101" in sent


@pytest.mark.asyncio
async def test_the_critical_reply_offers_the_no_voice_channel():
    """A caller who cannot speak still needs a way through."""
    assert "052-7000101" in agent.critical_reply()


def test_the_critical_reply_only_uses_verified_numbers():
    assert agent.verify_answer(agent.critical_reply()).ok


# --- suicidal distress is routed to the right line, not to 101 --------------


@pytest.mark.parametrize(
    "text",
    [
        "יש לי מחשבות אובדניות",
        "אני רוצה להתאבד",
        "אני לא רוצה לחיות יותר",
        "אני רוצה למות",
        "נמאס לי לחיות",
        "אני רוצה לגמור עם הכל",
        "אני חושב לפגוע בעצמי",
    ],
)
def test_suicidal_distress_gets_its_own_route(text):
    assert agent.classify(text) == "mental_health"


@pytest.mark.asyncio
async def test_the_mental_health_reply_leads_with_eran_not_an_ambulance():
    ctx = _ctx()
    update = _message("יש לי מחשבות אובדניות")

    await agent.handle_message(update, ctx)

    sent = update.message.reply_text.await_args.args[0]
    assert "1201" in sent
    assert sent.index("1201") < sent.index("101"), "an ambulance is not the first answer here"
    ctx.user_data["emerg_model"].start_chat.assert_not_called()


def test_the_mental_health_reply_only_uses_verified_numbers():
    assert agent.verify_answer(agent._MENTAL_HEALTH_REPLY).ok


# --- known gaps are refused, not improvised ---------------------------------


@pytest.mark.parametrize(
    "text,topic",
    [
        ("יש חדירת מחבלים ליישוב, מה עושים?", "חדירת מחבלים"),
        ("יש דליפת גז מסוכן ברחוב", "אירוע חומרים מסוכנים"),
        ("מה עושים באירוע קרינה גרעינית?", "אירוע רדיולוגי"),
        ("הייתה רעידת אדמה, יש סכנת צונאמי?", "חשש לצונאמי"),
    ],
)
def test_scenarios_the_guide_never_covered_are_refused(text, topic):
    """The guide's own coverage contract marks these as deliberate gaps."""
    assert agent.classify(text) == "uncovered"
    assert agent.uncovered_topic(text) == topic


@pytest.mark.asyncio
async def test_an_uncovered_scenario_routes_to_home_front_command():
    ctx = _ctx()
    update = _message("יש חדירת מחבלים ליישוב")

    await agent.handle_message(update, ctx)

    sent = update.message.reply_text.await_args.args[0]
    assert "104" in sent
    ctx.user_data["emerg_model"].start_chat.assert_not_called(), "the model was asked to improvise"


def test_shelter_exit_is_covered_so_it_reaches_the_model():
    """Step 8 does cover this, and it is the guide's most safety-critical answer."""
    assert agent.classify("כמה זמן נשארים בממד אחרי אזעקה?") == "ask_model"


# --- ordinary questions still work ------------------------------------------


@pytest.mark.asyncio
async def test_an_ordinary_question_reaches_the_model_and_is_remembered():
    ctx = _ctx("לכו לטרם.")
    update = _message("מתי הולכים לטרם?")

    await agent.handle_message(update, ctx)

    ctx.user_data["emerg_model"].start_chat.assert_called_once()
    assert len(ctx.user_data["emerg_chat_history"]) == 2


@pytest.mark.asyncio
async def test_a_rejected_answer_is_not_remembered():
    ctx = _ctx("חייגו 108.")
    update = _message("מתי הולכים לטרם?")

    await agent.handle_message(update, ctx)

    assert ctx.user_data["emerg_chat_history"] == []


@pytest.mark.asyncio
async def test_an_api_failure_is_reported_not_narrated():
    ctx = _ctx()
    ctx.user_data["emerg_model"].start_chat.return_value.send_message_async = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    reply, is_real = await agent.ask_guide(ctx, "שאלה")

    assert reply == agent._ERR_AI_COMM and is_real is False


@pytest.mark.asyncio
async def test_every_answer_carries_the_disclaimer():
    ctx = _ctx("לכו לטרם.")
    reply, _ = await agent.ask_guide(ctx, "מתי הולכים לטרם?")

    assert agent.DISCLAIMER.strip() in reply


# --- the deterministic card --------------------------------------------------


def test_the_numbers_card_needs_no_model():
    card = agent.format_emergency_numbers()
    assert "101" in card and "100" in card and "102" in card


def test_the_card_warns_about_112():
    """112 reaches the police only; sending a medical emergency there costs time."""
    assert "112" in agent.format_emergency_numbers()


def test_the_card_only_uses_verified_numbers():
    assert agent.verify_answer(agent.format_emergency_numbers()).ok


@pytest.mark.asyncio
async def test_the_daily_limit_still_leaves_the_numbers_reachable():
    """Running out of Gemini quota must not take emergency numbers with it."""
    ctx = _ctx()
    update = _message("מתי הולכים לטרם?")

    with patch.object(agent, "is_limit_reached", return_value=True):
        await agent.handle_message(update, ctx)

    sent = update.message.reply_text.await_args.args[0]
    assert "101" in sent
    ctx.user_data["emerg_model"].start_chat.assert_not_called()


# --- entry point -------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_refuses_to_start_when_the_guide_is_missing():
    """Better a stated failure than an agent answering from model knowledge."""
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.user_data = {}

    with patch.object(agent, "is_guide_available", return_value=False):
        result = await agent.entry_from_callback(update, ctx)

    from telegram.ext import ConversationHandler

    assert result == ConversationHandler.END
    assert "101" in update.callback_query.message.reply_text.await_args.args[0]


def test_the_shortcut_prompts_are_all_dispatchable():
    pattern = r"^emerg_(triage|siren)$"
    import re

    for key in agent.TOPIC_SHORTCUTS:
        assert re.match(pattern, key), f"{key} is declared but never routed"
