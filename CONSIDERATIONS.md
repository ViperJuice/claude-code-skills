# Considerations, prerequisites, and nuances

This document has four parts:

1. **Global** — prerequisites that apply to everything (target harness, custom tool dependencies, writing style).
2. **The pipeline** — the AI-driven-engineering loop (`phase-roadmap-builder` → `plan-phase` → `execute-phase`, with `task-contextualizer` as a supporting checklist) and every consideration specific to running it.
3. **Meta-skills** — the self-improvement loop (`skill-improvement-planner` → `skill-editor`) that reviews accumulated reflections and updates the pipeline skills' instructions over time.
4. **Standalone skills** — the efficiency-kit. Unrelated to the pipeline. Short passive rules that load into context and steer the agent away from common anti-patterns.

---

# Part 1 — Global

## Target harness

The skills are written for **[Claude Code](https://docs.claude.com/en/docs/claude-code/overview)**. They use these Claude Code-specific tools:

- `Agent` (with `subagent_type`, `team_name`, `isolation`, `model`, `name`, `prompt`)
- `TeamCreate`, `TaskCreate`, `TaskUpdate`, `TaskStop`, `TaskList`
- `EnterWorktree`, `ExitWorktree`
- `SendMessage`
- `AskUserQuestion`, `ExitPlanMode`
- `ToolSearch` (for deferred tool loading)

Codex, Gemini CLI, and OpenCode are **not** supported as host harnesses — they don't have equivalent primitives for team coordination, worktree isolation, or plan-mode approval. They're used only as *external CLIs* for the optional review step (Part 2).

## Custom tool dependencies

### PMCP — required for a few pipeline steps

[`PMCP`](https://github.com/ViperJuice/pmcp) is an open-source MCP gateway that aggregates many MCP servers behind progressive disclosure: tools aren't loaded until a skill asks for them, which saves context. The pipeline uses PMCP for:

- **`execute-phase` browser verification** — Playwright via `pmcp_invoke(tool_id="playwright::browser_navigate", ...)`.
- **Frontier model discovery** (for optional CLI review) — BrightData search + scrape, fetch, and Context7 doc lookup.

Minimum install: follow PMCP's README. A minimal `~/.pmcp.json` registers Playwright and Context7; PMCP can provision the rest on demand via `pmcp_request_capability`. If your team has a different MCP gateway or a direct Playwright MCP install, `execute-phase` will adapt — it says "use Playwright via whatever MCP you have configured," not "use PMCP specifically."

### Code-Index-MCP — optional

[`Code-Index-MCP`](https://github.com/ViperJuice/Code-Index-MCP) is a local-first code indexer (symbol search + optional semantic search across 48 Tree-sitter languages). Useful for large repos during `plan-phase` reconnaissance, but not required. PMCP can auto-provision it.

### Other

No other custom tooling assumptions. Standard `git`, `python3`, and `bash`. All Python scripts in `tools/` are stdlib-only.

## Directive-only writing style

See `_template/SKILL.md`. Short version: imperative instructions, rationale in one clause, no war stories, no stats, no narrative justification. The description field in YAML frontmatter carries triggering info only — not "this skill prevents 47% of retry failures." Prose like that tends to leak into skill bodies and bloats context. Every skill in this repo is cleaned to this style; contributions should follow it.

---

# Part 2 — The pipeline

The four skills below compose into a loop that takes a conversation about architecture and turns it into parallel, worktree-isolated execution. Run phase by phase; the execute-phase handoff feeds the next plan-phase so you can keep going through the roadmap without context clutter.

```
phase-roadmap-builder   →   specs/phase-plans-v<N>.md
        │
        ▼ (once per phase, with /clear between)
plan-phase <ALIAS>      →   plans/phase-plan-v<N>-<alias>.md
        │
        ▼
execute-phase <alias>   →   auto-merged lanes on main
        │
        └──► feeds back into plan-phase <next-alias>
             (or phase-roadmap-builder if extending the roadmap)
```

## The pipeline skills

- **phase-roadmap-builder** — Turns a conversation (or a pointer to a markdown spec) into `specs/phase-plans-v<N>.md`, a multi-phase roadmap consumable by `plan-phase`. Append-mode adds phases to an existing roadmap without editing prior ones. Decomposition rules push for maximum parallelism: fewer phases with more sibling lanes, tight early interface freezes, and explicit cross-phase parallel branches in the DAG.

- **plan-phase** — Takes one phase from the roadmap and decomposes it into swim lanes with disjoint file ownership, lane-level task lists (test → impl → verify), and interface-freeze gates. Emits a `TaskCreate` per lane so the lane DAG is visible in your task pane. With `--consensus`, spawns 2-3 Plan teammates with different architectural framings (minimal / clean / parallel) and synthesizes.

- **execute-phase** — Reads a plan-phase output and drives execution. Spawns one worktree-isolated teammate per lane, dispatches lanes in parallel when dependencies allow, auto-merges each lane on green verify, retries once on failure, halts the phase on second failure. Routes lanes to model tiers (frontier / strong / fast) based on complexity.

- **task-contextualizer** — A checklist, not an active workflow. Loads into context and reminds the agent to include file paths, architecture context, scope boundary, expected output, and related files in every subagent brief. The three active pipeline skills already reference it in their briefing steps; invoke it directly if you're about to write any ad-hoc `Task`/`Agent` call.

## Pipeline considerations

### Model tier table

`planning-chain/execute-phase/SKILL.md` routes lane dispatches by capability tier. The concrete model IDs live in exactly one place — the `## Model tiers` block near the top of that file. When Anthropic ships a new model, edit that table (three lines). Everything else in the skill refers to tier names (`frontier`, `strong`, `fast`).

Current mapping as shipped:

| Tier      | Model              |
|-----------|--------------------|
| frontier  | claude-opus-4-7    |
| strong    | claude-sonnet-4-6  |
| fast      | claude-haiku-4-5   |

### External CLI review (`--review-external`) — optional

Opt-in flag on `plan-phase` and `phase-roadmap-builder`. After the skill writes its artifact, it runs Gemini and Codex **in parallel** through `tools/review_with_cli.py` with a skill-specific review prompt. Both CLIs receive identical input; output lands in a `_reviews.md` sibling file.

Interpretation rule (baked into the output):

> When Gemini and Codex flag the same concern, treat it as real. Divergent comments are context, not verdicts — decide which to act on.

Claude authors; the CLIs critique. This is a review pattern, not a three-way consensus-generation pattern.

**Prerequisites**:
- `gemini` CLI installed (`npm install -g @google/gemini-cli` or equivalent) and authenticated via API key or Google subscription.
- `codex` CLI installed (`npm install -g @openai/codex` or equivalent) and authenticated via API key or ChatGPT subscription.
- Frontier-model cache populated — see below.

If the CLIs aren't installed or authenticated, the pipeline still works — just don't pass `--review-external`. It's strictly additive.

### Frontier model auto-discovery (for external CLIs)

`tools/frontier_model_discovery.py` resolves the current top Gemini and Codex models, caches to `~/.claude/cache/frontier_models.json` for 24 hours. This is how the external-review step avoids hardcoding Gemini/Codex model IDs the way the Anthropic tier table does.

First run of `--review-external` on an empty cache: the script prints a discovery prompt to stderr asking the calling Claude session to execute the four-tool research pattern (BrightData search, BrightData scrape, fetch, Context7 doc lookup) and save the resolved models back via `frontier_model_discovery.py --save '<json>'`. PMCP provides all four tools.

Cache schema:

```json
{
  "gemini_model": "gemini-3.1-pro-preview",
  "gemini_thinking_flag": "",
  "codex_model": "gpt-5.4",
  "codex_effort_flag": "-c model_reasoning_effort=\"xhigh\"",
  "resolved_at": "<ISO timestamp>"
}
```

### Parallelism semantics

- **Phases are serial checkpoints.** Phase N+1 can't start until Phase N's interface freezes (`IF-0-<ALIAS>-<N>`) are closed.
- **Lanes within a phase are parallel.** `execute-phase` dispatches all ready lanes in one message, up to `EXECUTE_MAX_PARALLEL_LANES` (default 2).
- **Cross-phase parallelism.** Phases with no shared ancestor in the DAG (e.g., `P6A` parallel after P1, `P6B` parallel after P4) can run concurrently. `phase-roadmap-builder`'s decomposition heuristics push for this; the DAG in the roadmap doc is the source of truth.
- **Single-writer files** (barrel index files, generated types, migration numbers, nav configs) need an explicit owner-lane declaration in the roadmap's Execution Notes. `plan-phase` won't allow two lanes to both own the same file.

Tuning knob: `EXECUTE_MAX_PARALLEL_LANES` controls the max concurrent lane dispatches per wave. Increase it on machines with lots of RAM and GPU headroom; keep it small if you hit rate limits or merge-conflict churn.

### Documentation drift prevention

Every phase plan includes a mandatory terminal `SL-docs` lane that updates cross-cutting docs (root README, CHANGELOG, CONTRIBUTING, CLAUDE.md / AGENTS.md, `llm*.txt`, `services.json` / `openapi.*`, ARCHITECTURE, DESIGN, `docs/**`, `rfcs/**`, `adrs/**`) after all impl lanes land. No opt-out — phases with no doc impact still run the lane and record that in the commit message.

The lane's inputs are driven by `.claude/docs-catalog.json`, a repo-scoped inventory of documentation surfaces. `phase-roadmap-builder` bootstraps the catalog on first run; each phase's `SL-docs` lane rescans at start to pick up any new doc files created by impl lanes (history preserved). The catalog also tracks `touched_by_phases` per file, so you can see which phase last modified a given doc.

`SL-docs` can also append `### Post-execution amendments` subsections to phase specs — both the current phase and prior phases — when interface freezes turn out empirically wrong mid-execution. This keeps the spec/plan history honest without rewriting earlier phase sections.

Committing `.claude/docs-catalog.json` to git is the intended pattern — it's repo state, not ephemeral.

### Worktree conventions

`execute-phase` isolates each lane's teammate in its own git worktree under `.claude/worktrees/`. The allocator guarantees unique names (`lane-sl-1-<timestamp>-<random>`). After a lane's verify passes, the orchestrator resolves the lane's commit by SHA (never by branch name — the harness sometimes auto-names branches) and merges with `--no-ff`.

Add these to your `.gitignore`:

```
.claude/worktrees/
.claude/execute-phase-state.json
```

The state file holds progress for `--resume` on halt. On clean completion, it's deleted.

### Close-out: reflection + handoff

Every artifact-producing pipeline skill (`phase-roadmap-builder`, `plan-phase`, `execute-phase`) spawns a single frontier-tier Agent at close-out. That Agent reviews the skill's instructions and the execution transcript and writes **two** files into the skill's own directory:

1. **Repo-agnostic reflection** → `~/.claude/skills/<skill>/reflections/<skill>-reflection-v<N>.md`
   - Version `N` increments on each run.
   - Strictly about the skill's *instructions* — no references to the project, codebase, file names, or domain.
   - Two sections: "What worked" and "Improvements to SKILL.md."
   - **Why**: a future meta-skill (not in this repo yet) will digest this corpus across skills and runs and propose concrete SKILL.md changes.

2. **Repo-specific handoff** → `~/.claude/skills/<skill>/handoff.md`
   - Single file, overwritten each run.
   - Concrete: summary of what was produced, key decisions, open items for the next skill, repo-specific gotchas discovered, files committed this run.
   - Starts with a metadata header (`from:` + `timestamp:` + `artifact:`) so the next skill can validate predecessor identity and freshness.

**Chain reads** (Step 0 of each pipeline skill):

- `phase-roadmap-builder` ← `~/.claude/skills/execute-phase/handoff.md` (previous cycle's output, useful for roadmap extensions).
- `plan-phase` ← whichever of `phase-roadmap-builder/handoff.md` or `execute-phase/handoff.md` is newer (first run of a roadmap vs. next phase after execution).
- `execute-phase` ← `~/.claude/skills/plan-phase/handoff.md`.

**User workflow at skill exit**: close-out prints the handoff + reflection paths and tells the user to run `/clear` before invoking the next skill. The next skill reads the predecessor's handoff automatically, so the new context window starts with only the relevant state — no inherited chatter.

**Where the files physically live**: `~/.claude/skills/<skill>/` is a symlink to the skill's source repo (either this clone or wherever `install.sh` points). Reflection and handoff files land in that source repo via the symlink. The repo's `.gitignore` excludes `*/reflections/` and `*/handoff.md` so they don't pollute git history — but they stay visible on disk for review. If repo-specific content ever leaks into a reflection that's supposed to be repo-agnostic, you'll spot it immediately by browsing the skill dir.

---

# Part 3 — Meta-skills (maintain the pipeline itself)

Two skills that close the self-improvement loop on the planning chain. Use them periodically (monthly, or after a batch of phase executions has accumulated reflections).

```
pipeline runs produce reflections
        │
        ▼
/skill-improvement-planner   →   plan-v<N>-<ISO>.md (aggregated, repo-agnostic)
        │
        ▼ (/clear, optional user review of the plan)
/skill-editor                →   applies recommendations; archives consumed reflections
        │
        └──► next pipeline run benefits from the improved instructions
```

## The meta-skills

- **skill-improvement-planner** — Aggregates reflection files from `phase-roadmap-builder`, `plan-phase`, and `execute-phase`. Identifies recurring themes (default threshold: 2 distinct reflections), separates high-confidence from speculative, flags contradictions, enforces repo-agnostic output. Produces a plan file at `~/.claude/skills/skill-improvement-planner/plans/plan-v<N>-<ISO>.md` with a frontmatter listing every reflection consumed. Does not edit any skill itself.

- **skill-editor** — Ingests the plan file (either explicitly via argument or via the planner's handoff). For each recommendation, spawns a frontier-tier Agent to apply the change while preserving directive-only house style. Mirrors edits to both `~/code/dotfiles/` and this repo when a skill is dual-homed. Archives consumed reflections to `<reflections-dir>/archive/` — per-recommendation granularity means a reflection stays unarchived if any recommendation it supports failed, so next cycle can reconsider. Commits + pushes both repos.

## Meta-skill considerations

### The reflection archive convention

New with this loop. Path: `~/.claude/skills/<skill>/reflections/archive/<original-filename>`. Created lazily by `skill-editor` on first archive. The planner excludes `archive/` when globbing, so each aggregation cycle sees only un-processed reflections.

### Invocation cadence

There's no automatic trigger. Run `/skill-improvement-planner` when reflections have accumulated — typically several pipeline runs' worth. Review the generated plan (it's a markdown file; skim it), then run `/skill-editor` to apply. The `/clear` between them is strongly recommended so the editor starts with only the plan in context, not the planner's transcript.

### Failure handling

If a recommendation can't be applied (vague, repo-specific, target file missing, or contradicts existing instructions), `skill-editor` refuses cleanly, reports the reason, and leaves the supporting reflections unarchived. The next `/skill-improvement-planner` run will reconsider them — possibly in a clearer form once more reflections accumulate.

### Double-application protection

`skill-editor` appends each applied plan's timestamp to `~/.claude/skills/skill-editor/applied-plans.log`. On re-run, it checks this log and prompts if the plan has already been applied once — applying twice is almost always a mistake.

---

# Part 4 — Standalone skills (efficiency-kit)

These are unrelated to the pipeline. Each is a short passive rule that loads into context and steers you away from a common anti-pattern. They don't run workflows, don't produce artifacts, don't need reflections or handoffs. Load whichever are relevant to the work you're doing.

- **file-read-cache** — Don't re-read a file you already read in this conversation unless it's been modified since. Addresses the most common source of duplicate tool calls.

- **safe-edit** — Pre-flight checklist before every Edit/Write: have I Read this file? Has anything modified it since? Is my `old_string` unique? Am I preserving exact indentation? Prevents the most common edit failures.

- **batch-verify** — When editing 3+ related files for the same change, complete ALL edits first, then verify ONCE (tsc, pytest, etc.). Intermediate verification on partial refactors just reports errors in files you haven't fixed yet.

- **smart-search** — Decision tree + ripgrep-escaping rules for Grep/Glob. If you'd need 4+ Grep calls to answer a question, use an Explore agent instead. Before a second search on the same topic, stop and diagnose the first failure — don't thrash.

- **diagnose-bash-error** — When a Bash command fails, read the full stderr and categorize by exit code before retrying. Prevents the "try different flags until it works" anti-pattern.

- **validate-before-bash** — Before the first `tsc`, `pytest`, `cargo build`, `flutter analyze` in a session: run a preflight checking tool-installed, config-file-present, deps-installed. Catches predictable failures before eating the tool's slow startup time.

- **detect-environment** — One-pass detection of Python (system / venv / poetry / uv), Node, TypeScript, Dart, Rust, Git, Docker, Java at session start. Caches the result so you don't chain `which` → `whereis` → `type` → `find /` for every tool lookup.

- **smart-screenshot** — Rules for browser automation: use `browser_snapshot()` for finding elements and taking actions (fast, text-based); use `browser_take_screenshot()` only for visual verification. Prevents "screenshot → zoom → screenshot" thrashing and blind retries when screenshots fail.

- **page-load-monitor** — When a browser navigation or screenshot fails, do escalating *diagnosis* (console errors, network requests) instead of escalating retries. After 2 failures, identify the cause — dev server down, 503 from backend, JS build error, wrong URL — and surface to the user instead of retrying a 4th time.

---

## Sharing notes

Fork this repo. Adapt the tier table (Part 2) to your team's model preferences. Adjust the review prompts in `planning-chain/plan-phase/assets/review_prompt.md` and `planning-chain/phase-roadmap-builder/assets/review_prompt.md` to your domain (they're tuned for general software engineering; a data-science team might want different assessment criteria). Keep the close-out rules — clean tree + repo-agnostic reflection — if you want the corpus to compound.
