# claude-code-skills

A set of [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) skills that turn a conversation about architecture into parallel, worktree-isolated execution — with an optional second-opinion review from Gemini and Codex CLIs.

## The planning chain

```
conversation or spec
        │
        ▼
/phase-roadmap-builder   →   specs/phase-plans-v<N>.md
        │
        ▼ (once per phase)
/plan-phase <ALIAS>      →   plans/phase-plan-v<N>-<alias>.md  (+ TaskCreate per lane)
        │
        ▼
/execute-phase <alias>   →   auto-merged lanes on main
```

Each skill is self-contained and runs in **Claude Code's plan mode** where applicable. Phases serialize on interface freezes; lanes inside a phase are dispatched in parallel via worktree-isolated teammates. The roadmap format is designed so adjacent phases with no shared DAG ancestor can be planned and executed concurrently.

## Quick start

```bash
git clone https://github.com/ViperJuice/claude-code-skills
cd claude-code-skills
./install.sh                 # installs symlinks under ~/.claude/skills/
# Or: ./install.sh .claude   # installs under ./.claude/skills/ for a specific project
```

Then in any Claude Code session:

```
/phase-roadmap-builder        # start a new roadmap
/plan-phase P1                # plan phase P1's lanes
/execute-phase p1             # build it
```

## What's in the box

- **planning-chain/** — the four flagship skills: `phase-roadmap-builder`, `plan-phase`, `execute-phase`, `task-contextualizer`.
- **tools/** — shared Python utilities used by the planning skills: `frontier_model_discovery.py` (dynamic Gemini/Codex model resolution with 24h cache), `review_with_cli.py` (parallel cross-CLI review), `next_reflection_path.py` (incrementing reflection-log filename).
- **efficiency-kit/** — seven short skills that prevent the most common token-wasting anti-patterns: `file-read-cache`, `safe-edit`, `batch-verify`, `smart-search`, `diagnose-bash-error`, `validate-before-bash`, `detect-environment`.
- **_template/** — the house style for writing your own skills: imperative, directive-only, no war stories.

## Prerequisites, custom tools, and nuances

See [CONSIDERATIONS.md](./CONSIDERATIONS.md). In short:

- **Claude Code** is the target harness. The skills use Claude Code's `Agent`, `TeamCreate`, `TaskCreate`, `EnterWorktree`, `SendMessage`, `AskUserQuestion`, `ExitPlanMode`, and `ToolSearch` tools. Anyone on Claude Code has these.
- **External CLI review (`--review-external`, optional)** requires `gemini` and `codex` CLIs installed and authenticated.
- **PMCP** is a custom open-source MCP gateway that provides progressive disclosure and on-demand MCP server provisioning. Required for `execute-phase`'s browser-verification step and for the `frontier_model_discovery` research pattern.

## Design principles

The skills follow five rules worth calling out so forks preserve them:

1. **Directive-only instructions.** No war stories, no stats, no narrative justification. Rules in imperative form. Reasons stated in one clause, not paragraphs. The `_template/` directory codifies this.
2. **Maximum parallelism.** Phases are serial checkpoints; lanes within a phase are parallel. The roadmap decomposition rules push for fewer phases with more lanes and the tightest possible early interface freezes.
3. **Clean-tree close-out.** Every artifact-producing skill commits its output before exiting, so the next skill in the chain starts with a clean tree.
4. **Repo-agnostic reflection corpus.** Each artifact-producing skill writes a reflection to `~/.claude/cache/reflections/<skill>/<skill>-reflection-v<N>.md` after close-out — feedback strictly about the skill's *instructions*, never about the repo it was run in. The long-term goal is a meta-skill that digests this corpus across skills and proposes improvements.
5. **External review over multi-harness consensus.** Claude authors the plan. Gemini and Codex critique it in parallel. Agreements get attention; divergences are context for the human.

## Contributing

Forks are encouraged. If you extend the skills, keep the directive-only style and the close-out pattern (clean-tree commit + repo-agnostic reflection). The `_template/SKILL.md` has the house rules.
