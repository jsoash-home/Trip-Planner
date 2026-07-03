# AI Watchdogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three enforcement mechanisms — Cerberus (DB Guardian deny rules), Sarge (Consent Cop deny rules), and Sherlock (Verifier Stop hook) — into `~/.claude/` so every future Claude Code session gets automatic protection against DB writes, destructive commands, and unverified completion claims.

**Architecture:** Cerberus and Sarge are `permissions.deny` entries in `~/.claude/settings.json` — declarative, zero runtime, no shell scripting. Sherlock is a small POSIX shell wrapper (`~/.claude/hooks/sherlock.sh`) invoked on the `Stop` hook event; it checks a kill-switch marker, short-circuits pure-conversation turns, and calls the Anthropic Messages API directly via `curl` with a system prompt loaded from `~/.claude/agents/sherlock.md`. Direct API is chosen over `claude -p --agent` to avoid CLI-recursion and auth-mode uncertainty.

**Tech Stack:** JSON, POSIX shell (`sh`, not `bash`-specific), `jq` for JSON parsing on stdin, `curl` for the Anthropic API call.

**Reference spec:** [docs/superpowers/specs/2026-07-03-ai-watchdogs-design.md](../specs/2026-07-03-ai-watchdogs-design.md)

**Progress-tracking note:** This plan modifies files under `~/.claude/`, which is not typically a git repo. There is no "commit after task" step for those files — progress is tracked by checking off boxes in this plan file (which IS in the Vacation Planner repo). Commit the checked-off plan file after each task.

---

## File map

**Create:**
- `~/.claude/agents/sherlock.md` — Sherlock subagent definition (frontmatter + system prompt + output schema)
- `~/.claude/hooks/sherlock.sh` — Stop-hook shell wrapper (POSIX, executable)
- `~/.claude/hooks/tests/test_sherlock.sh` — test harness (POSIX, executable)
- `~/.claude/hooks/tests/fixtures/no_code_turn.json` — fixture: turn with no code edits
- `~/.claude/hooks/tests/fixtures/code_no_claim_turn.json` — fixture: code edits, no completion claim
- `~/.claude/hooks/tests/fixtures/code_claim_no_evidence_turn.json` — fixture: claimed done, no verification tool calls
- `~/.claude/hooks/tests/fixtures/code_claim_with_evidence_turn.json` — fixture: claimed done, tool calls include a `preview_*`
- `~/.claude/hooks/tests/fake-curl.sh` — stub for the Anthropic API call used in tests

**Modify:**
- `~/.claude/settings.json` — add Cerberus + Sarge entries to `permissions.deny`; add Sherlock registration to `hooks.Stop`

**Not touched:** anything under `/Users/jeff_s/Projects/Vacation Planner/`. The plan file is the only project artifact this work produces.

---

## Public surface

**`sherlock.sh` (POSIX):**
- Reads Stop-hook JSON on stdin
- Env vars read: `ANTHROPIC_API_KEY` (required for LLM step; missing → exit 0 with one-line stderr note), `SHERLOCK_MODEL` (default `claude-haiku-4-5-20251001`), `SHERLOCK_CURL` (default `curl`, override for tests to point at fake-curl.sh)
- Exit `0` = allow / no action
- Exit `2` = show a `[Sherlock] <message>` line on stderr; Claude Code injects it into the next turn's context
- Never prints anything on stdout

**`sherlock.md` (subagent definition, referenced but read via `cat`):**
- YAML frontmatter with `name`, `description`, `model`, `tools: []`
- System prompt body: character voice + evidence rules + output schema
- Output schema (that Sherlock must return): `{ "claimed_done": bool, "has_evidence": bool, "message": string }`

**`test_sherlock.sh` (POSIX):**
- No arguments. Runs every fixture and asserts exit code + stderr shape.
- Exit `0` if all pass, `1` if any fail
- Prints per-test PASS/FAIL to stdout

**`permissions.deny` additions (`~/.claude/settings.json`):**

Cerberus (5 entries):
- `Write(**/vacation.db)`
- `Write(**/*.sqlite)`
- `Write(**/*.sqlite3)`
- `Bash(rm * vacation.db*)`
- `Bash(rm * *.sqlite*)`

Sarge (12 entries):
- `Bash(rm -rf *)`, `Bash(rm -fr *)`
- `Bash(git push --force*)`, `Bash(git push -f*)`, `Bash(git push --force-with-lease*)`
- `Bash(git reset --hard*)`
- `Bash(git checkout --*)`, `Bash(git restore --*)`
- `Bash(git clean -f*)`, `Bash(git branch -D*)`
- `Bash(*--no-verify*)`, `Bash(*--no-gpg-sign*)`

**`hooks.Stop` addition:** one command hook pointing to `~/.claude/hooks/sherlock.sh`.

---

## Test list (names only)

`test_sherlock.sh` runs these seven, one per fixture / branch:

- `test_kill_switch_marker_exits_zero_silently` — `touch ~/.claude/watchdogs.disabled`, run any fixture → exit 0, no stderr
- `test_missing_api_key_exits_zero_with_notice` — unset `ANTHROPIC_API_KEY`, run code-edit fixture → exit 0, one line on stderr
- `test_no_code_edits_exits_zero_silently` — feed `no_code_turn.json` → exit 0, no stderr, curl NOT called
- `test_code_touched_no_claim_exits_zero` — feed `code_no_claim_turn.json`, fake-curl returns `{claimed_done:false}` → exit 0
- `test_code_touched_claim_no_evidence_exits_two` — feed `code_claim_no_evidence_turn.json`, fake-curl returns `{claimed_done:true, has_evidence:false, message:"[Sherlock] ..."}` → exit 2, stderr starts with `[Sherlock]`
- `test_code_touched_claim_with_evidence_exits_zero` — feed `code_claim_with_evidence_turn.json`, fake-curl returns `{claimed_done:true, has_evidence:true}` → exit 0
- `test_malformed_llm_response_exits_zero_silently` — fake-curl returns `not-json` → exit 0 (fail open, don't crash the parent session)

---

## Tasks

### Task 1: Prereqs — verify tooling and set up directories

**Files touched:**
- Create empty: `~/.claude/hooks/tests/` and `~/.claude/hooks/tests/fixtures/`
- Create empty: `~/.claude/agents/`

**Steps:**

- [x] Confirm `jq` is installed: `jq --version`. If missing on macOS: `brew install jq`.
- [x] Confirm `curl` is installed: `curl --version`.
- [x] Confirm the user has `ANTHROPIC_API_KEY` set: `echo "${ANTHROPIC_API_KEY:0:6}..."` should print six chars + `...`. If empty, tell Jeff — he'll need to add it to his shell profile (`~/.zshrc`) before Sherlock can work.
- [x] `mkdir -p ~/.claude/hooks/tests/fixtures ~/.claude/agents`
- [x] Back up settings.json: `cp ~/.claude/settings.json ~/.claude/settings.json.bak.$(date +%s)`. Keep the backup path in a variable and print it — recovery matters if a bad edit corrupts the file.
- [x] Verify current settings.json is valid: `jq . ~/.claude/settings.json > /dev/null` should exit 0.

---

### Task 2: Add Cerberus deny rules to settings.json

**Files:** Modify `~/.claude/settings.json` — append 5 entries to `permissions.deny`.

**Public surface:** the five deny entries listed under "public surface" above.

**Steps:**

- [x] Read the current `permissions.deny` shape. Confirm it's a JSON array (currently empty).
- [x] Append the 5 Cerberus entries using `jq`: `jq '.permissions.deny += ["Write(**/vacation.db)", "Write(**/*.sqlite)", "Write(**/*.sqlite3)", "Bash(rm * vacation.db*)", "Bash(rm * *.sqlite*)"]' ~/.claude/settings.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json`
- [x] Validate: `jq .permissions.deny ~/.claude/settings.json` shows the 5 entries.
- [x] Smoke test (needs Claude Code restart to pick up new deny rules): after restart, ask Claude Code in any project to `Write` a file at `/tmp/vacation.db`. Expect: refused with a permission-denied message. Ask it to `Write` a file at `/tmp/other.txt`. Expect: allowed.
- [x] Delete `/tmp/vacation.db` if it got created before the block: `rm -f /tmp/vacation.db`.
- [x] Check `- [x]` on the Cerberus row and commit the plan progress in the Vacation Planner repo.

---

### Task 3: Add Sarge deny rules to settings.json

**Files:** Modify `~/.claude/settings.json` — append 12 entries to `permissions.deny`.

**Public surface:** the 12 Sarge entries listed under "public surface" above.

**Steps:**

- [x] Append the 12 Sarge entries with the same `jq` pattern as Task 2. All 12 entries in one `jq += [...]` call so it's a single atomic edit.
- [x] Validate: `jq '.permissions.deny | length' ~/.claude/settings.json` returns `17` (5 Cerberus + 12 Sarge).
- [x] Smoke test (after Claude Code restart): ask Claude Code to run `Bash(rm -rf /tmp/anything)`. Expect: refused. Ask it to run `Bash(git status)`. Expect: allowed.
- [x] Check `- [x]` and commit the plan progress.

---

### Task 4: Write Sherlock's subagent definition (sherlock.md)

**Files:** Create `~/.claude/agents/sherlock.md`.

**Public surface:** frontmatter block + system prompt body. The frontmatter follows Claude Code subagent conventions:

```yaml
---
name: sherlock
description: The Verifier — sniffs out AI completion claims without evidence
model: claude-haiku-4-5-20251001
tools: []
---
```

The body (system prompt) covers three things:
1. Character voice — Sherlock is a bloodhound-eared detective
2. Evidence rules — what counts as verification (specifically: `preview_*` tool calls, `curl localhost:*`, `pytest`/`npm test` output). What does NOT count: narration.
3. Output schema — Sherlock must return valid JSON matching `{ "claimed_done": bool, "has_evidence": bool, "message": string }`. Message is empty string unless both `claimed_done` is true AND `has_evidence` is false; then message starts with `[Sherlock] ` and is one sentence.

**Steps:**

- [ ] Write the file with the frontmatter above and the three-part system prompt body. Full prompt text is engineer's judgment call within the constraints above — aim for ~300 words. Word "Sherlock" appears in character voice; do not include emoji per Jeff's global preference.
- [ ] Verify YAML frontmatter parses: `head -8 ~/.claude/agents/sherlock.md | python3 -c "import sys, yaml; print(yaml.safe_load(sys.stdin.read().split('---')[1]))"` should print a dict with keys `name`, `description`, `model`, `tools`.
- [ ] Check `- [x]` and commit the plan progress.

---

### Task 5: Write sherlock.sh (the Stop-hook wrapper)

**Files:** Create `~/.claude/hooks/sherlock.sh` and `chmod +x` it.

**Behavior (public surface, ordered):**

1. `set -eu` at the top. POSIX shell — no `bash`-isms.
2. **Kill-switch check.** If `~/.claude/watchdogs.disabled` exists, exit 0 immediately.
3. **API key check.** If `${ANTHROPIC_API_KEY:-}` is empty, print `[Sherlock] No ANTHROPIC_API_KEY set; skipping verification check.` to stderr and exit 0. Fails open, doesn't block the session.
4. **Read stdin.** Capture into a variable via `input=$(cat)`. If empty, exit 0.
5. **Extract signals with jq.** From the stdin JSON:
   - `final_message` — the assistant's last message text (best-effort — schema for Stop hook input is not fully documented, so try known key paths and fall back to empty string; NEVER crash on missing keys)
   - `tool_calls` — array of `{tool: string, bash_summary: string}` for this turn's tool calls. Bash summary is the first ~120 chars of the command.
6. **Code-touching heuristic.** Set `code_touched=true` if any tool call is `Edit` or `Write`, OR any Bash call's summary matches `pytest|npm test|python |flask |node ` (with word boundaries). If not, exit 0 silently.
7. **Build the LLM payload.** Compose a JSON body for `POST /v1/messages` with:
   - `model` = `${SHERLOCK_MODEL:-claude-haiku-4-5-20251001}`
   - `max_tokens` = 400
   - `system` = contents of `~/.claude/agents/sherlock.md` from the first line after the frontmatter to end of file (strip the YAML block)
   - `messages` = `[{role: user, content: "<JSON-encoded {final_message, tool_calls} payload>"}]`
8. **Invoke the API.** `${SHERLOCK_CURL:-curl}` with `-sS`, `-H "x-api-key: $ANTHROPIC_API_KEY"`, `-H "anthropic-version: 2023-06-01"`, `-H "content-type: application/json"`, `--max-time 20`, `--data @-` reading the payload from stdin. Capture the response.
9. **Parse the response.** Extract `content[0].text` via jq. Then parse THAT as JSON. If parsing fails at either level, exit 0 silently (fail open — never break the parent session).
10. **Act on the verdict.** If `.claimed_done == true` AND `.has_evidence == false`, print `.message` to stderr and exit 2. Otherwise exit 0.

**Do NOT:**
- Print anything to stdout (would confuse Claude Code's hook JSON parser)
- Exit with any code other than 0 or 2 (other codes are undefined behavior for hooks)
- Retry on API failure (accept ~$0.005 lost + fail open)

**Steps:**

- [ ] Write the script per behavior above
- [ ] `chmod +x ~/.claude/hooks/sherlock.sh`
- [ ] Quick sanity: `echo '{}' | ~/.claude/hooks/sherlock.sh` → exit 0, no stderr (no code touched — short-circuits before API call).
- [ ] `touch ~/.claude/watchdogs.disabled && echo '{}' | ~/.claude/hooks/sherlock.sh; rm ~/.claude/watchdogs.disabled` → exit 0, no stderr (kill-switch).
- [ ] Check `- [x]` and commit the plan progress.

---

### Task 6: Register Sherlock in settings.json

**Files:** Modify `~/.claude/settings.json` — add a `Stop` entry to `hooks`.

**Public surface:**

```json
"Stop": [
  {
    "matcher": "",
    "hooks": [
      { "type": "command", "command": "~/.claude/hooks/sherlock.sh" }
    ]
  }
]
```

**Steps:**

- [ ] Check whether `hooks.Stop` exists in settings.json: `jq .hooks.Stop ~/.claude/settings.json`. If `null`, add the whole array. If existing, append the hook object to the first matcher.
- [ ] Add the entry with `jq`. Concrete command: `jq '.hooks.Stop = ((.hooks.Stop // []) + [{"matcher":"","hooks":[{"type":"command","command":"~/.claude/hooks/sherlock.sh"}]}])' ~/.claude/settings.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json`.
- [ ] Validate: `jq . ~/.claude/settings.json > /dev/null` succeeds.
- [ ] Restart Claude Code for the new hook to load. In a fresh session: verify no errors on startup (Claude Code will complain loudly if the hook config is malformed).
- [ ] Check `- [x]` and commit the plan progress.

---

### Task 7: Write sherlock.sh tests

**Files:**
- Create `~/.claude/hooks/tests/fixtures/no_code_turn.json` — turn with only Read/Grep tool calls
- Create `~/.claude/hooks/tests/fixtures/code_no_claim_turn.json` — has one Edit call, final message is "Here's the change."
- Create `~/.claude/hooks/tests/fixtures/code_claim_no_evidence_turn.json` — has one Edit call, final message is "That should work now."
- Create `~/.claude/hooks/tests/fixtures/code_claim_with_evidence_turn.json` — has one Edit call and one `mcp__Claude_Preview__preview_screenshot` call, final message is "Done — verified in browser."
- Create `~/.claude/hooks/tests/fake-curl.sh` — POSIX script that echoes a canned Anthropic-Messages-style response body. Behavior driven by `FAKE_CURL_MODE` env var: `claimed_no_evidence`, `claimed_with_evidence`, `no_claim`, `malformed`.
- Create `~/.claude/hooks/tests/test_sherlock.sh` — the harness; runs all seven test cases from the "Test list" section above.

**Steps:**

- [ ] Draft the four fixture JSON files. Each is small (~30-100 lines). Structure them to match your best inference of the Stop hook JSON schema. Include `transcript` / `messages` shape as a nested array with role + content. If real Claude Code Stop-hook JSON differs, fixtures + `sherlock.sh` jq queries need to align — update both together.
- [ ] Write `fake-curl.sh` (~40 lines). Reads args, ignores the URL, uses `$FAKE_CURL_MODE` to pick which canned response to print.
- [ ] Write `test_sherlock.sh` (~120 lines). Uses `SHERLOCK_CURL=~/.claude/hooks/tests/fake-curl.sh` env override, sets `FAKE_CURL_MODE` per test. `chmod +x` all three shell scripts.
- [ ] Run `~/.claude/hooks/tests/test_sherlock.sh`. All seven should PASS. If any FAIL, fix in sherlock.sh (never in the test) and re-run.
- [ ] Check `- [x]` and commit the plan progress.

---

### Task 8: End-to-end smoke test

**Files:** none — this is a real live-session validation.

**Steps:**

- [ ] Restart Claude Code. Open a scratch project (`mkdir /tmp/smoke && cd /tmp/smoke && git init`).
- [ ] **Sherlock happy path — should nag.** Ask Claude Code to edit any file (e.g., "create hello.py with a print statement"). When Claude claims it's done without loading the page or running the file, confirm a `[Sherlock] ...` message appears in the next turn's transcript.
- [ ] **Sherlock silent path.** In another turn, edit a file AND run it (`python hello.py`) so tool calls include the verification. Confirm no Sherlock message.
- [ ] **Sherlock kill-switch.** `touch ~/.claude/watchdogs.disabled`. Ask Claude Code to "create foo.py". When Claude claims done without verifying, confirm no Sherlock message. Then `rm ~/.claude/watchdogs.disabled`.
- [ ] **Cerberus.** Ask Claude Code to `Write` a file at `/tmp/vacation.db`. Confirm the tool call is refused. Ask it to `Write` a file at `/tmp/other.txt`. Confirm allowed.
- [ ] **Sarge.** Ask Claude Code to run `git push --force origin main` (in the scratch repo — nothing will actually push since there's no remote). Confirm the Bash call is refused before it runs. Ask it to run `git status`. Confirm allowed.
- [ ] If any test fails, note which mechanism and open a follow-up task in this plan. Do NOT check `- [x]` on Task 8 until all five paths pass.
- [ ] Once all five pass: check `- [x]`, commit the plan progress, and mark the plan complete in the commit message.

---

## Self-review

**Spec coverage:** Each spec section maps to at least one task:
- Mechanism 1 (Cerberus) → Task 2
- Mechanism 2 (Sarge) → Task 3
- Mechanism 3 (Sherlock) → Tasks 4, 5, 6
- Testing strategy → Task 7
- Disabling and toggling → covered in sherlock.sh (kill-switch check) and settings.json edits (permanent disable)
- Open questions from spec (invocation mechanism, Stop hook JSON schema, code-touching detection) → resolved in the Architecture section of this plan header + Tasks 5 and 7 (fixtures + jq path robustness)

**Placeholder scan:** no "TBD", no "add error handling as appropriate", no "similar to Task N", no unshown code where behavior is being changed. The one deliberate handwave is "engineer's judgment call for the exact prompt wording" in Task 4 — constrained by "aim for ~300 words" and three concrete content requirements. This is acceptable because prompt tuning is a taste call and a fixed word count won't help.

**Type consistency:** Sherlock's output schema `{claimed_done, has_evidence, message}` is referenced identically in Task 4 (system prompt), Task 5 (parse), Task 7 (fixtures + fake-curl). Env var names (`ANTHROPIC_API_KEY`, `SHERLOCK_MODEL`, `SHERLOCK_CURL`) are consistent across Tasks 5 and 7. File paths use `~/.claude/agents/sherlock.md` and `~/.claude/hooks/sherlock.sh` throughout, matching the spec.

**One weakness worth naming:** Task 7's fixture JSON is inferred, not confirmed against Claude Code's actual Stop-hook input schema. If the real JSON differs, both fixtures and jq queries in sherlock.sh need to align. Task 5's "best-effort key paths and fall back to empty string" clause is the safety net; the smoke test in Task 8 is where a real-schema mismatch would surface. If Task 8 reveals a mismatch, that's a one-turn fix to update sherlock.sh's jq queries — not a plan restructure.
