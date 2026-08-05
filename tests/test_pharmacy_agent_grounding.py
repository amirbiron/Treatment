"""Grounding tests for the pharmacy agent.

The incident these cover: a user asked about a medication at a named branch, no
intent regex matched, the message went to Gemini with no tool output, and the
model produced a branch, an address and a "✅ במלאי" status out of nothing - for
a medication bot. Two things now prevent that: the model reaches data only
through declared tools, and a tool failure is returned to the user verbatim
instead of being handed to the model to narrate.
"""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

agent = importlib.import_module("handlers.pharmacy_agent")


def _ctx(model=None):
    ctx = MagicMock()
    ctx.user_data = {"pharm_model": model or MagicMock(), "pharm_chat_history": []}
    return ctx


def _call(name, **args):
    call = MagicMock()
    call.name = name
    call.args = args
    return call


def _response(*calls, text="תשובה"):
    """A Gemini response carrying zero or more function calls."""
    parts = []
    for call in calls:
        part = MagicMock()
        part.function_call = call
        parts.append(part)
    if not calls:
        part = MagicMock()
        part.function_call = None
        parts.append(part)

    candidate = MagicMock()
    candidate.content.parts = parts
    response = MagicMock()
    response.candidates = [candidate]
    response.text = text
    return response


def _chat(*responses):
    chat = MagicMock()
    chat.send_message_async = AsyncMock(side_effect=list(responses))
    return chat


def _model(*responses):
    model = MagicMock()
    model.start_chat = MagicMock(return_value=_chat(*responses))
    return model


# --- the tools are the only way to data ----------------------------------


def test_every_declared_tool_can_actually_be_dispatched():
    """A name Gemini can call but the code cannot run would fail mid-conversation."""
    declared = {d["name"] for d in agent.FUNCTION_DECLARATIONS}
    assert declared == set(agent._TOOL_DISPATCH)


def test_stock_requires_a_catcode_from_a_search():
    """Stock cannot be asked for out of thin air; it needs a real code first."""
    stock = next(d for d in agent.FUNCTION_DECLARATIONS if d["name"] == "check_stock")
    assert stock["parameters"]["required"] == ["cat_code"]


def test_the_model_is_created_with_the_tools_attached():
    ctx = MagicMock()
    ctx.user_data = {}
    with patch.object(agent, "genai") as genai_mock, patch.dict(
        agent.os.environ, {"GEMINI_API_KEY": "k"}
    ):
        agent._init_ai_session(ctx)

    kwargs = genai_mock.GenerativeModel.call_args.kwargs
    assert kwargs["tools"] == [{"function_declarations": agent.FUNCTION_DECLARATIONS}]


def test_the_prompt_forbids_inventing_data():
    assert "אסור להמציא נתונים" in agent.SYSTEM_PROMPT
    assert "אל תסמלץ" in agent.SYSTEM_PROMPT


# --- a failing tool never reaches the model ------------------------------


@pytest.mark.asyncio
async def test_a_missing_skill_is_reported_not_narrated():
    """Today's failure: the tool was absent and the model answered anyway."""
    ctx = _ctx(_model(_response(_call("search_medication", query="ריקסולטי"))))
    failure = agent.ToolResult(False, "שגיאה: כלי חיפוש בית מרקחת לא מותקן.")

    with patch.object(agent, "_search_medication", AsyncMock(return_value=failure)):
        response, _, is_real = await agent._process_with_tools(ctx, 'ריקסולטי 3 מ"ג סניף בארי')

    assert response == failure.text, "the tool error must reach the user unchanged"
    assert is_real is False, "a failure must not be committed to chat history"


@pytest.mark.asyncio
async def test_the_model_is_not_asked_to_continue_after_a_tool_failure():
    model = _model(_response(_call("search_medication", query="x")))
    ctx = _ctx(model)
    failure = agent.ToolResult(False, "שגיאה בחיפוש: 403")

    with patch.object(agent, "_search_medication", AsyncMock(return_value=failure)):
        await agent._process_with_tools(ctx, "שאלה")

    chat = model.start_chat.return_value
    assert chat.send_message_async.await_count == 1, "the failure was fed back to the model"


@pytest.mark.asyncio
async def test_a_successful_result_is_fed_back_for_phrasing():
    model = _model(
        _response(_call("search_medication", query="ריקסולטי")),
        _response(text="מצאתי את ריקסולטי."),
    )
    ctx = _ctx(model)
    ok = agent.ToolResult(True, "catCode: 12345")

    with patch.object(agent, "_search_medication", AsyncMock(return_value=ok)):
        response, _, is_real = await agent._process_with_tools(ctx, "חפש ריקסולטי")

    assert response == "מצאתי את ריקסולטי."
    assert is_real is True
    assert model.start_chat.return_value.send_message_async.await_count == 2


@pytest.mark.asyncio
async def test_a_search_then_stock_chain_runs_both_tools():
    model = _model(
        _response(_call("search_medication", query="ריקסולטי")),
        _response(_call("check_stock", cat_code="12345", city_code="5000")),
        _response(text="במלאי בסניף."),
    )
    ctx = _ctx(model)
    search = AsyncMock(return_value=agent.ToolResult(True, "catCode: 12345"))
    stock = AsyncMock(return_value=agent.ToolResult(True, "status: במלאי"))

    with patch.object(agent, "_search_medication", search), patch.object(agent, "_check_stock", stock):
        response, _, is_real = await agent._process_with_tools(ctx, "יש ריקסולטי בתל אביב?")

    search.assert_awaited_once()
    stock.assert_awaited_once_with("12345", "5000", "")
    assert response == "במלאי בסניף." and is_real is True


@pytest.mark.asyncio
async def test_tool_rounds_are_bounded():
    """A model that keeps calling tools must not spin forever."""
    endless = [_response(_call("list_cities", query="")) for _ in range(agent.MAX_TOOL_ROUNDS + 3)]
    model = _model(*endless)
    ctx = _ctx(model)

    with patch.object(agent, "_list_cities", AsyncMock(return_value=agent.ToolResult(True, "ok"))):
        await agent._process_with_tools(ctx, "ערים")

    # one opening call plus at most MAX_TOOL_ROUNDS tool round-trips
    assert model.start_chat.return_value.send_message_async.await_count <= agent.MAX_TOOL_ROUNDS + 1


@pytest.mark.asyncio
async def test_an_unknown_tool_name_does_not_crash_the_turn():
    model = _model(_response(_call("delete_everything", query="x")), _response(text="בסדר"))
    ctx = _ctx(model)

    response, _, is_real = await agent._process_with_tools(ctx, "שאלה")

    assert response == "בסדר" and is_real is True


@pytest.mark.asyncio
async def test_a_plain_answer_with_no_tool_call_is_still_returned():
    """Conversational turns - 'what can you do' - do not need a tool."""
    ctx = _ctx(_model(_response(text="אני יכול לחפש תרופות.")))
    response, _, is_real = await agent._process_with_tools(ctx, "מה אתה יכול לעשות?")

    assert response == "אני יכול לחפש תרופות." and is_real is True


@pytest.mark.asyncio
async def test_shortcuts_go_through_the_tool_path():
    """The shortcut buttons used to bypass tools entirely."""
    update = MagicMock()
    update.callback_query.data = "pharm_check_stock"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    ctx = _ctx()

    with patch.object(
        agent, "_process_with_tools", AsyncMock(return_value=("טקסט", "m", True))
    ) as routed:
        await agent.handle_shortcut(update, ctx)

    routed.assert_awaited_once()
    assert routed.await_args.args[1] == agent.TOPIC_SHORTCUTS["pharm_check_stock"]


# --- self-healing install ------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_install_state():
    """The failure reason is cached module-wide; each test starts clean."""
    agent._install_failed_reason = None
    yield
    agent._install_failed_reason = None


@pytest.mark.asyncio
async def test_an_installed_skill_is_not_reinstalled():
    with patch.object(agent, "is_skill_installed", return_value=True), patch.object(
        agent.asyncio, "create_subprocess_exec"
    ) as spawn:
        result = await agent.ensure_skill_installed()

    assert result.ok is True
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_a_missing_skill_is_installed_on_demand():
    """Render wipes the disk on restart, so the agent installs it itself."""
    installed = iter([False, False, True, True])
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"done", b""))

    with patch.object(agent, "is_skill_installed", side_effect=lambda: next(installed)), patch.object(
        agent.shutil, "which", return_value="/usr/bin/x"
    ), patch.object(agent.os.path, "isfile", return_value=True), patch.object(
        agent.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
    ) as spawn:
        result = await agent.ensure_skill_installed()

    assert result.ok is True
    assert spawn.await_args.args[0] == "bash"


@pytest.mark.asyncio
async def test_a_missing_binary_is_named_in_the_error():
    with patch.object(agent, "is_skill_installed", return_value=False), patch.object(
        agent.shutil, "which", side_effect=lambda b: None if b == "node" else "/usr/bin/x"
    ):
        result = await agent.ensure_skill_installed()

    assert result.ok is False
    assert "node" in result.text


@pytest.mark.asyncio
async def test_a_failed_install_is_not_retried_on_every_message():
    """A clone that fails must not add a minutes-long stall to each request."""
    proc = MagicMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"boom", b""))

    with patch.object(agent, "is_skill_installed", return_value=False), patch.object(
        agent.shutil, "which", return_value="/usr/bin/x"
    ), patch.object(agent.os.path, "isfile", return_value=True), patch.object(
        agent.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
    ) as spawn:
        first = await agent.ensure_skill_installed()
        second = await agent.ensure_skill_installed()

    assert first.ok is False and second.ok is False
    assert spawn.await_count == 1, "the failed install was attempted again"


@pytest.mark.asyncio
async def test_a_command_reports_the_install_failure_rather_than_running_node():
    with patch.object(
        agent, "ensure_skill_installed", AsyncMock(return_value=agent.ToolResult(False, "שגיאה: אין node"))
    ), patch.object(agent.asyncio, "create_subprocess_exec") as spawn:
        result = await agent._run_pharmacy_command("search", "x")

    assert result.ok is False and result.text == "שגיאה: אין node"
    spawn.assert_not_called()
