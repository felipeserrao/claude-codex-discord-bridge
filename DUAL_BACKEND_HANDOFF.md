# Dual Backend Handoff

This document supplements `DUAL_BACKEND_PLAN.md`.

`DUAL_BACKEND_PLAN.md` remains the strategy document.
This file is the execution handoff: what has actually landed, what still
remains, and what should happen next.

## Current Verdict

The core P0 chat path is now backend-aware.

Important:

- Backend persistence exists.
- A minimal `CodexRunner` exists.
- Shared code now has a backend/runner abstraction.
- New sessions can now start on either `claude` or `codex`.
- Thread replies now choose the runner from the stored session backend.
- Startup resume now chooses the runner from the stored session backend.

The repo is still not fully dual-backend complete.

What remains is mostly:

- gating unsupported Codex commands/features
- suppressing Claude-only helper behavior on Codex runs
- deciding whether non-chat runner consumers should stay Claude-only or become backend-aware
- documentation/config cleanup

## What Was Implemented

### 1. Backend metadata is now stored in the session DB

Implemented:

- `sessions.backend TEXT NOT NULL DEFAULT 'claude'`
- migration/backfill for legacy rows
- `SessionRecord.backend`
- `SessionRepository.save(..., backend=...)`

Files:

- `claude_discord/database/models.py`
- `claude_discord/database/repository.py`

Result:

- Existing rows are treated as `claude`
- New rows can persist `claude` or `codex`

### 2. Shared backend primitives were added

Implemented:

- `BackendKind`
- `DEFAULT_BACKEND`
- `normalize_backend()`
- `build_resume_command()`

File:

- `claude_discord/backends.py`

Result:

- shared code can refer to backends without hardcoding Claude everywhere
- `/resume-info` can render the correct provider-specific resume command

### 3. Runner abstraction was introduced

Implemented:

- `AgentRunner` protocol
- shared type signatures updated from `ClaudeRunner` to `AgentRunner` in the key seams

Files:

- `claude_discord/protocols.py`
- `claude_discord/cogs/run_config.py`
- `claude_discord/discord_ui/views.py`
- `claude_discord/cogs/skill_command.py`
- `claude_discord/cogs/scheduler.py`
- `claude_discord/cogs/webhook_trigger.py`
- `claude_discord/setup.py`

Result:

- the codebase no longer requires every backend-aware seam to name `ClaudeRunner` directly
- Claude still fits the protocol
- Codex now also fits the protocol

### 4. Run config and event persistence are backend-aware

Implemented:

- `RunConfig.backend`
- `EventProcessor` saves `backend` when persisting session records

Files:

- `claude_discord/cogs/run_config.py`
- `claude_discord/cogs/event_processor.py`

Result:

- once a run is started with a backend, that backend can be saved with the session row

### 5. Provider-aware `/resume-info`

Implemented:

- Claude sessions show `claude --resume <id>`
- Codex sessions show `codex exec resume <id>`

File:

- `claude_discord/cogs/session_manage.py`

Result:

- persisted backend now affects a user-visible command

### 6. Minimal `CodexRunner` was added

Implemented:

- `claude_discord/codex/runner.py`
- export in `claude_discord/codex/__init__.py`
- export in `claude_discord/__init__.py`

Behavior:

- starts Codex with `codex exec --json`
- resumes with `codex exec resume --json`
- sends prompt via stdin
- supports `--output-last-message`
- translates:
  - `thread.started` -> shared `SYSTEM`
  - `turn.failed` -> shared terminal `RESULT` error
  - success -> shared terminal `RESULT` text

Notes:

- v1 implementation is intentionally thin
- no partial text streaming yet
- no tool/permission/elicitation translation yet
- `inject_tool_result()` is a no-op for Codex v1

Files:

- `claude_discord/codex/runner.py`
- `claude_discord/codex/__init__.py`

### 7. Backend-aware runner lookup and default backend wiring

Implemented:

- `ClaudeChatCog(..., runners=..., default_backend=...)`
- runner lookup via backend inside `ClaudeChatCog`
- `setup_bridge()` now builds a runner registry instead of assuming one concrete runner
- `setup_bridge()` auto-registers a builtin `CodexRunner`
- `CCDB_DEFAULT_BACKEND` env for message-based default backend

Files:

- `claude_discord/setup.py`
- `claude_discord/cogs/claude_chat.py`

Result:

- consumer code can keep calling `setup_bridge()` once
- the main chat path no longer needs custom wiring to reach Codex
- no repo-wide rename or invasive rewrite was needed

Note:

- `main.py` still instantiates only the base Claude runner directly, but this is
  no longer a blocker because `setup_bridge()` now creates/registers the Codex
  runner automatically

### 8. Real backend selection and backend-driven routing now exist for the main chat path

Implemented:

- explicit `/session backend:{claude|codex} prompt:<text>` command
- normal message-based new sessions use the configured default backend
- `_run_claude()` now clones the runner selected for that backend
- thread replies choose backend from `SessionRecord.backend`
- startup resume chooses backend from `SessionRecord.backend`
- startup resume also carries stored `working_dir` when available
- `/resume` now forwards `record.backend` into `spawn_session()`
- `/fork` now also forwards the stored backend into `spawn_session()`

Files:

- `claude_discord/cogs/claude_chat.py`
- `claude_discord/discord_ui/views.py`

Result:

- the core Discord chat lifecycle is now backend-correct end-to-end:
  - new session
  - session persistence
  - reply in thread
  - restart + resume

### 9. Regression coverage was added for the P0 routing slice

Added tests for:

- default-backend new sessions
- explicit `/session` backend override
- backend-aware thread replies
- backend-aware startup resume
- backend-aware `/resume` spawn path
- setup-time runner registry/default backend wiring
- programmatic `spawn_session()` using the configured default backend

Files:

- `tests/test_claude_chat.py`
- `tests/test_resume_command.py`
- `tests/test_setup.py`

Result:

- the new routing behavior now has targeted unit coverage

### 10. Discord backend-selection UX is now implemented

Implemented:

- persisted default backend stored in the shared `settings` table
- `/backend-show` to display the current default backend
- `/backend-set backend:{claude|codex}` to change the default backend from Discord
- short explicit launch commands:
  - `/claude prompt:<text>`
  - `/codex prompt:<text>`
- message-started new sessions and `spawn_session()` now resolve the default
  backend from settings first, then fall back to env/config
- existing `/session backend:{claude|codex} prompt:<text>` remains available

Files:

- `claude_discord/database/settings_repo.py`
- `claude_discord/cogs/session_manage.py`
- `claude_discord/cogs/claude_chat.py`
- `tests/test_settings_repo.py`
- `tests/test_session_manage.py`
- `tests/test_claude_chat.py`

Result:

- backend choice is now user-manageable from Discord instead of env-only
- env/config remains only the fallback boot-time source
- stored-backend reply/resume behavior stays unchanged

## Validation In This Session

Confirmed locally:

- `python3 -m compileall claude_discord/database/settings_repo.py claude_discord/cogs/session_manage.py claude_discord/cogs/claude_chat.py tests/test_settings_repo.py tests/test_session_manage.py tests/test_claude_chat.py`
- `git diff --check -- claude_discord/database/settings_repo.py claude_discord/cogs/session_manage.py claude_discord/cogs/claude_chat.py tests/test_settings_repo.py tests/test_session_manage.py tests/test_claude_chat.py`

Not run in this workspace:

- `pytest`
- `ruff`

Reason:

- this workspace did not have `uv`, `pytest`, or `ruff` available

## Machine Setup Status (2026-04-15 to 2026-04-16)

An isolated second bot instance was also stood up on the target machine for
real Discord testing of the Codex path.

Created:

- env file: `.env.test-codex`
- systemd unit: `discord-bot-test-codex.service`
- helper script: `setup_test_codex_bot.sh`

Current test-instance shape:

- separate Discord bot token
- separate systemd service name
- separate clone/workdir: `/home/ubuntu/claude-codex-discord-bridge`
- separate runtime DB/data under this clone's `data/`
- default backend set to `codex`
- mention-only behavior enabled for the configured test channel

Important runtime fixes made during setup:

- pinned `CCDB_UV_BIN=/home/ubuntu/.local/bin/uv` so `pre-start.sh` works under
  systemd
- `NotificationRepository.init_db()` now creates the parent directory before
  opening SQLite, fixing `sqlite3.OperationalError: unable to open database file`
- `scripts/cleanup_worktrees.sh` no longer hardcodes `/home/ebi/...`; it now
  derives the repo root dynamically from the script location
- the Codex test instance now uses an absolute binary path:
  `/home/ubuntu/.npm-global/bin/codex`
  because systemd did not inherit the interactive shell `PATH`
- Codex test env was switched to dangerous/full-access mode for real repo work:
  - `CODEX_DANGEROUSLY_SKIP_PERMISSIONS=true`
  - `CODEX_SANDBOX_MODE=danger-full-access`

Important Codex UX/runtime fixes made after live Discord testing:

- Codex resume argv ordering was fixed so exec-level flags like `--cd` appear
  before the `resume` subcommand
- backend-aware session-start and completion wording was added so Codex threads
  no longer present themselves as Claude threads
- Codex final-message handling now falls back to assistant text parsed from the
  JSON event stream when `--output-last-message` is empty, instead of emitting
  `Codex completed without a final message`

Current known operational blockers outside the core code path:

- the original production bot is still watching the same Discord test channel on
  the target machine, so both bots can answer in the same thread
- this is not caused by the dual-backend code itself; it is an operator/channel
  isolation issue
- if the original bot must remain untouched, the test bot should move to a
  different Discord channel that the original bot does not monitor

Current machine-level follow-up order:

- keep the test bot on an isolated Discord channel
- verify local branch/git behavior inside the intended working repo
- verify GitHub/fork/auth/network behavior for Codex in that environment

## Production-Readiness Next Steps

Given the work completed so far, the next steps to move this toward a
production-ready dual-backend release are:

### 1. Finish the Codex v1 product boundary

The core chat path works, but unsupported or Claude-specific features still
need explicit policy and UX.

Next work:

- design and implement mid-conversation backend switching in the same thread
  so a thread can move from Claude to Codex or from Codex to Claude without
  forcing the user to start a new thread
- gate `/rewind` for Codex threads with a clear unsupported-in-v1 response
- gate or redesign `/fork` for Codex threads
- gate `/sync-sessions` for Codex until a Codex-native session-storage story
  exists
- audit Claude-only helper flows in `EventProcessor` and skip or replace them
  for Codex runs
- decide whether `SkillCommandCog`, `SchedulerCog`, and `WebhookTriggerCog`
  remain Claude-only in v1 or become backend-aware

Why this matters:

- users may need to continue the same Discord thread after provider quota,
  outage, or policy issues on one backend
- the current v1 behavior is backend-sticky per thread/session, which is
  implementation-simple but operationally limiting

### 2. Verify and harden branch/git/GitHub behavior

The next end-to-end validation should happen in the actual target working repo,
not only in the bridge repo.

Minimum validation:

- verify local git works inside the configured Codex working directory
- verify branch create/switch flows work reliably
- verify remote visibility via `git remote -v`
- verify GitHub auth availability (`gh` or git credential path)
- verify whether the Codex subprocess has the outbound network needed for
  fork/push/PR operations

Why this matters:

- local repo work may succeed while fork/push/PR flows still fail
- production readiness for repo work is not proven until both local git and
  GitHub-connected operations are validated

### 3. Harden the runtime and service behavior

Live machine testing exposed the operational edges that should be tightened
before calling this production-ready.

Next work:

- keep absolute binary paths where systemd `PATH` differences matter
- verify the intended working repo exists and is accessible before startup
- add startup/smoke validation for the configured backend binary and working dir
- verify restart behavior: service restart, reconnect, session resume, and no
  DB collisions
- make backend/working-dir failures easy to diagnose from journald logs

### 4. Update operator-facing docs

The implementation is now ahead of the operator documentation.

Next work:

- document the backend-related env/config surface in `.env.example` and README
- document `CCDB_DEFAULT_BACKEND`
- document Codex-specific settings:
  - `CODEX_COMMAND`
  - `CODEX_MODEL`
  - `CODEX_PERMISSION_MODE`
  - `CODEX_WORKING_DIR`
  - `CODEX_DANGEROUSLY_SKIP_PERMISSIONS`
  - `CODEX_SANDBOX_MODE`
- document what Codex supports in v1 and what is intentionally unsupported
- document how to stand up a second isolated bot instance for testing

## What Is Still Missing

### 1. Unsupported Codex-only commands still need gating

Still missing:

- `/rewind` guard for Codex
- `/fork` guard or real Codex fork semantics
- `/sync-sessions` guard/policy for Codex

Why this matters:

- `/rewind` still assumes Claude JSONL layout
- `/fork` now preserves backend correctly, but Codex does not yet implement the
  same semantics as Claude's fork flow in this code path
- `/sync-sessions` is still fundamentally Claude-storage-specific

### 2. Claude-only helper behavior still needs provider gating

Still missing:

- `EventProcessor` statusline/footer behavior is still Claude-oriented
- thread inbox classification still assumes the Claude-style helper path

Already improved:

- auto thread rename is now effectively limited to Claude-started sessions in the
  main message-start path

Why this matters:

- the main chat runner selection is fixed, but some post-processing still assumes
  Claude-specific surrounding features

### 3. Dual-backend support is still centered on the main chat path

Still missing or undecided:

- `SkillCommandCog` still uses a single runner
- `SchedulerCog` still uses a single runner
- `WebhookTriggerCog` still uses a single runner

Why this matters:

- the just-finished P0 slice fixed the human chat path first
- other runner consumers may need a later decision:
  - remain Claude-only in v1
  - or become backend-aware in a later slice

### 4. Docs/config cleanup still remains

Still missing:

- document the new backend-related env/config surface
- update operator-facing docs/examples as needed

Relevant config currently read in code:

- `CCDB_DEFAULT_BACKEND`
- `CODEX_COMMAND`
- `CODEX_MODEL`
- `CODEX_PERMISSION_MODE`
- `CODEX_WORKING_DIR`
- `CODEX_DANGEROUSLY_SKIP_PERMISSIONS`
- `CODEX_SANDBOX_MODE`

## P0 Status

The original P0 from the previous handoff is done for the main chat path.

Shipped:

- configurable default backend: `claude` or `codex`
- explicit new-session backend choice
- persistence of chosen backend at session start
- reply-in-thread uses stored backend automatically
- startup resume uses stored backend automatically

This was the required blocker before doing any other Codex feature work.

Important:

- the Discord UX for choosing/changing the backend is now in place
- follow-up work should focus on gating unsupported Codex-only behavior

## Recommended Next Implementation Order

### Step 1. Gate unsupported Codex commands first

Suggested files:

- `claude_discord/cogs/claude_chat.py`
- `claude_discord/cogs/session_manage.py`
- `claude_discord/cogs/session_sync.py`

Target behavior:

- Codex threads should get a clear "unsupported in v1" response for `/rewind`
- Codex threads should get a clear "unsupported in v1" response for `/fork`
- Codex-specific `/sync-sessions` should be blocked or hidden until explicitly designed

### Step 2. Gate Claude-only helper flows during Codex runs

Suggested files:

- `claude_discord/cogs/event_processor.py`

Target behavior:

- skip or replace Claude-only statusline/footer behavior for Codex
- skip or replace Claude-only inbox classification behavior for Codex

### Step 3. Decide the policy for non-chat runner consumers

Suggested files:

- `claude_discord/cogs/skill_command.py`
- `claude_discord/cogs/scheduler.py`
- `claude_discord/cogs/webhook_trigger.py`

Target decision:

- either explicitly keep them Claude-only for v1
- or add backend-aware runner lookup there in a later slice

### Step 4. Update docs/examples/config references

Suggested files:

- `README.md`
- `.env.example`
- any operator-facing docs that describe startup config

Target behavior:

- operators should know how to select a default backend
- operators should know how to configure the Codex runner
