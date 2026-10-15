"""A surface-only RunConfig must survive the whole run helper.

PR4 let a caller pass ``surface=`` instead of ``thread=``. Every caller that
actually did so was still a Discord one until PR6 rewired the scheduler, and
the helper's system-context builder still reached for ``config.thread.id``.
Nothing caught it: the scheduler's own tests mock ``run_claude_with_config``
out entirely, so the one function that broke was never executed.

These tests run it for real against a surface with no Discord object behind it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from claude_code_core.memory_surface import MemorySurface
from claude_discord.cogs._run_helper import _build_system_context
from claude_discord.cogs.run_config import RunConfig
from claude_discord.concurrency import SessionRegistry


def _runner() -> MagicMock:
    runner = MagicMock()
    runner.working_dir = "/tmp/example"
    runner.model = "test-model"
    return runner


async def test_system_context_is_built_without_a_discord_thread() -> None:
    surface = MemorySurface()
    config = RunConfig(
        surface=surface,
        runner=_runner(),
        prompt="scheduled work",
        registry=SessionRegistry(),
    )

    context = await _build_system_context(config)

    assert str(surface.thread_key) in context


async def test_file_delivery_guidance_forbids_local_path_links() -> None:
    surface = MemorySurface()
    config = RunConfig(
        surface=surface,
        runner=_runner(),
        prompt="send me the report",
    )

    context = await _build_system_context(config)

    assert "Discord cannot open local filesystem paths" in context
    assert "Never describe a local path as a clickable link" in context
    assert f".ccdb-attachments-{surface.thread_key}" in context


async def test_the_session_is_registered_under_the_surface_key() -> None:
    """The registry is how two sessions notice each other — a wrong key is a silent collision."""
    surface = MemorySurface()
    registry = SessionRegistry()
    config = RunConfig(
        surface=surface, runner=_runner(), prompt="scheduled work", registry=registry
    )

    await _build_system_context(config)

    assert surface.thread_key in {s.thread_id for s in registry.list_active()}


async def test_lounge_context_is_built_without_a_discord_thread() -> None:
    lounge_repo = MagicMock()
    lounge_repo.get_recent = AsyncMock(return_value=[])
    config = RunConfig(
        surface=MemorySurface(),
        runner=_runner(),
        prompt="scheduled work",
        lounge_repo=lounge_repo,
    )

    await _build_system_context(config)

    lounge_repo.get_recent.assert_awaited_once()


async def test_wait_guidance_appears_only_while_a_watcher_runs() -> None:
    from claude_discord import waits

    runner = _runner()
    runner.api_port = 8099
    config = RunConfig(surface=MemorySurface(), runner=runner, prompt="push and wait for CI")

    waits.register_watcher(None)
    assert "/api/waits" not in (await _build_system_context(config) or "")

    waits.register_watcher(MagicMock())
    try:
        assert "/api/waits" in (await _build_system_context(config) or "")
    finally:
        waits.register_watcher(None)


async def test_file_delivery_guidance_names_the_console() -> None:
    """A console conversation must not be told its files go to Discord."""
    surface = MemorySurface(frontend="console")
    config = RunConfig(surface=surface, runner=_runner(), prompt="send me the report")

    context = await _build_system_context(config)

    assert "Ebi AI Console cannot open local filesystem paths" in context
    assert "send files to Discord" not in context


async def test_console_thread_link_guidance_uses_verified_search_ids() -> None:
    config = RunConfig(surface=MemorySurface(), runner=_runner(), prompt="find earlier work")
    context = await _build_system_context(config)
    assert "[thread title](/#focus/t<thread_id>)" in context
    assert "/api/search?q=" in context
    assert "Never invent thread IDs" in context


async def test_delegation_guidance_preserves_preselected_child_ai() -> None:
    config = RunConfig(surface=MemorySurface(), runner=_runner(), prompt="delegate work")
    context = await _build_system_context(config)
    assert "parent_thread_id" in context
    assert "child AI preferences" in context
    assert "native subagents" in context


# --- Local customization: CCDB_LOUNGE_PROMPT_OFF -------------------------------


def _lounge_config(runner: MagicMock) -> tuple[RunConfig, MagicMock]:
    lounge_repo = MagicMock()
    lounge_repo.get_recent = AsyncMock(return_value=[])
    config = RunConfig(surface=MemorySurface(), runner=runner, prompt="hi", lounge_repo=lounge_repo)
    return config, lounge_repo


class PiRunner(MagicMock):
    """Class name is what _backend_name_from_runner keys on."""


async def test_lounge_prompt_on_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CCDB_LOUNGE_PROMPT_OFF", raising=False)
    config, repo = _lounge_config(_runner())
    assert "AI LOUNGE" in (await _build_system_context(config) or "")
    repo.get_recent.assert_awaited_once()


async def test_lounge_prompt_off_for_all(monkeypatch) -> None:
    monkeypatch.setenv("CCDB_LOUNGE_PROMPT_OFF", "all")
    config, repo = _lounge_config(_runner())
    assert "AI LOUNGE" not in (await _build_system_context(config) or "")
    repo.get_recent.assert_not_awaited()


async def test_lounge_prompt_off_only_for_listed_backend(monkeypatch) -> None:
    monkeypatch.setenv("CCDB_LOUNGE_PROMPT_OFF", "pi, codex")
    pi_runner = PiRunner()
    pi_runner.working_dir = "/tmp/example"
    pi_config, _ = _lounge_config(pi_runner)
    claude_config, _ = _lounge_config(_runner())
    assert "AI LOUNGE" not in (await _build_system_context(pi_config) or "")
    assert "AI LOUNGE" in (await _build_system_context(claude_config) or "")
