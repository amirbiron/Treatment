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
    chat = MagicMock()
    chat.send_message = AsyncMock(return_value=_response(answer))
    client = MagicMock()
    client.aio.chats.create = MagicMock(return_value=chat)

    ctx = MagicMock()
    ctx.user_data = {"emerg_client": client, "emerg_chat_history": []}
    return ctx


def _response(*texts, thoughts=()):
    """A response whose parts carry text, plus any parts flagged as thoughts."""
    parts = []
    for body in thoughts:
        part = MagicMock()
        part.text, part.thought = body, True
        parts.append(part)
    for body in texts:
        part = MagicMock()
        part.text, part.thought = body, False
        parts.append(part)

    candidate = MagicMock()
    candidate.content.parts = parts
    response = MagicMock()
    response.candidates = [candidate]
    response.text = "".join(texts)
    return response


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


def test_a_partial_guide_counts_as_no_guide():
    """A missing reference file would otherwise show up as rejected answers,
    not as a missing file."""
    real_open = open

    def fail_on_hospitals(path, *args, **kwargs):
        if "hospital-directory" in str(path):
            raise OSError("gone")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=fail_on_hospitals):
        assert agent._load_guide() == ""


def test_the_numbers_card_does_not_depend_on_the_ai_module():
    """The one screen someone may open in a hurry must not need google.generativeai."""
    import ast

    source = open("handlers/emergency_numbers.py", encoding="utf-8").read()
    imports = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert imports == [], "the standalone numbers card grew a dependency"


def test_the_agent_re_exports_the_card():
    """main.py and older call sites should keep working either way."""
    from handlers.emergency_numbers import format_emergency_numbers as standalone

    assert agent.format_emergency_numbers is standalone


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


# A model asked for a phone number does not always format it the way the guide
# does, and a shape the validator cannot see is a shape it cannot reject.


def test_a_guide_number_written_without_hyphens_still_verifies():
    assert agent.verify_answer("וואטסאפ ער\"ן 0528451201").ok


def test_an_invented_contiguous_mobile_is_caught():
    assert agent.verify_answer("חייגו 0591234567").ok is False


def test_an_invented_contiguous_landline_is_caught():
    assert agent.verify_answer("חדר מיון: 081234567").ok is False


def test_a_guide_landline_without_hyphens_verifies():
    assert agent.verify_answer("סורוקה 086400111").ok


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

    ctx.user_data["emerg_client"].aio.chats.create.assert_not_called()
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
    ctx.user_data["emerg_client"].aio.chats.create.assert_not_called()


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
    assert not ctx.user_data["emerg_client"].aio.chats.create.called, "the model was asked to improvise"


def test_shelter_exit_is_covered_so_it_reaches_the_model():
    """Step 8 does cover this, and it is the guide's most safety-critical answer."""
    assert agent.classify("כמה זמן נשארים בממד אחרי אזעקה?") == "ask_model"


# --- ordinary questions still work ------------------------------------------


@pytest.mark.asyncio
async def test_an_ordinary_question_reaches_the_model_and_is_remembered():
    ctx = _ctx("לכו לטרם.")
    update = _message("מתי הולכים לטרם?")

    await agent.handle_message(update, ctx)

    ctx.user_data["emerg_client"].aio.chats.create.assert_called_once()
    assert len(ctx.user_data["emerg_chat_history"]) == 2


@pytest.mark.asyncio
async def test_the_history_stops_growing():
    """The whole history is resent every request, so an uncapped one costs more
    with every message in the session."""
    ctx = _ctx("לכו לטרם.")
    update = _message("מתי הולכים לטרם?")

    for _ in range(30):
        await agent.handle_message(update, ctx)

    assert len(ctx.user_data["emerg_chat_history"]) == agent.MAX_HISTORY_MESSAGES


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, agent.DEFAULT_HISTORY_TURNS),
        ("", agent.DEFAULT_HISTORY_TURNS),
        ("   ", agent.DEFAULT_HISTORY_TURNS),
        ("3", 3),
        (" 4 ", 4),
        ("0", 0),
    ],
)
def test_the_history_length_reads_from_the_environment(raw, expected):
    environ = {} if raw is None else {agent.HISTORY_TURNS_ENV: raw}
    assert agent.history_turns_from_env(environ) == expected


@pytest.mark.parametrize("bad", ["abc", "5.5", "-1", "ten", "1e3"])
def test_a_bad_value_falls_back_instead_of_crashing(bad):
    """This knob is typed into a hosting dashboard; a typo must not kill the bot."""
    assert agent.history_turns_from_env({agent.HISTORY_TURNS_ENV: bad}) == (
        agent.DEFAULT_HISTORY_TURNS
    )


def test_an_absurd_value_is_clamped():
    turns = agent.history_turns_from_env({agent.HISTORY_TURNS_ENV: "10000"})
    assert turns == agent.MAX_HISTORY_TURNS


def test_zero_turns_keeps_no_history_at_all():
    """A legitimate setting: every question independent, grounded by the guide."""
    ctx = MagicMock()
    ctx.user_data = {}

    with patch.object(agent, "MAX_HISTORY_MESSAGES", 0):
        agent.remember(ctx, "שאלה", "תשובה")

    assert ctx.user_data["emerg_chat_history"] == []


def test_a_configured_length_is_honoured():
    ctx = MagicMock()
    ctx.user_data = {}

    with patch.object(agent, "MAX_HISTORY_MESSAGES", 4):
        for i in range(10):
            agent.remember(ctx, f"שאלה {i}", f"תשובה {i}")

    assert len(ctx.user_data["emerg_chat_history"]) == 4


def test_trimming_keeps_the_most_recent_exchange():
    ctx = MagicMock()
    ctx.user_data = {}

    for i in range(agent.MAX_HISTORY_MESSAGES):
        agent.remember(ctx, f"שאלה {i}", f"תשובה {i}")

    history = ctx.user_data["emerg_chat_history"]
    assert history[-2]["parts"] == [f"שאלה {agent.MAX_HISTORY_MESSAGES - 1}"]
    assert history[0]["role"] == "user", "trimming must not start mid-exchange"


@pytest.mark.asyncio
async def test_a_rejected_answer_is_not_remembered():
    ctx = _ctx("חייגו 108.")
    update = _message("מתי הולכים לטרם?")

    await agent.handle_message(update, ctx)

    assert ctx.user_data["emerg_chat_history"] == []


@pytest.mark.asyncio
async def test_an_api_failure_is_reported_not_narrated():
    ctx = _ctx()
    ctx.user_data["emerg_client"].aio.chats.create.return_value.send_message = AsyncMock(
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
    ctx.user_data["emerg_client"].aio.chats.create.assert_not_called()


@pytest.mark.asyncio
async def test_the_shortcut_buttons_respect_the_daily_limit_too():
    """A guard that lives at each call site gets forgotten at the next one."""
    ctx = _ctx()
    query = MagicMock()
    query.data = "emerg_triage"
    query.answer = AsyncMock()
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch.object(agent, "is_limit_reached", return_value=True):
        await agent.handle_shortcut(update, ctx)

    ctx.user_data["emerg_client"].aio.chats.create.assert_not_called()
    assert "101" in query.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_the_limit_is_enforced_inside_ask_guide():
    """So any future call site inherits it rather than having to repeat it."""
    ctx = _ctx()

    with patch.object(agent, "is_limit_reached", return_value=True):
        reply, is_real = await agent.ask_guide(ctx, "שאלה")

    assert is_real is False and "101" in reply
    ctx.user_data["emerg_client"].aio.chats.create.assert_not_called()


# --- a missing API key still leaves the numbers -------------------------------


@pytest.mark.asyncio
async def test_a_missing_api_key_returns_the_numbers_not_a_generic_error():
    """An unhandled RuntimeError here would surface as the bot's generic error."""
    ctx = MagicMock()
    ctx.user_data = {}

    with patch.object(agent, "_init_ai_session", side_effect=RuntimeError("no key")):
        reply, is_real = await agent.ask_guide(ctx, "שאלה")

    assert reply == agent._ERR_NO_AI
    assert "101" in reply and is_real is False


@pytest.mark.asyncio
async def test_entry_survives_a_missing_api_key():
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.user_data = {}

    with patch.object(agent, "_init_ai_session", side_effect=RuntimeError("no key")):
        result = await agent.entry_from_callback(update, ctx)

    from telegram.ext import ConversationHandler

    assert result == ConversationHandler.END
    assert "101" in update.callback_query.message.reply_text.await_args.args[0]


# --- broken Markdown must not swallow the answer ------------------------------


@pytest.mark.asyncio
async def test_an_unparseable_answer_is_resent_as_plain_text():
    """Telegram rejects the whole message on a stray asterisk; losing the bold
    beats losing the answer."""
    from telegram.error import BadRequest

    message = MagicMock()
    message.reply_text = AsyncMock(side_effect=[BadRequest("can't parse entities"), None])

    await agent.send_reply(message, "תשובה עם *כוכבית פתוחה")

    assert message.reply_text.await_count == 2
    assert "parse_mode" not in message.reply_text.await_args.kwargs


@pytest.mark.asyncio
async def test_a_parseable_answer_is_sent_once():
    message = MagicMock()
    message.reply_text = AsyncMock()

    await agent.send_reply(message, "תשובה תקינה")

    assert message.reply_text.await_count == 1
    assert message.reply_text.await_args.kwargs["parse_mode"] == "Markdown"


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


# --- the model's reasoning is not the answer ---------------------------------
#
# gemini-2.5-flash reasons before answering. google-generativeai could neither
# switch that off nor mark which parts were thoughts, so the reasoning arrived
# as ordinary text and users read it. google-genai can do both.


def test_thinking_is_switched_off_at_the_api():
    assert agent.THINKING_OFF.thinking_budget == 0
    assert agent.THINKING_OFF.include_thoughts is False


@pytest.mark.asyncio
async def test_the_request_carries_the_thinking_config():
    """The whole point of the migration: it is asked for, not stripped after."""
    ctx = _ctx("חייגו 101.")
    await agent.ask_guide(ctx, "שאלה")

    config = ctx.user_data["emerg_client"].aio.chats.create.call_args.kwargs["config"]
    assert config.thinking_config is agent.THINKING_OFF


def test_a_thought_part_is_dropped_from_the_answer():
    """Belt and braces: honour the flag even with thinking asked off."""
    response = _response("חייגו 101.", thoughts=["The user is asking about..."])
    assert agent.answer_text(response) == "חייגו 101."


def test_text_parts_are_joined_in_order():
    assert agent.answer_text(_response("חייגו ", "101.")) == "חייגו 101."


def test_a_response_without_walkable_parts_falls_back_to_text():
    """Losing a real emergency answer over an unexpected shape is the worse bug."""
    response = MagicMock()
    response.candidates = []
    response.text = "חייגו 101."
    assert agent.answer_text(response) == "חייגו 101."


def test_a_thought_only_response_falls_back_rather_than_returning_nothing():
    response = _response(thoughts=["only reasoning"])
    response.text = "חייגו 101."
    assert agent.answer_text(response) == "חייגו 101."


@pytest.mark.asyncio
async def test_reasoning_never_survives_a_real_turn():
    chat = MagicMock()
    chat.send_message = AsyncMock(
        return_value=_response("חייגו 101.", thoughts=["THOUGHT: planning"])
    )
    ctx = _ctx()
    ctx.user_data["emerg_client"].aio.chats.create = MagicMock(return_value=chat)

    reply, _ = await agent.ask_guide(ctx, "שאלה")

    assert "THOUGHT" not in reply
    assert reply.startswith("חייגו 101.")


# --- what the intro promises -------------------------------------------------


@pytest.mark.parametrize(
    "topic",
    ["בלי שיחת קול", "מרחב המוגן", "בריאות הנפש", "טרם", "חדר מיון", "טראומה דרג 1"],
)
def test_the_intro_lists_what_the_guide_actually_covers(topic):
    assert topic in agent.INTRO


def test_the_intro_still_says_not_to_use_it_in_a_real_emergency():
    assert "101" in agent.INTRO


# --- the SDK migration itself ------------------------------------------------


def test_the_deprecated_sdk_is_gone():
    """google-generativeai could not switch thinking off; that was the whole
    reason the reasoning reached users."""
    for path in ("handlers/emergency_agent.py", "handlers/pharmacy_agent.py"):
        source = open(path, encoding="utf-8").read()
        assert "google.generativeai" not in source, f"{path} still imports the old SDK"


def test_the_requirement_matches_the_import():
    requirements = open("requirements.txt", encoding="utf-8").read()
    assert "google-genai" in requirements
    assert "google-generativeai" not in requirements


def test_the_ci_matrix_dropped_the_python_google_genai_cannot_run_on():
    """google-genai requires >=3.10, and runtime.txt deploys on 3.11 anyway."""
    import glob

    for workflow in glob.glob(".github/workflows/*.yml"):
        assert "'3.9'" not in open(workflow, encoding="utf-8").read()
