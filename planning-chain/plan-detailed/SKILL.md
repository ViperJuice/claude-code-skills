---
name: plan-detailed
description: "Produce a rigorous, immediately-implementable plan for a single bounded change — a bug fix, a small feature, a targeted refactor. Use whenever the user asks to 'write a plan for X', 'how should I implement Y', 'walk me through the changes to Z', 'I need a plan before I start', 'plan this change', 'detailed implementation plan', or similar — even without the explicit /plan-detailed invocation. This is the standalone planner; do NOT use for multi-phase roadmaps or work that would benefit from parallel swim lanes — those want /phase-roadmap-builder → /plan-phase → /execute-phase. Researches the codebase via parallel Explore teammates, enumerates every file + entity + action + reason, calls out documentation impact, commits the plan doc, and hands off with a clean context window."
---

# plan-detailed

Standalone planner for one bounded change. Not part of the `phase-roadmap-builder` → `plan-phase` → `execute-phase` loop. Used **by exception, outside the pipeline**, when a change is single-concern and the pipeline's roadmap/phase/lane overhead costs more than the change deserves.

## When to use

- The change is bounded — a bug fix, a small feature, a targeted refactor with obvious blast radius.
- One agent (or one developer) will carry the work end-to-end.
- Producing a full phase roadmap would be disproportionate.

## When NOT to use

- Work spans multiple concerns that would benefit from parallel execution → use `/phase-roadmap-builder` (for the roadmap) then `/plan-phase` (per phase).
- Pure research / "how does X work" → use `Agent(subagent_type: "Explore")` directly.
- Task is trivial and one-step ("rename this variable") → just do it; a plan doc is noise.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<task>` | no | Free-form task description. Falls back to prior conversation context if omitted. |
| `--output <path>` | no | Override the generated plan path. Default: `plans/detailed-<slug>-<YYYYMMDD-HHMM>.md`. |
| `--review-external` | no | Run Gemini + Codex review after writing the plan. Requires both CLIs installed and the frontier-model cache populated. |

## Deferred tool preloading

```
ToolSearch(query: "select:AskUserQuestion,ExitPlanMode")
```

## Workflow

### Step 1 — Extract the task + gather implicit context

Task source, in order: invocation args → preceding conversation → `AskUserQuestion` if still unclear. A thin plan is worse than one more question.

Implicit context:

```bash
git status --porcelain 2>/dev/null | head -20
git log --oneline -5 2>/dev/null
git rev-parse --show-toplevel 2>/dev/null || pwd
```

Also read `CLAUDE.md` / `AGENTS.md` at repo root if present.

### Step 2 — Parallel reconnaissance via Explore teammates

Launch up to 3 `Agent(subagent_type: "Explore")` calls in a single message (1–2 is usual for single-concern work). Each Agent call MUST set `name:` for `SendMessage` addressability.

Teammate-naming template: `explore-<area>` (e.g., `explore-auth`, `explore-schema`).

Apply the `/task-contextualizer` checklist to every brief. Each must include:

- The task statement verbatim.
- 1–2 sentences of architecture context: how the relevant module fits the larger system.
- Specific file paths to start from, when known; otherwise a glob to search.
- A scoped question: "Map existing code in `<paths>`. Surface: (a) utilities/patterns to reuse, (b) types/schemas/contracts that constrain the design, (c) places that must change, (d) hidden coupling."
- A length cap: "Report in under 400 words."
- Expected output format.

Block until all return. Findings populate the plan's `## Research summary` section.

### Step 3 — Architect the plan

Synthesize into a concrete change list. Follow these rules rigorously — they're the core of what this skill exists to enforce.

**Research first.** Never propose a change without having located, in this research pass or prior context, the file and pattern it relates to.

**Explicit change enumeration.** Every change names: file path, entity (class/method/function/table/column/config/migration), action (add/modify/delete), reason (one clause).

**Modification over creation.** Prefer editing existing code. Only create new files/functions when separation of concerns demands it or the change has no existing home.

**Scope discipline.** No features beyond what was requested. No refactors of surrounding code unless broken or directly blocking. No speculative error handling, type annotations, or comments on unchanged code.

**Documentation impact enumerated inline.** Every cross-cutting doc (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, `llm.txt`, `llms.txt`, `llms-full.txt`, `services.json`, `openapi.*`, `ARCHITECTURE.md`, `DESIGN.md`, `docs/**`, `rfcs/**`, `adrs/**`) that needs updating gets a bullet with file + entity + action + reason like any other change. If none applies, state `Documentation impact: none — internal refactor, no doc footprint.` Force a conscious decision every run.

**Dependencies & order.** Identify which changes must happen first. Name blocking external dependencies (migrations that must run before a column is read, type definitions others consume, etc.).

**Verification.** Concrete shell/test commands (`pnpm test path/to/foo`, `cargo check`, `psql -c '…'`, `curl …`), behaviors to observe, edge cases to check. No "manually verify that it works" items.

**Acceptance criteria.** 2–5 `- [ ]` items. Testable assertions, not prose. "Users can log in" fails. "`POST /api/auth` returns 200 with a valid session cookie for a registered user" passes.

### Step 4 — Write the plan doc

Derive `<slug>` from the task (kebab-case, 3–5 words: `add-refresh-token-endpoint`, `fix-stale-cache-eviction`). Default path: `plans/detailed-<slug>-<YYYYMMDD-HHMM>.md` at repo root. Override via `--output`.

Also write to the plan-mode scratch file (path in the plan-mode system reminder — do not guess).

Use the template in `## Plan document template` below verbatim.

### Step 5 — External CLI review (only if `--review-external`)

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/review_with_cli.py" \
  --artifact <plan-path> \
  --prompt-file "$(git rev-parse --show-toplevel)/.claude/skills/plan-detailed/assets/review_prompt.md" \
  --out <plan-path>_reviews.md
```

On stale/missing frontier-model cache, surface via `AskUserQuestion` with `[run discovery now, skip review this run, abort]`.

Tell the user: "Review written to `<path>_reviews.md`. Agreements between Gemini and Codex are real signal; divergences are context."

### Step 6 — ExitPlanMode

Plan doc is the approval surface.

### Step 7 — Close-out: Commit artifact (clean-tree guarantee)

After `ExitPlanMode` approval, before exiting:

```bash
git add plans/detailed-<slug>-<YYYYMMDD-HHMM>.md
# Plus the _reviews.md sibling if --review-external produced one.
git commit -m "chore(plan): detailed plan for <short task summary>"
```

`git status` must be clean. On dirty outside the skill's artifacts, surface via `AskUserQuestion` with `[commit as chore, stash, abort]`.

### Step 8 — Close-out: Reflection + Handoff

Resolve paths:

```bash
REFLECTION_PATH=$(python3 ~/.claude/skills/_shared/next_reflection_path.py plan-detailed)
HANDOFF_PATH=~/.claude/skills/plan-detailed/handoff.md
SKILL_MD=~/.claude/skills/plan-detailed/SKILL.md
```

Spawn ONE close-out agent on the `frontier` tier. It writes both files via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "plan-detailed-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # plan-detailed reflection — <ISO>

      ## What worked
      - <bullet about the SKILL's instructions>

      ## Improvements to SKILL.md
      - <specific, actionable change>

      Do NOT reference this project or the specific plan produced.

    FILE 2 — REPO-SPECIFIC handoff → write to <HANDOFF_PATH>

      ---
      from: plan-detailed
      timestamp: <ISO>
      artifact: <absolute path to plan doc + reviews if any>
      ---

      # Handoff for the implementer

      ## Summary
      <1–2 sentences: task, plan doc path, rough scope.>

      ## Key decisions made this run
      - <numbered, one line each>

      ## Open items for the implementer
      - <concrete, actionable — e.g., "confirm the refresh-token TTL
        matches the session policy in auth-config.ts">

      ## Repo-specific gotchas surfaced
      - <quirks discovered during research — patterns to match, files
         not to touch>

      ## Files the implementer will touch
      - <enumerated from the plan>
  """
)
```

Exit message to user:

> Plan written to `<plan-path>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<HANDOFF_PATH>`.
>
> Recommended next step: run `/clear` to reset your context window, then implement the plan. The implementing agent can read the handoff automatically.

## Plan document template

Emit this structure verbatim.

```markdown
# Detailed plan: <one-line task summary>

## Task
<task statement — from args or conversation synthesis>

## Research summary
<2–5 sentences synthesized from Explore teammates. Cite the files,
utilities, and patterns worth reusing.>

## Changes

### `<file-path>` (<create|modify|delete>)
- `<entity>` — <add|modify|delete> — <reason>
- `<entity>` — <add|modify|delete> — <reason>

### `<file-path>` (<create|modify|delete>)
…

## Documentation impact
- `<doc-path>` — <add|modify> — <reason>
- …

(If no docs need changes: `None — internal refactor, no doc footprint.`)

## Dependencies & order
<Which changes must happen first. Name blocking relationships.>

## Verification
<Concrete shell/test commands, behaviors, edge cases. Runnable.>

## Acceptance criteria
- [ ] <testable assertion>
- [ ] <testable assertion>
```

## Teamwork posture

- **Main thread = orchestrator.** Brief Explore teammates, synthesize, write the plan, commit. Do not `Grep`/`Read` source files directly during Step 2 — that's the Explore teammates' job.
- **Parallel-by-default.** Step 2 launches all Explore teammates in a single message.
- **Name every teammate.** Set `name:` on every `Agent` call.

## Reference files

- `assets/review_prompt.md` — used by `--review-external` to critique the plan via Gemini + Codex.
