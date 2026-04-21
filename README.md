# claude-code-skills

A parallel-execution planning chain and efficiency kit for Claude Code Agent Skills.

This repo is the Claude Code port of the workflow skills maintained in `ViperJuice/dotfiles`. It is intentionally framework-specific: install these skills only into `$HOME/.claude/skills`, not into a shared `.agents/skills` directory.

## Migration note

The workflow skills now use framework-prefixed names. Older Claude Code sessions may remember short names such as `plan-phase`, `execute-phase`, or `skill-editor`; the current names are `claude-plan-phase`, `claude-execute-phase`, and `claude-skill-editor`. Use the prefixed names so sessions re-vector to the correct harness-specific implementation.

## Planning chain

```text
conversation or spec
        │
        ▼
/claude-phase-roadmap-builder   ->   specs/phase-plans-v<N>.md
        │
        ▼
/claude-plan-phase <ALIAS>      ->   plans/phase-plan-v<N>-<alias>.md
        │
        ▼
/claude-execute-phase <alias>   ->   implementation guided by the lane plan
```

Use `/claude-plan-detailed` by exception for one bounded change where the full roadmap/phase/lane pipeline is too heavy. Use `/claude-task-contextualizer` before writing delegated-agent briefs.

## Quick start

```bash
git clone https://github.com/ViperJuice/claude-code-skills
cd claude-code-skills
./install.sh
```

Then start a Claude Code session and invoke the skills by name, for example:

```text
/claude-phase-roadmap-builder
/claude-plan-phase P1
/claude-execute-phase p1
```

## Contents

- `planning-chain/` - roadmap, phase planning, execution, detailed planning, and task-contextualizer skills.
- `meta/` - `skill-improvement-planner` and `skill-editor` for reflection-driven skill maintenance.
- `efficiency-kit/` - short utility skills that reduce repeated reads, unsafe edits, search thrashing, and predictable verification failures.
- `runtime-state.md` - the repo/branch/run-isolated reflection and handoff contract.
- `_template/` - baseline style for new skills.

## Runtime state

Runtime artifacts are isolated by repo hash, branch slug, and run id. Handoffs use `latest.md` pointers under the framework-private skill root. See [CONSIDERATIONS.md](./CONSIDERATIONS.md) and [runtime-state.md](./runtime-state.md).

## Contributing

Keep skills directive-first and framework-specific. If a workflow instruction names a harness tool, runtime path, delegation primitive, or approval model, it belongs in the framework-specific repo for that harness.
