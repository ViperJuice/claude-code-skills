---
name: skill-editor
description: "Apply an improvement plan produced by skill-improvement-planner to the relevant SKILL.md files. Archives the reflection files consumed by the plan so they aren't re-aggregated next cycle. Use when the user says 'apply the skill improvement plan', 'update the skills with the aggregated feedback', 'run the skill editor', or follows a skill-improvement-planner run. Ingests the plan at ~/.claude/skills/skill-improvement-planner/plans/plan-v<N>-<ISO>.md (or the path in the predecessor handoff), applies each recommendation via a frontier-tier agent, mirrors edits across dotfiles and team-skills repos where applicable, and commits each edited repo."
---

# skill-editor

Applies the plan produced by `skill-improvement-planner` to the target SKILL.md files. Interprets each recommendation, edits the file, mirrors across repos if the skill is dual-homed, and archives the reflections the plan consumed so they won't drive another pass.

## When to use

- Right after a `skill-improvement-planner` run. Its handoff points here.
- The user names a plan file explicitly and wants it applied.

## When NOT to use

- No plan file exists → run `/skill-improvement-planner` first.
- User wants to edit a skill's instructions by hand → this skill is for applying a structured plan, not arbitrary edits.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<plan-path>` | no | Absolute path to a plan produced by `skill-improvement-planner`. Default: read `~/.claude/skills/skill-improvement-planner/handoff.md`'s `artifact:` field. |
| `--dry-run` | no | Parse the plan and print what WOULD change without editing any files. |
| `--no-push` | no | Commit but skip `git push`. Default: push. |
| `--no-mirror` | no | Edit dotfiles only; skip team-repo mirror. |

## Workflow

### Step 0 — Resolve plan path

If `<plan-path>` passed, use it verbatim.

Else read `~/.claude/skills/skill-improvement-planner/handoff.md`:

- Validate YAML frontmatter `from: skill-improvement-planner`. On mismatch → flag via `AskUserQuestion` with `[use anyway, provide plan path, abort]`.
- Validate timestamp < 7 days old. On staleness → same AskUserQuestion.
- Extract `artifact:` → this is the plan path.

If neither source yields a path, stop and ask the user to provide one via `AskUserQuestion`.

### Step 1 — Parse the plan

Read the plan file. Extract:

- **Frontmatter** — YAML block at top. Fields:
  - `from: skill-improvement-planner` (validate)
  - `timestamp:`
  - `min_reflections:`
  - `reflections_consumed:` — list of absolute paths (this is the archival worklist)
- **Recommendations per skill** — `### <skill-name>` subheadings under `## Recommendations by skill`. For each subheading, collect every `**Change**:` bullet with its `**Rationale**:` and `**Supporting reflections**:` lines.
- **Cross-cutting recommendations** — same structure under `## Cross-cutting recommendations`; these name multiple skills each.
- **Speculative / low-confidence notes** — record but do not act on.
- **Contradictions surfaced** — record and print to user; do not auto-resolve. If contradictions exist, surface before applying and offer to skip affected recommendations.

Build a per-skill work list. Each entry: `(skill_name, change_text, rationale, supporting_reflection_versions)`.

### Step 2 — Validate

- Every `reflections_consumed` path exists on disk. If any are missing → warn the user; skip them for archival but continue with edits.
- Every target skill named in recommendations has a SKILL.md at `~/.claude/skills/<skill>/SKILL.md` (resolving the symlink). If missing → fail that recommendation, note in the outcome report.
- Detect double-application: if the plan's timestamp is already recorded in `~/.claude/skills/skill-editor/applied-plans.log`, ask via `AskUserQuestion` with `[apply again, abort]` — applying twice is usually wrong.

On `--dry-run`, skip to Step 7 (print the worklist and exit).

### Step 3 — Apply recommendations (per-recommendation frontier-tier Agent)

For each recommendation, spawn an Agent to apply it. Resolve `<frontier>` from the `execute-phase` Model tiers table.

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "skill-editor-<skill>-<seq>",
  prompt: <contents of assets/editor_prompt.md>
        + "\n\n# Target skill\n<skill-name>"
        + "\n\n# Target SKILL.md path\n<absolute path>"
        + "\n\n# Change to apply\n<change text>"
        + "\n\n# Rationale\n<rationale text>"
)
```

The Agent has Read/Edit/Write tools. It reads the target SKILL.md, applies the specified change in directive-only style (preserving house style), and reports outcome JSON: `{applied: bool, files_modified: [path], diff_summary: "...", error: "..."}`.

Track per-recommendation outcomes. Don't stop on individual failures — collect them all for the final report.

Dispatch in parallel where safe: multiple recommendations targeting different skills can run concurrently. Multiple recommendations targeting the **same** skill must serialize (sequential Edit calls to the same file can conflict).

### Step 4 — Mirror to team repo (if `--no-mirror` not set)

For each successfully edited dotfiles SKILL.md at `~/code/dotfiles/claude-config/skills/<skill>/`, check whether a counterpart exists in `~/code/claude-code-skills/` (under `planning-chain/`, `efficiency-kit/`, or `meta/`).

- If counterpart exists → `cp` the edited SKILL.md over.
- If absent → note in the outcome report; the skill either isn't shipped to the team repo, or is at a non-standard path the mirror didn't find.

Skip mirror for scripts in `_shared/` (they map to `tools/` in the team repo); mirror those only if explicitly edited — same pattern via cp.

### Step 5 — Archive consumed reflections

Per the plan's archival directive. For each reflection in `reflections_consumed`:

1. Collect every recommendation that cited this reflection (via `**Supporting reflections**`).
2. If ALL citing recommendations succeeded → archive the reflection:
   ```bash
   mkdir -p <reflection-parent>/archive
   mv <reflection> <reflection-parent>/archive/<basename>
   ```
3. If ANY citing recommendation failed → leave the reflection in place so next cycle can reconsider.

A reflection cited by zero surviving recommendations (e.g., its theme was rejected as repo-specific) is still archived — it's been considered.

### Step 6 — Commit + push

Dotfiles:

```bash
cd ~/code/dotfiles
git add -A claude-config/skills/
git commit -m "chore(skills): apply improvement plan <plan-timestamp>

Applied N of M recommendations from <plan-path>. See the plan file for
per-skill details. Reflections consumed this run moved to each skill's
reflections/archive/ subdirectory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Team repo (if edits landed there):

```bash
cd ~/code/claude-code-skills
git add -A
git commit -m "chore: mirror skill edits from dotfiles improvement plan <plan-timestamp>"
```

`git push` in both unless `--no-push`.

Append the plan's timestamp + path to `~/.claude/skills/skill-editor/applied-plans.log` so Step 2's double-apply check has state to read.

### Step 7 — Close-out (standard pattern)

Resolve paths:

```bash
REFLECTION_PATH=$(python3 ~/.claude/skills/_shared/next_reflection_path.py skill-editor)
HANDOFF_PATH=~/.claude/skills/skill-editor/handoff.md
SKILL_MD=~/.claude/skills/skill-editor/SKILL.md
```

Spawn ONE close-out agent on the `frontier` tier. It writes both files via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "skill-editor-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # skill-editor reflection — <ISO>

      ## What worked
      - <bullet about the SKILL's instructions>

      ## Improvements to SKILL.md
      - <specific, actionable change>

      Do NOT reference this project or the specific plan applied.

    FILE 2 — REPO-SPECIFIC handoff → write to <HANDOFF_PATH>

      ---
      from: skill-editor
      timestamp: <ISO>
      artifact: <plan path that was applied>
      ---

      # Handoff

      ## Summary
      <applied N of M recommendations from the plan; archived K reflections.>

      ## Key decisions made this run
      - <which recommendations were skipped and why, e.g., contradictions
         surfaced, target skill missing, agent error>

      ## Files changed this run
      - <SKILL.md paths + commit SHAs>

      ## Next skill
      - Usually no immediate next skill — the pipeline has closed the loop.
        A new `/phase-roadmap-builder` run will pick up the improved
        instructions naturally.
  """
)
```

Exit message to user:

> Applied `<N>` of `<M>` recommendations from `<plan-path>`.
> `<K>` reflections archived.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<HANDOFF_PATH>`.
>
> Recommended next step: run `/clear`. The improved skill instructions take effect on the next pipeline invocation.

## Failure policy

- **Agent can't apply an edit** → mark recommendation failed, preserve its supporting reflections, continue with others.
- **Target skill missing** → mark failed, preserve its reflections, continue.
- **Plan file malformed** → surface to user via `AskUserQuestion`, offer abort.
- **Contradictions in plan** → print both sides, ask user which (or neither) to apply, continue with the rest.
- **Commit or push fails** → report to user; leave the working tree as-is for inspection.

## Reference files

- `assets/editor_prompt.md` — the full prompt given to each edit Agent.
