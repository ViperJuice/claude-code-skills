# Considerations, prerequisites, and nuances

Read this before running the planning chain at scale. Most of it is environment setup; the last two sections explain the reflection corpus and the review pattern.

## Target harness

The skills are written for **[Claude Code](https://docs.claude.com/en/docs/claude-code/overview)**. They use these Claude Code-specific tools:

- `Agent` (with `subagent_type`, `team_name`, `isolation`, `model`, `name`, `prompt`)
- `TeamCreate`, `TaskCreate`, `TaskUpdate`, `TaskStop`, `TaskList`
- `EnterWorktree`, `ExitWorktree`
- `SendMessage`
- `AskUserQuestion`, `ExitPlanMode`
- `ToolSearch` (for deferred tool loading)

Codex, Gemini CLI, and OpenCode are **not** supported as host harnesses — they don't have equivalent primitives for team coordination, worktree isolation, or plan-mode approval. They're used only as *external CLIs* for the optional review step (see below).

## Model tier table

`execute-phase/SKILL.md` routes lane dispatches by capability tier. The concrete model IDs live in exactly one place — the `## Model tiers` block near the top of that file. When Anthropic ships a new model, edit that table (three lines). Everything else in the skill refers to tier names (`frontier`, `strong`, `fast`).

Current mapping as shipped:

| Tier      | Model              |
|-----------|--------------------|
| frontier  | claude-opus-4-7    |
| strong    | claude-sonnet-4-6  |
| fast      | claude-haiku-4-5   |

## Frontier model auto-discovery (for external CLIs)

`tools/frontier_model_discovery.py` resolves the current top Gemini and Codex models, caches to `~/.claude/cache/frontier_models.json` for 24 hours. This is how the external-review step avoids hardcoding Gemini/Codex model IDs the way the Anthropic tier table does.

First run of `--review-external` on an empty cache: the script prints a discovery prompt to stderr asking the calling Claude session to execute the four-tool research pattern (BrightData search, BrightData scrape, fetch, Context7 doc lookup) and save the resolved models back via `frontier_model_discovery.py --save '<json>'`. The `PMCP` gateway provides all four tools; see the Custom tools section.

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

## External CLI review (`--review-external`)

Opt-in flag on `plan-phase` and `phase-roadmap-builder`. After the skill writes its artifact, it runs Gemini and Codex **in parallel** through `tools/review_with_cli.py` with a skill-specific review prompt. Both CLIs receive identical input; output lands in a `_reviews.md` sibling file.

Interpretation rule (baked into the output):

> When Gemini and Codex flag the same concern, treat it as real. Divergent comments are context, not verdicts — decide which to act on.

Claude authors; the CLIs critique. This is a review pattern, not a three-way consensus-generation pattern.

**Prerequisites**:
- `gemini` CLI installed (`npm install -g @google/gemini-cli` or equivalent) and authenticated via API key or Google subscription.
- `codex` CLI installed (`npm install -g @openai/codex` or equivalent) and authenticated via API key or ChatGPT subscription.
- `frontier_model_discovery.py` cache populated (see above).

If the CLIs aren't installed or authenticated, the skills still work — just don't pass `--review-external`. It's strictly additive.

## Custom tool dependencies

### PMCP — required for a few steps

[`PMCP`](https://github.com/ViperJuice/pmcp) is an open-source MCP gateway that aggregates many MCP servers behind progressive disclosure: tools aren't loaded until a skill asks for them, which saves context. The planning chain uses PMCP for:

- **`execute-phase` browser verification** — Playwright via `pmcp_invoke(tool_id="playwright::browser_navigate", ...)`.
- **Frontier model discovery** — BrightData search + scrape, fetch, and Context7 doc lookup.

Minimum install: follow PMCP's README. A minimal `~/.pmcp.json` registers Playwright and Context7; PMCP can provision the rest on demand via `pmcp_request_capability`.

If your team already has a different MCP gateway or a direct Playwright MCP install, the browser-verification step will adapt — `execute-phase` says "use Playwright via whatever MCP you have configured," not "use PMCP specifically." The discovery script is slightly more coupled; feel free to swap its research pattern for whatever web-lookup tools you have.

### Code-Index-MCP — optional

[`Code-Index-MCP`](https://github.com/ViperJuice/Code-Index-MCP) is a local-first code indexer (symbol search + optional semantic search across 48 Tree-sitter languages). Useful for large repos during the `plan-phase` reconnaissance step, but not required. PMCP can auto-provision it.

### Other

The skills make no other assumptions about custom tooling. They use standard `git`, `python3`, and `bash`. Python scripts are stdlib-only.

## Parallelism semantics

- **Phases are serial checkpoints.** Phase N+1 can't start until Phase N's interface freezes (`IF-0-<ALIAS>-<N>`) are closed.
- **Lanes within a phase are parallel.** `execute-phase` dispatches all ready lanes in one message, up to `EXECUTE_MAX_PARALLEL_LANES` (default 2).
- **Cross-phase parallelism.** Phases with no shared ancestor in the DAG (e.g., `P6A` parallel after P1, `P6B` parallel after P4) can run concurrently. The `phase-roadmap-builder` skill's decomposition heuristics push for this; the DAG in the roadmap doc is the source of truth.
- **Single-writer files** (barrel index files, generated types, migration numbers, nav configs) need an explicit owner-lane declaration in the roadmap's Execution Notes. `plan-phase` won't allow two lanes to both own the same file.

Tuning knob: `EXECUTE_MAX_PARALLEL_LANES` controls the max concurrent lane dispatches per wave. Increase it on machines with lots of RAM and GPU headroom; keep it small if you hit rate limits or merge-conflict churn.

## Worktree conventions

`execute-phase` isolates each lane's teammate in its own git worktree under `.claude/worktrees/`. The allocator guarantees unique names (`lane-sl-1-<timestamp>-<random>`). After a lane's verify passes, the orchestrator resolves the lane's commit by SHA (never by branch name — the harness sometimes auto-names branches) and merges with `--no-ff`.

Add these to your `.gitignore`:

```
.claude/worktrees/
.claude/execute-phase-state.json
```

The state file holds progress for `--resume` on halt. On clean completion, it's deleted.

## Close-out: reflection + handoff

Every artifact-producing skill (`phase-roadmap-builder`, `plan-phase`, `execute-phase`) spawns a single frontier-tier Agent at close-out. That Agent reviews the skill's instructions and the execution transcript and writes **two** files into the skill's own directory:

1. **Repo-agnostic reflection** → `~/.claude/skills/<skill>/reflections/<skill>-reflection-v<N>.md`
   - Version `N` increments on each run.
   - Strictly about the skill's *instructions* — no references to the project, codebase, file names, or domain.
   - Two sections: "What worked" and "Improvements to SKILL.md."
   - **Why**: a future meta-skill (not in this repo yet) will digest this corpus across skills and runs and propose concrete SKILL.md changes.

2. **Repo-specific handoff** → `~/.claude/skills/<skill>/handoff.md`
   - Single file, overwritten each run.
   - Concrete: summary of what was produced, key decisions, open items for the next skill, repo-specific gotchas discovered, files committed this run.
   - Starts with a metadata header (`from:` + `timestamp:` + `artifact:`) so the next skill can validate predecessor identity and freshness.

**Chain reads** (Step 0 of each artifact-producing skill):

- `phase-roadmap-builder` ← `~/.claude/skills/execute-phase/handoff.md` (previous cycle's output, useful for roadmap extensions).
- `plan-phase` ← whichever of `phase-roadmap-builder/handoff.md` or `execute-phase/handoff.md` is newer (first run of a roadmap vs. next phase after execution).
- `execute-phase` ← `~/.claude/skills/plan-phase/handoff.md`.

**User workflow at skill exit**: close-out prints the handoff + reflection paths and tells the user to run `/clear` before invoking the next skill. The next skill reads the predecessor's handoff automatically, so the new context window starts with only the relevant state — no inherited chatter.

**Where the files physically live**: `~/.claude/skills/<skill>/` is a symlink to the skill's source repo (either this clone or wherever `install.sh` points). Reflection and handoff files land in that source repo via the symlink. The repo's `.gitignore` excludes `*/reflections/` and `*/handoff.md` so they don't pollute git history — but they stay visible on disk for review. If repo-specific content ever leaks into a reflection that's supposed to be repo-agnostic, you'll spot it immediately by browsing the skill dir.

If you fork this repo, keep the same pattern in your own skills so your reflections feed the same corpus and your handoffs work with the chain.

## Directive-only writing style

See `_template/SKILL.md`. Short version: imperative instructions, rationale in one clause, no war stories, no stats, no narrative justification. The description field in YAML frontmatter carries triggering info only — not "this skill prevents 47% of retry failures." That kind of prose tends to leak into skill bodies and bloats context. All the skills in this repo were cleaned to this style; contributions should follow it.

## Sharing notes

Fork this repo. Adapt the tier table to your team's model preferences. Adjust the review prompts in `planning-chain/plan-phase/assets/review_prompt.md` and `planning-chain/phase-roadmap-builder/assets/review_prompt.md` to your domain (they're tuned for general software engineering; a data-science team might want different assessment criteria). Keep the close-out rules — clean tree + repo-agnostic reflection — if you want the corpus to compound.
