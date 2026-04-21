# Considerations

## Target harness

This repo targets **Claude Code**. Do not install these workflow skills into a different coding-agent harness. The skill names are prefixed with `claude-` to prevent cross-framework ambiguity.

Claude Code-specific workflow skills may reference Claude Code tools such as Agent, TeamCreate, TaskCreate, AskUserQuestion, ExitPlanMode, and ToolSearch.

## Runtime state

The old flat handoff/reflection layout is obsolete. Current workflow skills use the contract in `runtime-state.md`:

- `repo_hash = sha256(realpath(git rev-parse --show-toplevel))[:8]`
- `branch_slug = sanitized current branch`, or `detached-<short-sha>` when detached
- `run_id = <UTC YYYYMMDDTHHMMSSZ>-<short random suffix>`
- reflections: `$HOME/.claude/skills/<skill>/reflections/<repo_hash>/<branch_slug>/<run_id>.md`
- handoffs: `$HOME/.claude/skills/<skill>/handoffs/<repo_hash>/<branch_slug>/<run_id>.md`
- latest handoff pointer: `$HOME/.claude/skills/<skill>/handoffs/<repo_hash>/<branch_slug>/latest.md`

Downstream skills must read `latest.md`, validate `from`, `repo`, `repo_root`, `branch`, `branch_slug`, `commit`, `run_id`, and `artifact`, and ignore mismatched handoffs unless the user explicitly asks to reuse cross-branch or cross-repo state.

## Architecture note for old sessions

If a running agent remembers unprefixed Claude-era names (`phase-roadmap-builder`, `plan-phase`, `execute-phase`, `plan-detailed`, `task-contextualizer`, `skill-improvement-planner`, `skill-editor`), redirect it to the prefixed skill in this repo. For example, use `claude-plan-phase` instead of `plan-phase`.

## Skill groups

- `planning-chain/` contains the main roadmap -> plan -> execute loop.
- `meta/` contains the reflection aggregation and skill editing loop.
- `efficiency-kit/` contains passive utility skills. These are intentionally short and should not write runtime state.

## Installation target

Default install target: `$HOME/.claude/skills`.

These framework-specific skills are intentionally not installed into `~/.agents/skills`. That directory should be reserved for future skills that are genuinely platform-neutral.

## Style

Keep instructions directive-first. Avoid long narrative justification, war stories, or benchmark claims. If behavior differs between frameworks, do not hide that behind a generic skill; make an explicit framework-specific port.
