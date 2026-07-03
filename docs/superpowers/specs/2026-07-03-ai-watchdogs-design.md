# AI Watchdogs — Design Spec

**Date:** 2026-07-03
**Status:** Approved (simplified 2026-07-03 after critique — see "Design history" at bottom)

## Goal

Add automatic enforcement for the three AI mistakes that currently have no
mechanism catching them:

1. **Writes / destructive commands against production DB files** (vacation.db, etc.)
2. **Destructive git or shell commands without user confirmation** (`git push --force`, `rm -rf`, `git reset --hard`, `--no-verify`)
3. **Claiming "done / works / passes" without evidence of actually running the app**

Two of these can be done with plain deny rules in Claude Code's built-in
`permissions` system — six lines of JSON, zero maintenance. The third
(verification) genuinely needs a custom hook because it inspects my
end-of-turn message rather than a specific tool call.

Everything else on the original 10-persona wishlist was either redundant
with an existing superpower skill (e.g., Test Enforcer with
`test-driven-development`), duplicative of passive CLAUDE.md rules that are
already followed reliably, or too noisy to be net-positive
(pattern-matching for hedge words, hallucination detection). See "Design
history" for the full rationale.

## Decisions baked in

| Decision | Choice | Rejected alternative |
|---|---|---|
| Scope | Three mechanisms, not ten personas | Full 10-persona roster (too much overlap with existing skills, too much noise, too much maintenance) |
| DB Guardian mechanism | `permissions.deny` in `~/.claude/settings.json` | Custom shell hook with persona voice |
| Consent Cop mechanism | `permissions.deny` in `~/.claude/settings.json` | Custom shell hook with persona voice |
| Verifier mechanism | Custom `Stop` hook that spawns an LLM subagent | Deterministic grep (can't judge whether a claim was verified); skill-only (skill is opt-in and gets skipped) |
| Location | Global `~/.claude/` — always on, every project | Project-scoped |
| Voice / messaging | Claude Code's generic "permission denied" for deny rules; persona-flavored message for Verifier's LLM output | Custom persona voice for all three (not worth the code) |

## Mechanism 1 — DB Guardian (deny rules)

Add to `~/.claude/settings.json` under `permissions.deny`:

```json
"deny": [
  "Write(**/vacation.db)",
  "Write(**/*.sqlite)",
  "Write(**/*.sqlite3)",
  "Bash(rm * vacation.db*)",
  "Bash(rm * *.sqlite*)"
]
```

**What this blocks.** Any `Write` tool call whose target path matches
`vacation.db` in any project (or a `.sqlite` / `.sqlite3` file anywhere).
Any `Bash` command whose text matches `rm ... vacation.db*` or
`rm ... *.sqlite*`. Claude Code refuses the tool call before it runs and
shows a generic permission-denied message.

**What this deliberately does NOT block.** Read-only access to the DB
(`sqlite3 vacation.db ".tables"`, etc.). Your existing 359 allow-entries
for read queries stay intact.

**Adding a new project's DB.** When you start a new project with a different
DB name, add one deny rule per file. Static list, edited by hand. Fine while
you have 2–5 projects; if the list grows past that we can revisit.

**Explicit unblock.** If you ever legitimately need to write to
`vacation.db` from within Claude Code (unlikely — you should stop the app
and use `sqlite3` directly), you'd temporarily comment out the deny rule
and re-enable it after. This friction is the point.

## Mechanism 2 — Consent Cop (deny rules)

Add to `~/.claude/settings.json` under `permissions.deny`:

```json
"deny": [
  "Bash(rm -rf *)",
  "Bash(rm -fr *)",
  "Bash(git push --force*)",
  "Bash(git push -f*)",
  "Bash(git push --force-with-lease*)",
  "Bash(git reset --hard*)",
  "Bash(git checkout --*)",
  "Bash(git restore --*)",
  "Bash(git clean -f*)",
  "Bash(git branch -D*)",
  "Bash(*--no-verify*)",
  "Bash(*--no-gpg-sign*)"
]
```

**What this blocks.** Any Bash command containing the listed destructive
patterns. The commands are refused before execution. You (Jeff) can still
run them from your own shell — this only guards *me*.

**Why so many patterns.** `git push --force`, `-f`, and
`--force-with-lease` are three ways to say the same thing; the guard needs
all of them to be effective. Same for `rm -rf` vs. `rm -fr`. Deny rules
are literal string matches, not semantic.

**What this deliberately does NOT block.** Non-destructive git operations
(commit, push without force, checkout to a branch), non-recursive `rm`,
normal test-suite invocations. Also NOT blocked: you asking me to run one
of these explicitly — deny rules don't have an "unless the user just said
so" branch. If you ever explicitly ask me to force-push, we deal with it
by editing the deny list temporarily.

## Mechanism 3 — Verifier (custom Stop hook)

The one that needs a real hook. Fires on `Stop` (end of my turn), inspects
my final message, decides whether I claimed "done" without evidence.

### Trigger

Registered in `~/.claude/settings.json` under `hooks.Stop`:

```json
"Stop": [
  {
    "matcher": "",
    "hooks": [{"type": "command", "command": "~/.claude/hooks/verifier.sh"}]
  }
]
```

### Flow

1. `verifier.sh` receives JSON on stdin with (at minimum) the transcript
   of the finishing turn. Confirms via schema check when we build it.
2. Short-circuit: if the turn had no code edits (no `Edit`, `Write`, or
   code-relevant `Bash` calls), exit `0` silently. Pure conversation turns
   cost zero.
3. If the turn DID touch code, spawn a Haiku 4.5 subagent (via
   `~/.claude/agents/verifier.md`) with:
   - My final assistant message
   - A summary of tool calls made this turn (types + counts, not full
     content)
   - The specific prompt: "Did the assistant claim the work is complete
     (`done`, `works`, `passes`, `should work`, `ready`) without evidence
     it actually ran? Evidence means calling a `preview_*` tool,
     `curl`ing the local dev server, or reading test output. Answer
     JSON: `{claimed_done: bool, has_evidence: bool, message: string}`."
4. If `claimed_done && !has_evidence`, exit `2` with the subagent's
   `message` on stderr. That injects the finding into my context; I
   have to address it in the next turn (auto-fix: actually run the
   check; or explain if the finding is a false positive).

### Subagent definition

`~/.claude/agents/verifier.md` — a standard Claude Code subagent
definition with:
- Model: `claude-haiku-4-5-20251001`
- System prompt: character-flavored ("You are the Verifier — a skeptical
  QA reviewer. Your only job is to catch claims of completion that
  weren't backed by verification.")
- Tool access: none (it's a judgment call, no tool use needed)
- Output constraint: JSON schema for the response above

### Cost

Fires once per code-touching turn. Input: ~500–1500 tokens (final message
+ tool-call summary + system prompt). Output: ~100 tokens (short JSON).
At Haiku 4.5 pricing, ~$0.003–$0.008 per turn. Fifty code-touching turns
per day ≈ $0.15–$0.40/day.

## File layout

```
~/.claude/
├── settings.json                       ← EDIT: add deny rules + Stop hook registration
├── hooks/
│   ├── block-cd-prefix-bash.sh         ← existing; unchanged
│   ├── check-plan-size.sh              ← existing; unchanged
│   └── verifier.sh                     ← NEW: shell wrapper that spawns the subagent
├── agents/
│   └── verifier.md                     ← NEW: subagent definition
└── (no config file, no shared library, no watchdog directory)

~/Projects/Vacation Planner/            ← unchanged. Nothing project-local.
```

Two new files (`verifier.sh`, `verifier.md`) plus the JSON edit. That's the
whole system.

## Testing strategy

**Deny rules** need no automated test — they're declarative JSON. Manual
smoke test after adding them: attempt a `Bash(rm -rf /tmp/x)` in a scratch
directory, confirm it's blocked. Attempt a benign `Bash(rm /tmp/x)`,
confirm it goes through.

**Verifier** gets a small test file at
`~/.claude/hooks/tests/test_verifier.sh` that:
1. Feeds `verifier.sh` a fake Stop-hook JSON with a "no code edits" turn.
   Asserts exit 0, no stderr.
2. Feeds it a "code edits + no verification claim" turn. Asserts exit 0.
3. Feeds it a "code edits + verification claim + no browser tool call".
   Asserts exit 2 with a persona-flavored message on stderr.

The subagent call itself is not unit-tested — it's an LLM. But the shell
wrapper's short-circuit logic, JSON parsing, and exit-code discipline
absolutely are.

## Non-goals

- **Persona voice for the deny-rule mechanisms.** Claude Code's generic
  "permission denied" message is enough. Adding a shell hook just to
  reformat the message is not worth the maintenance.
- **Cross-machine sync.** Global here means "this laptop." If you use
  Claude Code on another machine, the deny rules and hook don't follow.
  That's inherent to `~/.claude/settings.json`.
- **The other seven personas from the original design.** Scope Cop, Rule
  Keeper, Test Enforcer, Cleanup Auditor, Hallucination Hunter, Plan
  Deputy, Hedge Detector — all cut. See "Design history" for reasoning.
- **Cross-turn state.** Verifier evaluates each turn on its own. No
  streak counters, no history.
- **Auto-fix beyond the Verifier's own domain.** The Verifier surfaces a
  finding to my context; my in-session response is whatever the finding
  prompts. No separate "fixer" agent.

## Open questions for the implementation plan

1. **How exactly to invoke a Claude Code subagent headlessly from a
   shell script.** Options: `claude -p --agent verifier`, direct
   Anthropic API call from within the shell, Claude Code SDK. Plan phase
   validates.
2. **What JSON does Claude Code actually pass to a Stop hook?** Need to
   confirm the transcript is available and how much of it. If not
   available, the wrapper reads recent git status / diff as a proxy.
3. **How to detect "code-touching turn" from the JSON.** Grep tool-call
   names for `Edit|Write|Bash` and Bash content for common code-run
   commands (`pytest`, `flask`, `python`, etc.). Concrete list decided
   in plan phase.
4. **Whether the block-cd-prefix-bash.sh hook can be replaced with a
   deny rule.** Likely yes — `"Bash(cd * &&*)"`. If so, we drop one of
   the two existing custom hooks and consolidate.

## Design history

Original design (2026-07-03 morning) proposed 10 watchdog personas — each
with a character voice, one per common AI mistake, mixing deterministic
shell scripts with LLM subagents.

Critical review during the design conversation identified two problems:

1. **Redundancy with existing superpower skills.** Test Enforcer overlaps
   with `superpowers:test-driven-development`. Hedge Detector overlaps
   with `superpowers:verification-before-completion` (which targets the
   root cause — unverified claims — rather than the surface symptom of
   hedge language). Rule Keeper duplicates CLAUDE.md's already-followed
   rules.

2. **False-positive risk from pattern-matching semantic mistakes.**
   Hallucination Hunter (grep for referenced symbols) would fire on
   every legitimate cross-file import. Scope Cop's LLM judgment on
   "does the diff match the ask" is exactly the call you (the user)
   make best by looking. Plan Deputy would false-positive on legitimate
   detours.

3. **Enforcement gap actually confirmed for three mistakes:** DB safety,
   destructive commands, and unverified completion claims. Everything
   else on the roster either has a documented right answer already
   (skill) or catches things that basically don't happen.

4. **Simpler-than-hooks alternative for two of the three:** Claude Code's
   built-in `permissions.deny` mechanism can block tool calls directly,
   without custom shell scripts. Verified via inspection of the user's
   current `settings.json` — zero deny rules exist today. Six lines of
   JSON replaces the DB Guardian and Consent Cop hooks entirely.

The simplified design ships the three mechanisms that survive the
scrutiny. If, after living with them for a month, real recurring mistakes
appear that aren't caught, we revisit — likely one persona at a time,
with the concrete failure mode as justification.
