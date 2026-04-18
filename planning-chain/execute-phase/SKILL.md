---
name: execute-phase
description: "Executes a plan-phase plan doc to completion. Spawns one worktree-isolated teammate per swim lane via TeamCreate, respects the lane DAG and interface freeze gates, auto-merges lanes when their verify passes, and retries once on failure before halting. Assigns each teammate a model + thinking level matched to the lane's complexity. Run after /plan-phase has produced plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md."
---

# execute-phase

Follow-on executor for `/plan-phase`. Consumes the plan doc + TaskCreate'd lane tasks and drives them to completion: root lanes first, parallel lanes in parallel, auto-merge on green, retry-once on failure, halt-all on second failure.

## When to use

- `/plan-phase` has produced `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` and a `TaskCreate`'d task per lane.
- You want the phase executed **full-auto** end-to-end, with lanes merging to the current branch as their gates go green.
- The working tree is clean and you're on the branch lanes should merge into.

## When NOT to use

- Plan doc has never been produced → run `/plan-phase` first.
- You want human checkpoints between lanes → execute lanes manually (`Agent(isolation: "worktree", name: "<SL-ID>")` with the lane's section pasted in).
- The plan doc's DAG has cycles or a lane's owned files overlap another lane's → fix the plan first.

## Model tiers (edit on Anthropic releases)

Model IDs appear only in this table. All model-routing logic in the workflow references the tier name.

| Tier      | Model              | Use for                                                       |
|-----------|--------------------|---------------------------------------------------------------|
| frontier  | claude-opus-4-7    | retry escalation ceiling, highest-stakes lanes                |
| strong    | claude-sonnet-4-6  | contract-authoring (IF-freeze), schema/migration, algorithmic |
| fast      | claude-haiku-4-5   | mechanical wiring, small components against frozen types      |

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<plan-path>` | no | Path to plan doc. Default: auto-detected via env vars + filename convention. |
| `--dry-run` | no | Parse + validate, print the dispatch schedule with per-lane model assignments, do not spawn teammates. |
| `--resume` | no | Continue a partially executed plan: skip lanes already merged (their merge commit is on the target branch and their produced gates are closed). |

## Environment variables

Plan-location variables are inherited from `plan-phase` so the two skills resolve the same defaults:

| Variable | Default | Meaning |
|---|---|---|
| `PLAN_SPEC` | Auto-detected highest `specs/phase-plans-v*.md` | Path to spec file (used only for version extraction here). |
| `PLAN_VERSION` | Extracted `v\d+` from spec filename | Version token embedded in plan-doc filename. |
| `PLAN_PHASE_ALIASES` | Built-in alias table | Path to alias-map JSON. |
| `PLAN_DOC` | `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` | Override the resolved plan-doc path directly. |
| `EXECUTE_MERGE_TARGET` | Current branch at invocation | Branch lanes merge into. |
| `EXECUTE_WORKTREE_ROOT` | `.worktrees/` (inside repo; auto-gitignored) | Root dir for per-lane worktrees. |
| `EXECUTE_MAX_PARALLEL_LANES` | `2` | Max concurrent lane dispatches per wave. Keep small: each merge makes the other running lanes' bases stale. |

## Deferred tool preloading

Several tools this skill uses are deferred and must be registered via `ToolSearch` before first call. Load them in a single query at the top of Step 1 so mid-workflow calls (especially `TaskUpdate` on every dispatch and `AskUserQuestion` on preflight failures) don't pay a round-trip:

```
ToolSearch(query: "select:TaskCreate,TaskUpdate,TaskList,TeamCreate,AskUserQuestion")
```

## Workflow (orchestrator-only main thread)

The main thread reads exactly two things: the plan doc and the TaskList. It does not Grep/Read repo source — lane teammates own their files. If the main thread is reaching for Grep or Read on source files, the teammate brief was incomplete; re-brief via `SendMessage`.

### Step 1 — Resolve + parse plan doc

Resolve in order: `$PLAN_DOC` → `<plan-path>` arg → default path built from `$PLAN_VERSION` + phase alias argument.

`Read` the plan doc. Parse these sections (headings are stable IDs from `plan-phase`):

- `## Interface Freeze Gates` — list of `IF-0-<PHASE>-<N>` items with descriptions.
- `## Cross-Repo Gates` (optional) — `IF-XR-<N>`.
- `## Lane Index & Dependencies` — machine-readable DAG block (`SL-N`, `Depends on:`, `Blocks:`, `Parallel-safe:`).
- `## Lanes` — per-lane: `Scope`, `Owned files`, `Interfaces provided`, `Interfaces consumed`, task table.
- `## Verification` — final end-to-end commands.

Build the lane graph. Topologically sort it; reject on cycle with a clear error.

### Step 2 — Preflight

- **Run `scripts/verify_harness.sh <merge-target>`.** Enforces the hard gates: git + git-worktree available, inside a work tree, merge-target branch exists locally, working tree clean (allowlist: `.claude/worktrees/`, `.claude/execute-phase-state.json`), `.gitignore` covers worktree paths. **Non-zero exit blocks dispatch.** On dirty-tree failure, invoke `AskUserQuestion` with `[commit the changes as a chore, stash for the duration of the phase, abort /execute-phase]` and take the user's answer. No override.
- Record merge target = current branch (or `$EXECUTE_MERGE_TARGET`).
- Sanity check: every symbol appearing in any lane's `Interfaces consumed` must either be produced by an upstream lane's `Interfaces provided` OR be pre-existing (skip unknown symbols with a warning, don't hard-fail).
- If `--dry-run`: print the topological schedule with per-lane model/thinking assignments (see Step 3) and stop here.

### Step 2a — Worktree hygiene preflight

Prune stale worktrees in `.claude/worktrees/` at phase start. Skip on `--resume`.

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/execute-phase/scripts/sweep_stale_worktrees.sh"
# Pass --dry-run to preview decisions without removing anything.
```

For each worktree marked `PRUNE`:

1. `git worktree unlock <path>` (succeeds silently if unlocked).
2. `git worktree remove -f -f <path>` — double-force bypasses both the lock and the unmerged-changes check (safe since the ancestor check already confirmed incorporation).
3. `git branch -D <branch>` **only** if the branch name matches an auto-named pattern (`worktree-*`, `phase/*/sl-*`). Leave human-named branches (`skills/*`, `feature/*`, `fix/*`) intact even when their work is on the merge target — the user may still want the reference.

Worktrees marked `KEEP` are left alone; log a one-line warning per worktree.

### Step 3 — Assign model + thinking per lane

Each lane gets a model and thinking level matched to its complexity. The assignment is encoded on the `Agent` call via `model:` and communicated as guidance in the brief.

Apply in order, first match wins:

1. Lane has `Execution hint: <tier>/<thinking>` inside its `### SL-N` section → use it verbatim.
2. Lane publishes any `IF-0-*` gate (contract-authoring) → `strong` / high. Downstream lanes depend on the symbols being correct.
3. Lane scope mentions migrations, schema, or SQL → `strong` / high. Bad migrations are expensive to unwind.
4. Lane scope mentions algorithmic/computed logic AND has tests as first task → `strong` / medium.
5. Lane owns >10 files AND publishes no interfaces (wiring / mechanical refactor) → `fast` / low.
6. Lane implements small components against already-frozen types → `fast` / low.
7. Default fallback → `strong` / medium.

Resolve tier → model from the Model tiers table at the top of this skill and pass the concrete model ID to `Agent(model: …)`.

**Retry escalation** (after a lane's first failure):

- `fast` → `strong`
- `strong` → `frontier`
- `frontier` → stay at `frontier`
- Thinking level bumps up one tier (`low → medium → high`).

`Agent` does not expose a direct thinking-level parameter — convey it in the brief's framing (e.g., "Think carefully before editing shared type definitions" vs "These are mechanical edits; move quickly").

### Step 4 — TeamCreate

Create one team for the phase:

- **Team name**: `phase-<PHASE_ALIAS>` (e.g., `phase-p1`).
- **Teammates**: one per lane, `subagent_type: "general-purpose"`. Teammate names use the allocator — see Step 5.

TeamCreate registration enables `SendMessage` retry rounds without fresh Agent spawns.

### Step 5 — Dispatch loop

State per lane: `pending | running | verify-ok | merged | failed`. State per gate: `open | closed`.

Repeat until all lanes are `merged` or halt is triggered:

1. **Find ready lanes** — `pending` lanes whose upstream lanes are all `merged` AND all consumed `IF-0-*` gates are `closed`. Cap the dispatch batch at `EXECUTE_MAX_PARALLEL_LANES` (default 2). Slice the eligible set to the first N (lower SL-ID first) and queue the rest.

2. **Allocate worktree names**. For each ready lane, run `scripts/allocate_worktree_name.sh <sl-id>`. Substitute the emitted name (e.g., `lane-sl-1-20260418T144536-nxz5`) into both `Agent(name=…)` and the briefed `EnterWorktree(name=…)`. Bare `lane-<sl-id>` names collide under rapid dispatch.

3. **Dispatch in parallel** — single message with one `Agent(team_name: "phase-<alias>", name: "<allocated-name>", subagent_type: "general-purpose", model: "<assigned>")` call per ready lane. Sequential dispatch within a wave is a bug. Do NOT pass `isolation: "worktree"` when `team_name` is set — the harness drops `isolation` in that combination. Use `team_name` for coordination + teammate-called `EnterWorktree` for filesystem isolation.

4. **Teammate brief** contains:
   - **Worktree isolation (mandatory, first tool call)**: Load `EnterWorktree` via `ToolSearch(query="select:EnterWorktree,ExitWorktree")` if not already in the tool registry. Call `ExitWorktree(action="keep")` FIRST (no-op if no session active; clears any stale session-state flag inherited from a prior teammate). Then call `EnterWorktree(name: "<allocated-name>")` as the very next tool call, BEFORE any file operation. Every subsequent edit/commit goes into that worktree. At the end, call `ExitWorktree(action: "keep")` so the worktree and branch remain available for the orchestrator to merge.
   - The full `### SL-N` section copied verbatim from the plan doc.
   - **Architecture context** (1–2 sentences): how this lane fits the phase; how this phase fits the roadmap.
   - **Related files** the lane reads but does not own: type defs, test fixtures, shared config. Distinct from `Owned files`.
   - Concrete upstream artifact paths (populated from now-merged upstream lanes) for every entry in `Interfaces consumed`.
   - The merge target branch and the orchestrator's current tip SHA, injected as `<TIP_SHA>` (used by the stale-base check below).
   - The lane's test → impl → verify task list.
   - Thinking-level guidance matching the lane's profile.
   - **Stale-base discipline**: AFTER `EnterWorktree` returns and BEFORE any code change, run `git rebase main` (or `git merge main --no-ff -m "merge: incorporate prior-lane foundation"`). Verify with `git merge-base --is-ancestor <TIP_SHA> HEAD && echo OK || echo STALE`. Repeat the rebase immediately before your final commit. On conflicts, STOP and report — do not resolve silently. Never `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree; this destroys peer-lane work on `--no-ff` merge.
   - **Structured-reply instruction**: "When done, reply with JSON `{lane, verify_exit_code, failed_tasks, notes, commit_sha, branch, worktree_path}`. All seven fields are mandatory. `branch` and `worktree_path` come from `EnterWorktree`'s return value."

   Apply the `/task-contextualizer` checklist to every brief.

5. **Await completions**. For each:
   - `verify_exit_code == 0` → run gate verification (Step 6). On green → auto-merge (Step 7). Mark lane `merged`, flip produced gates to `closed`, update the lane's `TaskCreate`'d task to `completed`.
   - Non-zero or gate failure → retry-once (Step 8).
   - **Idle without JSON reply** → `SendMessage` to the teammate by name asking for the envelope. If it still doesn't reply and a commit exists on a branch you can identify via `git branch` or `git log --all --oneline --author=<user>`, treat the commit as the result and proceed with Step 7's destructiveness check. Never block the phase on missing JSON when the artifact is on disk.

6. Persist lane + gate state to `.claude/execute-phase-state.json` after every transition (enables `--resume`).

### Step 6 — Gate verification

For each gate the lane provides:

1. If the plan doc's `## Verification` section has a command that names this gate's artifact (e.g., `psql` for schema gates, `grep` for symbol gates), run it against the lane's worktree.
2. Else fall back:
   - Files listed under `Owned files` exist.
   - Symbols listed under `Interfaces provided` are grep-visible at expected paths.
   - Lane's own verify command exited 0.

Any failure here counts as a lane failure and triggers retry-once.

### Step 6.5 — Parent-tree leakage check

Detects two isolation failure modes before merge: (a) teammate writes landing in the parent checkout, (b) `EnterWorktree` falling back to in-place branch creation on the parent.

Run:
```bash
bash scripts/parent_tree_leakage_check.sh <lane-id> <owned-globs-file> <merge-target>
```

Verdicts (emitted on stdout; details on stderr):

- **`CLEAN`** — proceed to Step 7.
- **`LEAKAGE_DETECTED`** (dirty files overlap the lane's owned globs):
  1. Verify byte-equality: for each leaked path, `git diff <lane-sha> -- <path>` must be zero lines (confirms the leak is a redundant copy of committed lane work). If non-zero, treat as independent uncommitted work and STOP.
  2. Clean the parent: `git checkout -- <modified>` for tracked changes; `rm <untracked>` for new files. Do NOT `git stash`.
  3. Record in `.claude/execute-phase-state.json` under the lane's `notes`.
  4. Proceed to Step 7.
- **`UNRELATED_DIRTY_TREE`** (dirty files outside the lane's globs) → STOP. Ask via `AskUserQuestion` whether to stash, commit, or abort.
- **`PARENT_ON_WRONG_BRANCH`** (tree clean but parent on a non-merge-target branch — `EnterWorktree` fell back to in-place branch creation):
  1. Merge by SHA per Step 7.
  2. Run `git checkout <merge-target>` in the parent BEFORE Step 7's worktree cleanup — otherwise `git worktree remove` refuses.
  3. Record parent-fallback note in state.

### Step 7 — Auto-merge

**Branch discovery.** Resolve the lane's branch/worktree from the reply envelope's `commit_sha` via `git log --oneline -1 <commit_sha>` + `git worktree list`. Never trust the briefed branch name.

**Cross-lane file-touch audit.** Before the destructiveness check, run:

```bash
python scripts/audit_lane_file_touches.py <lane-sha> <plan-doc-path> <this-lane-id>
```

Verdicts:

- **`CLEAN`** → every touched file is within this lane's `Owned files` globs. Proceed.
- **`PEER_INTRUSION`** → the lane touched files owned by another lane. Stderr lists peer + files. Pause on `AskUserQuestion`: merge anyway, bounce the lane, or ask the teammate to revert the peer edits.
- **`ORPHAN_FILES`** → the lane touched files outside every lane's globs. Surface to user — likely plan or impl bug.

**Pre-merge destructiveness check** — lanes that committed against a stale base can wipe peer-lane work on `--no-ff` merge. Use the three-outcome script:

```bash
bash scripts/pre_merge_destructiveness_check.sh <lane-sha> <merge-target> <whitelist-path>
```

Where `<whitelist-path>` is a file (one path per line) of deletions the lane legitimately performs per its plan section; `/dev/null` if the lane is purely additive.

Verdicts:

- **`SAFE`** — deletion list empty or all whitelisted. Merge with `git merge --no-ff <lane-sha>`.
- **`STALE_BASE_DETECTED`** — lane branched from a pre-peer-merge main but did not actively delete. Preview, then finalize with the 3-way merge:
  ```bash
  git merge --no-ff --no-commit <lane-sha>
  ls <peer-lane-owned-paths>   # must exist
  git commit --no-edit
  ```
  Do NOT salvage — salvage loses commit lineage.
- **`CONFLICT`** — lane actively removed files. DO NOT `--no-ff` merge. Salvage:
  ```bash
  git checkout <lane-sha> -- <lane's owned paths from the plan doc>
  git commit -m "feat(<phase>,<sl-id>): <subject>

  Salvage of <SL-ID> lane work: lane commit was based on stale main and
  would have deleted <peer lanes' files>. Cherry-picked in-scope additions only."
  ```
  Count this as a successful completion — no retry.

**Merge conflict** (non-destructive case) → treat as lane failure: `git merge --abort`, surface the conflict to the teammate via `SendMessage` asking it to rebase inside its worktree, then retry the merge.

**Post-merge import smoke** — run immediately after `git merge --no-ff` and before dispatching the next wave:

```bash
packages="$(git diff --name-only HEAD~..HEAD \
    | grep '__init__\.py$' \
    | sed 's|/__init__\.py$||; s|/|.|g' \
    | sort -u)"
if [[ -n "$packages" ]]; then
    bash scripts/post_merge_import_smoke.sh $packages
fi
```

On non-zero exit, the merge broke package load. Unwind with `git reset --hard HEAD~`, then retry per Step 8. Second failure halts the phase.

**Post-merge cleanup.** `git worktree remove --force` any worktrees the lane used. `git branch -D` (not `-d`) every lane branch — salvaged work leaves branches unreachable from the merge target. If Step 6.5 returned `PARENT_ON_WRONG_BRANCH`, `git checkout <merge-target>` in the parent BEFORE removing worktrees.

### Step 8 — Retry-once, then halt

On first failure for a lane, decide between SendMessage-resume and kill-and-respawn based on whether the lane committed anything:

- **`commit_sha` empty AND `verify_exit_code != 0`** (teammate STOPped during preflight, no work done): kill via `TaskStop` and re-`Agent`-spawn fresh. Never resume a STOPped teammate with no commits — the worktree may be reaped and the resumed instance writes into the parent.
- **`commit_sha` populated AND verify failed** (teammate did work but it broke): re-address the same named teammate via `SendMessage` to preserve branch-state context.

In either case, the brief includes: the failure log, the escalated model+thinking hint, and the instruction to fix the failing task and re-run verify.

On second failure:

- Cancel all still-running lane Agents via their task IDs.
- Emit a diagnostic report naming the failing lane, the failing task, the last ~30 log lines, and which lanes were merged vs pending.
- Persist state to `.claude/execute-phase-state.json` and exit cleanly. User can fix and re-run with `--resume`.

### Step 9 — Final verification, cleanup, and summary

After all lanes merged:

1. Run every command under the plan doc's `## Verification` section against the merged tree.
2. Run every assertion under `## Acceptance Criteria` that can be mechanically checked.
3. **Team teardown**. Try `TeamDelete` first. If it blocks (in-process teammates ignore `shutdown_request`), fall back to filesystem cleanup: `bash scripts/team_teardown.sh phase-<alias>` (rm on `~/.claude/teams/<team>/` + `~/.claude/tasks/<team>/`).
4. **Kill leftover background processes**. Run `ps aux | grep -E "next dev|node.*dev"` and `kill` any stragglers spawned by lane teammates.
5. **Clean-tree verification**. Run `git status`. After successful completion the tree must be clean (lane merges are the only changes, and they're committed). Allowlist: `.claude/worktrees/`, `.claude/execute-phase-state.json`. Anything else → stop and surface.
6. Emit final summary:
   - Lanes merged (with merge-commit SHAs)
   - Gates closed
   - Final verification pass/fail
   - Total wall-clock duration
   - Per-lane breakdown: model used, duration, token spend, retry count
7. Mark the phase's parent TaskCreate (if one exists) as completed.

**Halt exception**: on Step 8 second-failure halt, `.claude/execute-phase-state.json` persists for `--resume`. This is the documented dirty-tree exception; no commit required.

### Step 9.5 — Close-out: Reflection

After final summary, spawn a reflection agent using the `frontier` tier (see Model tiers table above):

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "execute-phase-reflection",
  prompt: """
    Review the skill at <absolute-path-to-execute-phase/SKILL.md> and the
    current execution transcript.

    Produce REPO-AGNOSTIC feedback on the skill itself. Do not reference
    this specific project, codebase, file names, or domain — reflect only
    on how the skill's instructions performed.

    Output:
    # execute-phase reflection — <ISO timestamp>

    ## What worked
    - <bullet>

    ## Improvements to SKILL.md
    - <specific, actionable change to the instructions>
  """
)
```

Write the reply to the path emitted by:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/next_reflection_path.py" execute-phase
```

Surface to the user: "Reflection saved to <path>."

## Lane state machine

```
pending ──► running ──► verify-ok ──► merged
                 │                        ▲
                 └─fail─► failed ─retry─►─┘ (once)
                                 │
                                 └─fail2─► HALT
```

## Parallelism contract

- All lanes whose dependencies are satisfied at the same time MUST be dispatched in the same message (parallel `Agent` tool calls), up to `EXECUTE_MAX_PARALLEL_LANES`.
- Lanes must not share files. The plan's lane-validation checklist guarantees disjoint ownership; execute-phase trusts the plan and does not re-verify file-glob intersections.
- Shared generated files (e.g., barrel index files, generated types) are called out in the plan's `## Execution Notes`; only the lane that lists them under `Owned files` may modify them.

## Model selection quick-reference

| Symptom in the plan doc | Assigned tier | Thinking |
|---|---|---|
| `Scope` mentions schema / migration / SQL | `strong` | high |
| `Interfaces provided` includes any `IF-0-*` gate | `strong` | high |
| `Scope` mentions algorithm / compute / worker logic | `strong` | medium |
| `Owned files` glob expands to >10 files, no interfaces provided | `fast` | low |
| `Scope` is "small components against frozen types" | `fast` | low |
| `Execution hint:` line is present in lane section | Use it verbatim | Use it verbatim |
| Retry | One tier up | One tier up |

Resolve tier names to model IDs via the Model tiers table at the top of this skill.

## Output contract

On successful completion:

1. Every lane's branch merged into the target branch with a `--no-ff` commit, in topological order.
2. All lane worktrees removed; lane branches deleted.
3. All `TaskCreate`'d lane tasks marked `completed`.
4. `.claude/execute-phase-state.json` deleted (or the `status` field set to `complete`).
5. Team torn down via `TeamDelete` or `team_teardown.sh`.
6. Final summary message to the user.

On halt:

1. Lanes that completed remain merged; their state is preserved.
2. `.claude/execute-phase-state.json` contains the failing lane's name, task, log tail, and which gates/lanes were green vs open.
3. User can `/execute-phase --resume` after fixing the blocker.

## Worktree layout

```
<repo>/
├── .claude/
│   ├── worktrees/
│   │   ├── lane-sl-1-<timestamp>-<random>/
│   │   └── …
│   └── execute-phase-state.json
```

Both paths are auto-added to `.gitignore` in Step 2.

## Teamwork posture (hard rules)

- **Main thread = dispatcher.** Read plan doc + TaskList + git state. Do not Grep/Read source code during execution, except for the Step 7 destructiveness check and file-touch audit.
- **Parallel-by-default.** Ready lanes dispatch in a single message, every round.
- **Name every teammate via the allocator.** Bare `lane-<sl-id>` names collide in rapid dispatch.
- **TaskCreate tasks are the source of truth for lane status.** Update them as lanes transition.
- **No speculative refactoring.** Lane teammates must stay within their `Owned files` globs; reject their work at gate verification if they wandered. Use the file-touch audit to catch this pre-merge.
- **Never trust a branch name.** Resolve work by `commit_sha` from the reply envelope.
- **Never `--no-ff` merge without the destructiveness check.**
- **Never resume a STOPped teammate with no commits.** Kill + respawn.
- **Never override the dirty-tree preflight.** `verify_harness.sh` is the gate. Only paths forward: (a) commit as `chore:`, (b) `git stash push -u` and restore post-phase, (c) abort.

## Browser verification capabilities

When a plan's `## Verification` section includes Playwright/e2e commands or lane tasks ask for browser smoke-testing, run them:

- **Playwright via PMCP** — `pmcp_invoke(tool_id="playwright::browser_navigate", ...)` and related `playwright::*` tools. Default.
- **Chrome DevTools Protocol (CDP)** — low-level debugging (performance traces, CPU profiling).
- **`claude-in-chrome`** — extension-context automation only.

The PMCP Playwright server provisions on demand. If the repo lacks a Playwright config, add one in the lane rather than deferring the test.
