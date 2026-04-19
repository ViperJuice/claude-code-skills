---
name: phase-roadmap-builder
description: "Produces or extends a multi-phase roadmap spec (`specs/phase-plans-v<N>.md`) that `/plan-phase` can ingest. Use when the user wants to turn the current conversation's plan, an architecture discussion, or a pointed-at markdown spec into a phased roadmap — phrases like 'build a phase roadmap', 'turn this into a phased plan', 'create a multi-phase spec', 'add a phase to the roadmap', 'extend the phase plan', or after a long planning conversation when the user says 'ok let's formalize this'. Also triggers when the user wants to APPEND phases to an existing roadmap without editing prior phases. Designs for maximum parallelism: fewer phases, more parallel lanes per phase, tight early interface freezes."
---

# phase-roadmap-builder

Produces the `specs/phase-plans-v<N>.md` roadmap that `/plan-phase` consumes. Digests the prior conversation and any markdown files the user points at, then writes a phased roadmap whose structure maximizes parallel execution. Creates a new roadmap if none exists; appends phases (never edits existing phases) if one does.

## When to use

- User wants to formalize a conversation's plan into a phased roadmap.
- User points at a markdown spec and asks to "phase it."
- User wants to add phases to an existing `specs/phase-plans-v*.md`.
- User wants the output to be ingestible by `/plan-phase`.

## When NOT to use

- Single-phase or single-concern change → use `/plan-detailed`.
- Lane-level planning for one phase → the user wants `/plan-phase`, not this skill.
- Pure research / "how does X work" → use `Agent(subagent_type: "Explore")` directly.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<spec-path>` | no | Path to an input markdown spec to fold into the roadmap. Optional; conversation context is the primary source. |
| `--output <path>` | no | Override the default output path. Default: `specs/phase-plans-v<N>.md` at the repo root. |
| `--append` | no | Force append mode even if the resolved output path is new (rare). |
| `--review-external` | no | After writing the roadmap, run Gemini + Codex CLIs in parallel to review it. Requires `gemini` and `codex` installed and authenticated. Produces a `_reviews.md` sibling file. |

## Mode detection

Resolve the output path in this order:
1. `--output` override.
2. Glob `specs/phase-plans-v*.md`; pick the highest version.
3. If none found, default to `specs/phase-plans-v1.md` (create mode).

If the resolved path exists → **append mode**. Otherwise → **create mode**.

## Deferred tool preloading

Load tools used later in a single query:

```
ToolSearch(query: "select:AskUserQuestion,ExitPlanMode")
```

## Workflow — create mode

### Step 0 — Read predecessor handoff (if present)

Check for `~/.claude/skills/execute-phase/handoff.md`. If it exists, `Read` it in full — a prior `/execute-phase` run may have left context useful for the next roadmap (completed phases, decisions made, gotchas discovered mid-execution). Treat its contents as additional input to Step 1.

If the handoff's metadata header is older than 7 days or the `from:` field is not `execute-phase`, flag via `AskUserQuestion` with `[use anyway, ignore, abort]`.

If absent, proceed — this run is standalone.

### Step 1 — Gather inputs

Sources (permissive but bounded):

1. The current conversation's user turns, assistant plans, and any committed architectural decisions.
2. The spec path argument, if supplied — `Read` it in full.
3. `CLAUDE.md` and `AGENTS.md` at the repo root, if present.
4. Markdown files the user has explicitly named anywhere in the conversation.

Do not grep the repo for additional material. If context is insufficient, stop and ask the user via `AskUserQuestion` — a thin roadmap is worse than one more question.

### Step 1a — Ensure docs catalog exists

Run:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py"
```

Scaffolds `.claude/docs-catalog.json` if absent; no-op if already present. The catalog drives the `SL-docs` lane that `plan-phase` constructs for every phase. Existence matters more than content at this stage — the catalog will be refreshed (`--rescan`) by each `SL-docs` lane as the roadmap executes.

### Step 2 — Synthesize top-of-document sections

Fill these sections before touching phase decomposition:

- **Context** — one-page synthesis: the problem, current state, the thesis of the refactor/build.
- **Architecture North Star** — ASCII diagram of the target architecture if the work is structural. Omit if not load-bearing.
- **Assumptions (fail-loud if wrong)** — numbered list of preconditions; each is something that, if false, invalidates the plan.
- **Non-Goals** — explicit deferrals. Use to cut scope; silence here causes scope creep later.
- **Cross-Cutting Principles** — rules that apply across every phase (e.g., "single-writer-per-SQLite-file", "no mocks in integration tests").

### Step 3 — Decompose into phases (parallelization-maximizing)

Apply the heuristics in `references/parallelization-heuristics.md` in order:

1. **Phases are serial checkpoints; lanes within a phase are parallel.** Minimize total wall time by minimizing phase count and maximizing lanes per phase.
2. **A phase boundary exists only at a necessary interface freeze.** If two bodies of work share no freeze dependency and have disjoint files, they are sibling lanes inside one phase, not sequential phases.
3. **Prefer narrow, early freezes.** Each phase's `Produces:` lists the tightest contract that unblocks the next phase.
4. **Split fat phases into parallel sibling phases** when they contain independent subtrees (the `P6A || P6B` pattern).
5. **Every phase decomposes into ≥2 lanes** unless it is a preamble / interface-freeze-only phase (Phase 1 / P0 are the common exceptions). Single-lane phases are a code smell — merge or split.
6. **Each phase's `Scope notes` lists explicit parallelism hints**: suggested lane count, candidate disjoint-file partitions, and any single-writer files that would serialize lanes if ignored.
7. **Identify cross-phase parallelism.** Phases with no shared ancestor in the DAG can run concurrently. Call these out in the DAG.

### Step 4 — Draft Top Interface-Freeze Gates

For each inter-phase freeze, write one `IF-0-<ALIAS>-<N>` entry naming the concrete symbol, schema, or endpoint being frozen. Narrow is better — a gate that names "a dataclass with fields `{a, b, c}`" lets downstream lanes start; "the data model" does not.

### Step 5 — Write each phase section

Use the skeleton from `references/roadmap-template.md`. Each phase MUST contain:

- `**Objective**` — one or two sentences.
- `**Exit criteria**` — checkbox list (`- [ ] …`), each item testable.
- `**Scope notes**` — lane decomposition hints, parallelism advice, edge cases.
- `**Non-goals**` — explicitly deferred.
- `**Key files**` — paths the phase touches.
- `**Depends on**` — upstream phase aliases, or `(none)` for roots.
- `**Produces**` — `IF-0-<ALIAS>-<N>` entries for freezes this phase publishes.

Phase heading format: `### Phase N — <Name> (<ALIAS>)`. Alias is short, mnemonic, alphanumeric (`P1`, `P2A`, `P2B`, `P3`, …). It becomes the filename token in `phase-plan-v<N>-<alias>.md`.

### Step 6 — Build Phase Dependency DAG

Render as ASCII. Show serial arrows (`P1 → P2A → P2B`) and parallel branches (`P6A  parallel after P1`). This is the source of truth for the wall-clock schedule.

### Step 7 — Write Execution Notes and Verification

- **Execution Notes**: how to invoke `/plan-phase <ALIAS>` for each phase, and `/execute-phase <alias>` for each. Call out which phases can be planned and executed concurrently.
- **Verification**: end-to-end shell commands that prove the whole roadmap delivered its goals. These are the integration tests the user will run after the last phase merges.

### Step 8 — Validate

Run:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/phase-roadmap-builder/scripts/validate_roadmap.py" <output-path>
```

Fix every reported error before handing off. The validator enforces: required headings, alias uniqueness, DAG acyclicity, IF-gate ID format, Depends-on correctness, and the ≥2-lanes-per-phase rule (with a preamble-phase escape hatch).

### Step 8.5 — External CLI review (only if `--review-external`)

After the roadmap is written and validated, run:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/review_with_cli.py" \
  --artifact <output-path> \
  --prompt-file "$(git rev-parse --show-toplevel)/.claude/skills/phase-roadmap-builder/assets/review_prompt.md" \
  --out <output-path>_reviews.md
```

If the frontier-model cache is empty, the script prints the discovery prompt to stderr. Surface to the user via `AskUserQuestion` with options `[run discovery now, skip review this run, abort]`.

Tell the user: "Review written to `<output-path>_reviews.md`. Agreements between Gemini and Codex are real signal; divergences are context."

### Step 9 — Write and exit

Write the roadmap to the resolved output path. Call `ExitPlanMode` — the roadmap is the approval surface. After approval, the hand-off message is: "Run `/plan-phase <ALIAS>` for each phase. Phases with no shared DAG ancestor (e.g., `<list them>`) can be planned concurrently."

## Workflow — append mode

### Step A1 — Read existing roadmap

`Read` the existing `specs/phase-plans-v*.md`. Extract:

- The highest `## Phase N` number.
- The full existing alias set.
- The highest `IF-0-<ALIAS>-<N>` sequence number per phase.
- The existing Phase Dependency DAG edges.

### Step A2 — Identify new phases from context

Apply Step 1 above to gather new context. Then apply Step 3's heuristics to decide which new phases are needed. Do not modify existing phases — additions only. If the new context implies that an existing phase is wrong, stop and tell the user; do not silently edit.

### Step A3 — Assign numbers and aliases

- Phase numbers continue strictly increasing (highest existing + 1, +2, …).
- New aliases must not collide with existing ones. Extend the convention (`P8`, `P9`, or `P4B` if it branches from an existing `P4`).

### Step A4 — Wire Depends on

For each new phase, list every existing phase it depends on by alias. A new phase that depends on nothing existing is either a new root (rare — possible when introducing a parallel initiative) or misidentified.

### Step A5 — Splice into the document

Insert new phase sections under `## Phases`, after the last existing phase, before `## Execution Notes`. Update two other sections:

- `## Phase Dependency DAG` — add the new nodes and edges.
- `## Top Interface-Freeze Gates` — append any new `IF-0-<ALIAS>-<N>` entries.

Leave `## Context`, `## Architecture North Star`, `## Assumptions`, `## Non-Goals`, `## Cross-Cutting Principles`, `## Execution Notes`, and `## Verification` alone unless the new phases invalidate a stated assumption — in which case surface the conflict to the user and stop.

### Step A6 — Validate + exit

Same as Step 8, Step 8.5 (if `--review-external`), and Step 9. Validator must pass.

## Output contract

The output file must match `references/roadmap-template.md` structurally. `plan-phase` parses stable headings (`## Context`, `### Phase N — <Name>`, `**Objective**`, `**Exit criteria**`, etc.) by regex; non-standard formatting breaks downstream.

## Hand-off

After approval, invoke `/plan-phase <ALIAS>` per phase. Phases with no shared ancestor in the DAG can be planned and executed in parallel — note which ones in the hand-off message. The wall-clock critical path is the longest DAG path through the roadmap.

## Close-out — Commit artifact (clean-tree guarantee)

After `ExitPlanMode` is approved, before exiting:

1. `git add specs/phase-plans-v<N>.md` (and the `_reviews.md` sibling if `--review-external` produced one).
2. `git commit -m "chore(roadmap): <create|append phases>"`.
3. Run `git status`. If dirty outside the skill's own artifacts, surface via `AskUserQuestion` with `[commit the remaining changes as chore, stash, abort]`.

## Close-out — Reflection + Handoff

After artifacts are committed, resolve paths:

```bash
REFLECTION_PATH=$(python3 ~/.claude/skills/_shared/next_reflection_path.py phase-roadmap-builder)
HANDOFF_PATH=~/.claude/skills/phase-roadmap-builder/handoff.md
SKILL_MD=~/.claude/skills/phase-roadmap-builder/SKILL.md
```

Spawn ONE close-out agent using the `frontier` tier (resolve via `execute-phase` Model tiers table). It writes BOTH files directly via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "phase-roadmap-builder-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files, written via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # phase-roadmap-builder reflection — <ISO timestamp>

      ## What worked
      - <bullet, about the SKILL's instructions>

      ## Improvements to SKILL.md
      - <specific, actionable change to the instructions>

      Do NOT reference this project, codebase, filenames, or domain. Feedback
      is about how the skill's instructions performed, for a future meta-skill
      that digests reflections across runs.

    FILE 2 — REPO-SPECIFIC handoff → write to <HANDOFF_PATH> (overwrites
    any prior handoff from this skill)

      ---
      from: phase-roadmap-builder
      timestamp: <ISO>
      artifact: <absolute path(s) to roadmap spec + any reviews written>
      ---

      # Handoff for the next skill

      ## Summary
      <2-3 sentences: what was produced, where to find it.>

      ## Key decisions made this run
      - <numbered, one line each>

      ## Open items for the next skill
      - <concrete, actionable — e.g., "Lane SL-3 expects the
        plugins_for(repo_id) signature from IF-0-P3-1; verify it
        before planning P4">

      ## Repo-specific gotchas surfaced
      - <things that surprised this run; quirks of THIS codebase>

      ## Files committed this run
      - <path> @ <commit sha>

      ## Next skill's likely scope
      - <best-effort forecast of which files/paths the next skill will touch>
  """
)
```

After the agent returns, print to the user:

> Roadmap written to `<spec-path>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<HANDOFF_PATH>`.
>
> Recommended next step: run `/clear` to reset your context window, then invoke `/plan-phase <ALIAS>`. The next skill reads the handoff automatically.

## Reference files

- `references/roadmap-template.md` — exact structural skeleton to emit.
- `references/parallelization-heuristics.md` — extended rules for edge cases in phase/lane decomposition.
