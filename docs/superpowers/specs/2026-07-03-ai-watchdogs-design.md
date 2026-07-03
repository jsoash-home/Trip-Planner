# AI Watchdogs — Design Spec

**Date:** 2026-07-03
**Status:** Approved (defaults chosen by user 2026-07-03)

## Goal

Build a set of always-running background "watchdog personas" that catch the AI
(Claude Code) making common mistakes before those mistakes land in the repo.
Ten personas total, each with one job and one voice. Watchdogs fire from
Claude Code hooks — deterministic shell scripts for pattern-matchable
mistakes, LLM-backed subagents for mistakes that need judgment.

The design is scoped for the user (a beginner learning to code) with mostly
Python/Flask projects that follow the layout in `~/.claude/CLAUDE.md`.
Watchdogs live globally in `~/.claude/` so they protect every project, not
just Vacation Planner.

## Decisions baked in

| Decision | Choice | Rejected alternative |
|---|---|---|
| Trigger timing | Claude Code hooks (fire on tool events) | End-of-session review; scheduled cron |
| Deterministic vs LLM | Hybrid — seven deterministic, three LLM | All-deterministic (misses semantic mistakes); all-LLM (too slow, too expensive) |
| LLM subagent shape | Three separate subagents in parallel on `Stop` hook | One combined judgment (blurs voices); sequential panel (too slow) |
| Nag response policy | Auto-fix if I can, else explain in same turn | Ask user first (too slow); log-only (too quiet) |
| Scope | All global (`~/.claude/`) | Project-scoped watchdogs per project |
| Persona voice format | `[Persona Name] <message>`, plain text, no emoji | Emoji prefix (violates global CLAUDE.md preference) |
| DB protection | Convention-based defaults + optional per-project override | Hardcoded per-project list; user-must-configure |

## Persona roster

Ten watchdogs, grouped by trigger type.

### Deterministic (shell scripts — fast, free)

| # | Persona | Watches for | Hook event | Action |
|---|---|---|---|---|
| 1 | **DB Guardian** | Writes and destructive commands touching production DB files (`*.db`, `*.sqlite`, `*.sqlite3` at project root, > 24 hours old) | `PreToolUse` on Bash + Write | **Block** |
| 2 | **Rule Keeper** | Violations of concrete CLAUDE.md rules — `cd X &&` compound, `except Exception: pass`, `print()` where `logger` is expected, adding comments where surrounding file has none, `.py` at project root that isn't an allowed entry point | `PreToolUse` on Bash + Write + Edit | **Block** for hard rules (existing `cd`), **nag** for softer ones |
| 3 | **Consent Cop** | Destructive commands about to fire without user OK — `git push --force`, `rm -rf`, `git reset --hard`, `--no-verify`, `--no-gpg-sign`, `git checkout -- <path>` | `PreToolUse` on Bash | **Block** |
| 4 | **Hallucination Hunter** | Edits that reference a function, import, Flask route, template, or file that doesn't exist elsewhere in the repo | `PostToolUse` on Edit + Write | **Nag** |
| 5 | **Test Enforcer** | New function added to `src/*.py` with no matching test in `tests/test_<module>.py` (violates global "at least one test per pure function" rule) | `PostToolUse` on Edit + Write | **Nag** |
| 6 | **Cleanup Auditor** | Files placed at project root that aren't allowed entry points (`main.py`, `app.py`) — scratch files, `foo_v2.py`, backup copies | `PreToolUse` on Write | **Block** |
| 7 | **Hedge Detector** | Weasel words in my final message: `should work`, `probably`, `in most cases`, `usually`, `I think` (except in explicit hedging contexts) | `Stop` (end of turn) | **Nag** |

### LLM subagents (fire on `Stop` only — one call per turn each)

| # | Persona | Watches for | Model | Reads |
|---|---|---|---|---|
| 8 | **Scope Cop** | Diff vs. ask mismatch — one-line ask, 90-line diff; bugfix ask, refactor diff; edits to files outside the sketched scope | Haiku 4.5 | Last user message + git diff since that turn |
| 9 | **Verifier** | Claimed "done / works / passes / ready" without evidence — no `preview_*` tool call, no `curl localhost:*`, no browser check | Haiku 4.5 | My final message + tool-call log this turn |
| 10 | **Plan Deputy** | When active plan file exists, watches that my edits track the plan's task order; catches me improvising off-plan | Haiku 4.5 | Active plan file + current diff |

## Trigger mechanism

Claude Code emits hook events on tool calls. Each event passes JSON to the
hook script on stdin (tool name, arguments, cwd). Hook script exits with a
code — `0` = allow / continue, `2` = block / show message to Claude.

**Event → watchdog mapping:**

- `PreToolUse` (Bash) → DB Guardian, Rule Keeper (`cd &&`), Consent Cop
- `PreToolUse` (Edit / Write) → Rule Keeper (comment rules, forbidden patterns), DB Guardian (Write to protected DB), Cleanup Auditor (root-file rules)
- `PostToolUse` (Edit / Write) → Hallucination Hunter, Test Enforcer
- `Stop` → Hedge Detector (deterministic), Scope Cop / Verifier / Plan Deputy (LLM subagents in parallel)

**Stop hook fan-out.** A single shell script (`hooks/watchdogs/stop_dispatcher.sh`)
runs on `Stop`. It short-circuits when the turn had no code changes (no Edit,
Write, or code-relevant Bash calls) — pure conversation turns cost zero. When
code did change, it:

1. Runs Hedge Detector inline (deterministic grep on the final message).
2. Spawns Scope Cop and Verifier as parallel LLM subagents.
3. Spawns Plan Deputy only if `docs/superpowers/plans/*.md` contains a plan
   with `status: active` (or equivalent marker — decided at plan phase).

All three LLM subagents run concurrently. Wall-clock per turn: ~2–4s.
Estimated token cost per turn: $0.02–$0.05 with Haiku 4.5.

## Response policy

Two mechanics.

**Block-style** (DB Guardian, Consent Cop, hard rules in Rule Keeper,
Cleanup Auditor for root files). The `PreToolUse` hook exits 2 with a
persona message on stderr. Claude Code refuses the tool call. I have to
route around it — usually by asking the user.

**Nag-style** (all other watchdogs). Hook exits 2 with a persona message on
stderr. The tool call has already run (or the turn is ending) but the
finding is now injected into my context. I MUST address it in the same turn:

- **Auto-fix if I can** — Verifier flags "no verification"? I run the
  browser check now. Test Enforcer flags "no test"? I write the test.
  Scope Cop flags "you touched extra files"? I revert or justify inline.
- **Explain if I can't** — Sometimes the finding is a false positive
  (Hallucination Hunter can't find `format_money` because it's imported
  from `src/currency.py` and the grep missed it). I explain in my reply
  and continue.

Watchdog findings never persist across turns. Each turn is fresh.

## Persona message format

Every watchdog message starts with `[Persona Name]` in brackets, plain text,
no emoji. Scannable in the transcript. Examples:

```
[DB Guardian] Refused: rm command references vacation.db. This is your
production database. Ask Jeff first. Command not run.

[Test Enforcer] New function `format_money_range` in src/currency.py has
no matching test in tests/test_currency.py. Write one before you claim
this task is done.

[Scope Cop] The user asked for "a one-line fix to format_money". The diff
touches 4 files (currency.py, budget.py, templates/budget.html,
tests/test_currency.py) and adds a new helper `_split_amounts`. Justify
the scope or revert the extras.

[Verifier] You said "should work now" but you didn't call any preview_*
tool and didn't curl localhost:5002 this turn. Load the page in the
browser and confirm before saying you're done.
```

Character voice is a persona attribute — set in the subagent's system
prompt (for LLM personas) or in the shell script's stderr templates (for
deterministic personas).

## File layout

```
~/.claude/
├── hooks/
│   ├── block-cd-prefix-bash.sh           ← existing; folded into rule_keeper.sh
│   ├── check-plan-size.sh                 ← existing; kept as-is
│   └── watchdogs/                         ← NEW
│       ├── _lib.sh                        ← shared: persona formatter, exit codes, git-diff helpers, JSON-stdin parser
│       ├── rule_keeper.sh
│       ├── consent_cop.sh
│       ├── db_guardian.sh
│       ├── hallucination_hunter.sh
│       ├── test_enforcer.sh
│       ├── cleanup_auditor.sh
│       ├── hedge_detector.sh
│       ├── stop_dispatcher.sh             ← runs on Stop; fans out to Hedge Detector + LLM subagents
│       └── tests/
│           ├── test_rule_keeper.sh
│           ├── test_consent_cop.sh
│           ├── test_db_guardian.sh
│           ├── test_hallucination_hunter.sh
│           ├── test_test_enforcer.sh
│           ├── test_cleanup_auditor.sh
│           ├── test_hedge_detector.sh
│           └── run_all.sh                 ← runs every watchdog test
├── agents/                                ← NEW: LLM personas as subagent definitions
│   ├── verifier.md
│   ├── scope_cop.md
│   └── plan_deputy.md
├── watchdog-config.yaml                    ← NEW: optional per-project overrides (see below)
└── settings.json                           ← existing; add hook registrations
```

**Nothing new lives in any project's `.claude/`.** All watchdogs are global.

## DB Guardian specifics

DB Guardian needs to know which files to protect per project. Two-layer
resolution — convention first, config override second.

**Convention (default rule).** Block writes and destructive commands
against any file at the current project root matching:
- `*.db`, `*.sqlite`, `*.sqlite3`
- File exists and is > 24 hours old (skips test artifacts, mid-session
  scratch DBs)

Also always block:
- Any write to `.env` in a git-tracked location
- `db.create_all()`, `db.drop_all()` invocations in ad-hoc scripts (grep
  the command text)

**Override config** — `~/.claude/watchdog-config.yaml`:

```yaml
db_guardian:
  # Project-specific protected paths (absolute). Everything here is always blocked
  # regardless of the 24-hour rule.
  protected_paths:
    - /Users/jeff_s/Projects/Vacation Planner/vacation.db
    - /Users/jeff_s/Projects/stock-tracker/stocks.db
  # Paths to explicitly exempt (e.g., test fixtures that live outside `tests/`).
  exempt_paths: []

test_enforcer:
  # Projects where test enforcement is off (e.g., pure-JS project without pytest).
  disabled_projects: []
```

Config is optional. If absent, convention rules apply.

## Testing strategy

Every watchdog script has a companion test in
`~/.claude/hooks/watchdogs/tests/test_<persona>.sh`. Tests feed the script
fake JSON on stdin and assert:

1. Correct exit code (`0` = allow, `2` = block/nag)
2. Correct persona-formatted stderr
3. Silence on inputs that should not trigger

Tests use plain `bash` — no test framework dependency. `run_all.sh` runs
every test and returns non-zero if any fail. Wire it into a manual sanity
check (not a git hook) so a broken watchdog is caught before it silently
allows a mistake through.

LLM subagents (verifier, scope_cop, plan_deputy) are tested by:
1. Unit-ish: the shell wrapper that spawns them has a test that mocks
   `claude -p` and asserts the wrapper handled JSON correctly.
2. Manual: a handful of golden-transcript fixtures under
   `~/.claude/hooks/watchdogs/tests/fixtures/` that the developer can
   run the subagent against and eyeball the response.

Full end-to-end LLM tests are out of scope for v1 — they're expensive and
brittle. Deterministic wrappers are what we can rely on for regression.

## Non-goals

Things this design explicitly does NOT cover:

- **Watchdogs that fire outside Claude Code sessions.** No cron agents,
  no CI-side reviewers, no post-commit git hooks. If you want those later,
  they're a separate design.
- **Language coverage beyond Python.** Test Enforcer and Hallucination
  Hunter check Python conventions. JS/TS projects get a no-op until we
  teach the watchdogs new rules.
- **Watchdogs that read old commits.** Findings are always about the
  current turn. No "you added dead code three commits ago" retroactive
  nags.
- **User-facing UI.** Findings surface in the Claude Code transcript
  (via stderr) and nowhere else. No dashboard, no log viewer, no
  notification.
- **Cross-turn state.** Each turn starts fresh. No "you've been off-plan
  for 4 turns" streak counter. Plan Deputy re-evaluates from the plan
  file each time.

## Open questions for the implementation plan

Things the plan phase should decide, not the design phase:

1. **How exactly to invoke a Claude Code subagent from a hook script.**
   `claude -p --agent verifier` vs. Anthropic API direct call vs.
   Claude Code SDK. Whichever works reliably headless.
2. **Where to source the "last user message" and "diff since last user
   turn"** — Claude Code may pass this to the Stop hook via stdin JSON;
   need to confirm and fall back to git if not.
3. **Rule Keeper's rule schema.** Which rules block vs. nag. Concrete
   list of patterns to grep for (proposed set is in this doc; plan can
   refine).
4. **Migration path for the two existing hooks** (`block-cd-prefix-bash.sh`,
   `check-plan-size.sh`). Fold into new watchdog files or keep alongside.
5. **Phasing the build.** Ten personas is a lot. Plan should order them
   by highest-value-per-effort — likely: Consent Cop + DB Guardian + Rule
   Keeper first (all deterministic, high blast-radius protection), then
   the LLM three (Verifier + Scope Cop + Plan Deputy), then the polish
   personas.
