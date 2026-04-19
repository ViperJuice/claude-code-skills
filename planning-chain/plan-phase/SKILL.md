---
name: plan-phase
description: "Architecture-first planning for a spec phase. Produces an interface-freeze + swim-lane document for parallel execution. Use in plan mode. Supports --consensus for multi-agent architectural consensus across named Plan teammates."
---

# plan-phase

Architecture-first planner for a single phase of a multi-phase specification. Produces a plan document containing interface freezes, swim lanes with disjoint file ownership, a lane DAG, per-lane task lists (test → impl → verify), and testable acceptance criteria. Designed to be run in **plan mode** and handed off to `execute-phase` for parallel execution.

## When to use

- The input is a multi-phase spec (e.g., `specs/phase-plans-v1.md`) and the user wants to plan a specific phase.
- The work touches more than one area of the codebase and would benefit from parallel lane execution.
- You need interface contracts frozen before lanes diverge.

## When NOT to use

- Single-file, single-concern change → use `/plan-detailed` instead.
- Pure research / "how does X work" → use `Agent(subagent_type: "Explore")` directly, no plan doc needed.
- No phase structure in the spec → use `/plan-detailed` or ad-hoc planning.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<spec-path>` | no | Path to the spec file (relative to repo root). Default: auto-detected `specs/phase-plans-v*.md` at the highest version. |
| `<phase-name-or-id>` | yes | A phase heading, short alias (`P1`–`P7`), or any fuzzy match. Ambiguous → stop and ask via `AskUserQuestion`. |
| `--output <path>` | no | Override the default output path. Default: `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md`. |
| `--consensus` | no | Enable multi-agent architectural consensus (2–3 Plan teammates with different framings). |
| `--review-external` | no | After writing the plan doc, run Gemini + Codex CLIs in parallel to review it. Requires `gemini` and `codex` installed and authenticated. Produces a `_reviews.md` sibling file. |

Repos may supply a phase alias table (JSON file) via `$PLAN_PHASE_ALIASES` or fall back to the built-in `P1`–`P7` table. If the alias isn't recognized and no custom table is set, stop and ask via `AskUserQuestion` with the actual spec headings.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PLAN_SPEC` | Auto-detected highest `specs/phase-plans-v*.md` | Path to the spec file. |
| `PLAN_VERSION` | Extracted `v\d+` from spec filename | Version string embedded in output filename. |
| `PLAN_PHASE_ALIASES` | Built-in alias table | Path to a JSON file mapping alias → phase heading. |

Example `.env`:

```sh
PLAN_SPEC=specs/phase-plans-v1.md
```

Invocation examples:

```
/plan-phase P1
/plan-phase P3 --consensus
/plan-phase P3 --review-external
/plan-phase specs/roadmap.md "Phase 3: Billing" --consensus --review-external
```

## Deferred tool preloading

Load tools used later in a single query so mid-workflow calls don't pay a round-trip:

```
ToolSearch(query: "select:TaskCreate,AskUserQuestion,ExitPlanMode")
```

## Workflow (delegation-first)

The main thread is an orchestrator only: brief specialists, synthesize output, enforce consensus, write the final doc, emit tasks. See `## Teamwork & delegation posture` for the posture rules.

### Step 0 — Read predecessor handoff (if present)

The predecessor skill may be either:

- `phase-roadmap-builder` (first time planning a phase against a new roadmap) → `~/.claude/skills/phase-roadmap-builder/handoff.md`
- `execute-phase` (planning the next phase after a prior one finished executing) → `~/.claude/skills/execute-phase/handoff.md`

Check both paths. If both exist, pick the one with the newer `timestamp:` in its metadata header. If only one exists, use it. If neither, proceed standalone.

Validate the handoff: `from:` must match the expected predecessor; timestamp should be recent (<7 days). On mismatch or staleness, flag via `AskUserQuestion` with `[use anyway, ignore, abort]`.

Fold the handoff's "Open items" and "Repo-specific gotchas" into the brief given to Step 2's Explore teammates so they know what to watch for.

### Step 1 — Resolve spec path, phase, and PHASE_ID

**Spec path resolution (in order):**
1. `$PLAN_SPEC` env var → use verbatim.
2. `<spec-path>` arg → use verbatim.
3. Glob `specs/phase-plans-v*.md`; pick the highest version.
4. Else any `specs/*.md` if exactly one exists → use it and note the assumption.
5. Else stop and ask via `AskUserQuestion`.

**Version string** (for output filename): `$PLAN_VERSION` → pattern `v\d+` in filename → `v1` default.

**Phase alias table**: `$PLAN_PHASE_ALIASES` (JSON file) → built-in table.

**Phase name**: short alias → fuzzy match → 0 matches: stop + ask → multiple matches: stop + disambiguate.

**PHASE_ALIAS**: the resolved short alias in lowercase (e.g., `p1`). If none exists, use `phase-<N>`.

**Output path**: `--output` override, else `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md`.

### Step 2 — Parallel reconnaissance via Explore teammates

Launch up to 3 `Agent(subagent_type: "Explore")` calls in a single message. One per major area the phase touches. Each Agent call MUST set `name:` so it can be re-addressed later via `SendMessage`.

Teammate-naming template: `explore-<area>` (e.g., `explore-schema`, `explore-workers`).

Each brief must include:

- The phase's Objective + Exit criteria copied verbatim from the spec.
- A scoped question: "Map existing code in `<paths>` relevant to this phase. Surface: (a) existing utilities/patterns to reuse, (b) current type/schema/interface shapes that constrain the design, (c) places that will need to change, (d) hidden coupling that would break worktree isolation."
- A 1–2 sentence architecture context: how these paths fit the larger system.
- Related files the teammate should know about but not rewrite (type defs, tests, shared config).
- A length cap: "Report in under 400 words."

Apply the `/task-contextualizer` checklist to every brief.

Block until all return. Their findings populate `## Context`.

### Step 3 — Architectural decisions

**With `--consensus`**: Launch 2–3 `Agent(subagent_type: "Plan")` calls in a single message, each with a distinct framing:

| Name | Framing |
|---|---|
| `arch-minimal` | Minimal change. Preserve current module boundaries. Add, don't refactor. |
| `arch-clean` | Clean architecture. Willing to refactor to make the design right. |
| `arch-parallel` | Maximize parallelism. Prefer more, smaller lanes over fewer, fatter lanes, even if it adds interface surface. |

Each teammate's brief includes: the spec phase section, all Explore teammate findings, and its framing. Apply the `/task-contextualizer` checklist — architecture context and related-files list carry over from the Explore briefs. Each must return: (1) proposed interface freezes, (2) proposed lane decomposition with file ownership, (3) rationale, (4) known risks.

Synthesize per the Consensus mechanism below. If round 1 doesn't converge, re-address the same named teammates via `SendMessage` (not new `Agent` calls) with the specific disagreement surfaced. Max 2 rounds.

**Without `--consensus`**: Launch 1 `Agent(subagent_type: "Plan", name: "arch-baseline")` for baseline architecture decisions.

### Step 4 — Lane decomposition (main thread)

Synthesize Explore + Plan output into swim lanes. For each lane, determine:

- **Scope** — one sentence.
- **Owned files** — glob list. Must be disjoint from every other lane's globs.
- **Interfaces provided** — symbols, types, endpoints, migrations this lane publishes.
- **Interfaces consumed** — symbols this lane depends on from other lanes.
- **Parallel-safe** — `yes` / `no` / `mixed` (with explanation if not `yes`).

Run the Lane validation checklist (below) before proceeding. If it fails, return to Step 3 with the failure noted.

### Step 5 — Task authoring (main thread)

For each lane, author an ordered task list:

- One **test** task (write failing tests for the lane's contracts).
- One or more **impl** tasks (each depends on the preceding test task).
- One **verify** task (runs the full test suite for the lane, plus any integration checks).

Tasks are identified `<SL-ID>.<N>`.

**Every phase must include a terminal `SL-docs` lane** after the impl/verify lanes. See `## Docs-sweep lane template` below. No opt-out — force a conscious doc decision every phase, even if the lane ends up recording "no cross-cutting changes needed."

### Step 6 — Emit per-lane tasks via TaskCreate

For each lane, emit one `TaskCreate`:

- **Title**: `<SL-ID> — <lane name>`
- **Body**: `Depends on: <upstream SL-IDs>`, `Blocks: <downstream SL-IDs>`, `Parallel-safe: <flag>`, and the ordered child task list (`test / impl / verify`).

This makes the lane DAG visible in the user's task pane and becomes the hand-off surface for `execute-phase`.

### Step 7 — Write plan doc

Write to both:

1. `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` in the current project.
2. The plan-mode scratch file path (found in the plan-mode system reminder — do not guess the path).

Then validate:

```
python scripts/validate_plan_doc.py plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md
```

Fix any errors before calling `ExitPlanMode`. The validator checks required headings, disjoint file ownership, DAG acyclicity, grep-assertion-paired-with-tests, and eager-reexport risks.

### Step 7.5 — External CLI review (only if `--review-external`)

Run the shared review script:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/review_with_cli.py" \
  --artifact plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md \
  --prompt-file "$(git rev-parse --show-toplevel)/.claude/skills/plan-phase/assets/review_prompt.md" \
  --out plans/phase-plan-<VERSION>-<PHASE_ALIAS>_reviews.md
```

If the script reports the frontier-model cache is empty, it prints a discovery prompt to stderr. Surface to the user via `AskUserQuestion` with options `[run discovery now, skip review this run, abort]`.

Tell the user: "Review written to `plans/phase-plan-<VERSION>-<PHASE_ALIAS>_reviews.md`. When Gemini and Codex flag the same concern, treat it as real; divergent comments are context, not verdicts."

### Step 8 — ExitPlanMode

Call `ExitPlanMode`. The plan doc is the approval surface.

## Plan document template

Use these headings verbatim — `execute-phase` parses them:

```markdown
# <PHASE_ID>: <Phase Name>

## Context
<Synthesized from Explore teammates. What exists, what constrains the design, what will change.>

## Interface Freeze Gates
- [ ] IF-0-<PHASE>-<N> — <one-line description of the frozen interface>
- [ ] IF-0-<PHASE>-<N+1> — …

## Cross-Repo Gates
<Omit entirely if the phase only touches this repo.>
- [ ] IF-XR-<N> — <interface that must be frozen across repo boundaries>

## Lane Index & Dependencies

SL-1 — <lane name>
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-2 — <lane name>
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes

## Lanes

### SL-1 — <lane name>
- **Scope**: <one sentence>
- **Owned files**: `path/one/**`, `path/two/*.ts`
- **Interfaces provided**: `FooContract`, `POST /api/bar`
- **Interfaces consumed**: (none)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `path/one/__tests__/foo.test.ts` | `FooContract` shape | `pnpm test path/one/__tests__/foo.test.ts` |
| SL-1.2 | impl | SL-1.1 | `path/one/foo.ts` | — | — |
| SL-1.3 | verify | SL-1.2 | `path/one/**` | all SL-1 tests | `pnpm test path/one` |

### SL-2 — <lane name>
…

### SL-docs — Documentation & spec reconciliation

(See `## Docs-sweep lane template` earlier in this skill for the full lane spec. Copy it verbatim and set `Depends on:` to list every other SL-N in this phase.)

## Execution Notes
- <Parallelism caveats, sequencing gotchas, lanes that can't be worktree-isolated (shared migrations, shared generated files), etc.>
- **Single-writer files**: <files multiple lanes might want to touch but only one is allowed to modify — e.g., barrel index files, generated types, nav config, worker router. List the owner lane for each. If a single-writer file is also touched by a later phase, name this phase's owner lane and have them author-at-plan-time any additions the later phase's consumer lanes will need. Re-opening the file from the later phase's lane adds a cross-phase serialization edge that shouldn't exist.>
- **Known destructive changes**: <any deletions a lane legitimately performs, named by file path. If empty, write "none — every lane is purely additive." This is the whitelist execute-phase's pre-merge check uses to distinguish legitimate deletions from stale-base accidents.>
- **Expected add/add conflicts**: <if SL-0 preamble stubs a file that a later lane replaces the body of, list the file path here. The orchestrator pre-authorizes `git checkout --theirs <path>` resolution at merge time.>
- **SL-0 re-exports**: <if the preamble adds symbols to an `__init__.py`, specify the `__getattr__` lazy pattern (not top-level imports). Eager re-exports break package load when a later lane drops or renames the symbol.>
- **Worktree naming**: execute-phase allocates unique worktree names via `scripts/allocate_worktree_name.sh`. Plan doc does not need to spell out lane worktree paths.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- (If `--consensus` was used) **Architectural choices**: <consensus summary, or unresolved disagreement with dissent recorded>

## Acceptance Criteria
- [ ] <Testable assertion 1 drawn from the spec phase's Exit criteria>
- [ ] <Testable assertion 2>

## Verification
<Concrete end-to-end commands to run after all lanes merge. pnpm, supabase, curl, playwright, etc.>
```

## ID conventions

| ID | Format | Example |
|---|---|---|
| `PHASE_ID` | Spec identifier, else `PHASE-<kebab>` | `PHASE-1-shared-semantics` |
| Lane ID | `SL-<N>` | `SL-3` |
| Task ID | `<LANE_ID>.<N>` | `SL-3.2` |
| Interface freeze | `IF-0-<PHASE>-<N>` | `IF-0-P1-1` |
| Cross-repo freeze | `IF-XR-<N>` | `IF-XR-2` |

Defaults only — if the spec already uses its own identifiers (e.g., `P1-SL-AUTH-01`), adopt those verbatim.

## Task types & dependency rules

| Type | Purpose | Rules |
|---|---|---|
| `test` | Write failing tests that pin down the lane's contracts. | Must precede any `impl` task in the same lane. |
| `impl` | Write the code that makes the preceding tests pass. | Must depend on exactly one `test` task in the same lane. |
| `verify` | Run the full lane test suite + any integration checks. | Last task in the lane. Depends on the last `impl` task. |
| `docs` | Update cross-cutting documentation and the docs catalog. | Lives in the terminal `SL-docs` lane. Depends on every other lane's final `verify` task. |

## Docs-sweep lane template

Every phase plan must include this as the final lane. Copy verbatim into the `## Lanes` section, adjust `Depends on:` to list every other `SL-N` in the phase, and edit the `Scope notes` if the phase has atypical docs impact.

```markdown
### SL-docs — Documentation & spec reconciliation

- **Scope**: Refresh the docs catalog, update cross-cutting documentation touched or invalidated by this phase's impl lanes, and append any post-execution amendments to phase specs whose interface freezes turned out wrong.
- **Owned files** (read `.claude/docs-catalog.json` for the authoritative list; a minimum set is below, but the catalog is canonical):
  - Root: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `MIGRATION.md`, `ARCHITECTURE.md`, `DESIGN.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`
  - Agent indexes: `llm.txt`, `llms.txt`, `llms-full.txt`
  - Service manifests: `services.json`, `openapi.yaml`/`.yml`/`.json`
  - `docs/**`, `rfcs/**`, `adrs/**`
  - `.claude/docs-catalog.json` (this lane maintains it)
  - The current phase's section of `specs/phase-plans-v<N>.md` (append-only amendments)
  - Any prior `plans/phase-plan-v<N>-<alias>.md` or prior spec phase sections whose contracts this phase invalidated (prior-phase amendments allowed)
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal)
- **Depends on**: every other `SL-N` in this phase

**Tasks**:

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan: `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`. Picks up any new doc files created by impl lanes; preserves `touched_by_phases` history. |
| SL-docs.2 | docs | SL-docs.1 | per catalog | For each file in the catalog, decide: does this phase's work change it? If yes, update the file and append the current phase alias to its `touched_by_phases`. If no, leave it. Record in commit message any files intentionally skipped. |
| SL-docs.3 | docs | SL-docs.2 | `specs/phase-plans-v<N>.md`, prior plans | Append `### Post-execution amendments` subsections to any phase section (current or prior) whose interface freeze was empirically wrong this run. Named freeze IDs + dated correction. |
| SL-docs.4 | verify | SL-docs.3 | — | Run any repo doc linters (`markdownlint`, `vale`, `prettier --check`, Mermaid/PlantUML render check). If none configured, no-op. |
```

No opt-out. A phase with nothing to change still runs `SL-docs` and records that explicitly in its commit message — the audit trail.

## Consensus mechanism (synthesis rule)

Applied by the main thread after `--consensus` Step 3a:

1. **Unanimous** across all teammates → accept directly.
2. **Majority (2 of 3)** → accept the majority view; record the dissenting view under `## Execution Notes > Architectural choices > Dissent`.
3. **No majority** → re-address the same named teammates via `SendMessage` with the specific conflict surfaced. Max 1 additional round.
4. **Still no convergence** → main thread picks (biased toward `arch-parallel` for this skill's purpose) and records the full disagreement under `## Execution Notes > Unresolved architectural disagreements`.

## Lane validation checklist

Before writing the plan doc, verify:

- [ ] **Disjoint file ownership** — no two lanes' `Owned files` globs intersect. For generated files, call out shared-generated status in Execution Notes.
- [ ] **DAG has no cycles** — a topological sort of `Depends on:` succeeds.
- [ ] **Every `impl` task has a preceding `test` task** in the same lane.
- [ ] **Every acceptance criterion is a testable assertion**, not prose. "Users can log in" is not testable; "`POST /api/auth` returns 200 with a valid session cookie for a registered user" is.
- [ ] **Grep assertions are paired with tests.** Any acceptance criterion using `rg` or `grep` as its sole check must also cite a test file — grep alone is defeated by renaming a symbol to pass the regex.
- [ ] **Interface freeze gates are concrete** — name the symbol/endpoint/migration, not a vibe.
- [ ] **Stale-base resilience** — for each lane that isn't a DAG root, list every upstream symbol, migration number, or file path it reads under `Interfaces consumed`. This gives `execute-phase` evidence to verify the base wasn't stale and narrows the blast radius of a mis-based commit. Execution Notes must call out "if lane teammate finds its worktree base is pre-<upstream-SL>, stop and report — do not rebase silently."
- [ ] **Cross-lane file deletions called out** — if any lane legitimately deletes a file that another lane produces (rare but real: a lane replacing a stub), record it under Execution Notes' "Known destructive changes" block.
- [ ] **Expected add/add conflicts declared** — if SL-0 preamble stubs a file that a lane replaces, add it under Execution Notes' "Expected add/add conflicts" block.
- [ ] **SL-0 re-exports use `__getattr__` lazy form** — declared under Execution Notes' "SL-0 re-exports" block.
- [ ] **Plan doc passes `validate_plan_doc.py`** — run the validator and confirm zero errors before calling `ExitPlanMode`. The validator catches structural issues (missing headings, duplicate lane IDs, malformed task tables) that manual review misses.
- [ ] **Terminal `SL-docs` lane present** — every phase plan must include the docs-sweep lane from `## Docs-sweep lane template`. `Depends on:` lists every other lane in the phase. No opt-out; a phase with no doc changes still runs the lane and records that.

## Teamwork & delegation posture

- **Main thread = orchestrator only.** Brief, synthesize, write, emit. Do not `Grep`/`Read` the codebase directly during Steps 2–5. If you find yourself doing so, the teammate's brief was incomplete — re-brief via `SendMessage`.
- **Parallel-by-default.** Step 2 (Explore) and Step 3a (consensus Plan) MUST be issued as a single message with multiple `Agent` tool calls.
- **Name every teammate.** Set `name:` on every `Agent` call so you can re-address via `SendMessage` without losing context or paying to restart.
- **Task list as source of truth for the lane DAG.** Step 6's per-lane `TaskCreate` is how the plan becomes actionable; each lane task is addressable by ID for `execute-phase`.
- **Hand-off to `execute-phase`.** After `ExitPlanMode` approval, invoke `/execute-phase <plan-doc-path>`. See that skill for the full execution contract (team creation, worktree isolation, merge policy). Do NOT pass `isolation: "worktree"` alongside `team_name` — the harness drops `isolation` in that combination.
- **Manual hand-off (when `execute-phase` is unavailable).** Run `python scripts/validate_plan_doc.py <plan-doc-path>` first. Then execute each lane in one of two ways:
  - (a) **Standalone** — `Agent(isolation: "worktree", name: "<SL-ID>", subagent_type: "general-purpose")` without `team_name`. The `isolation` kwarg is honored in this form; loses team coordination.
  - (b) **Teamed** — `TeamCreate` + `Agent(team_name=…, name="<SL-ID>", subagent_type="general-purpose")`, and the teammate's first tool call is `EnterWorktree` (load via `ToolSearch(query="select:EnterWorktree")`). Worktree via tool, team coordination preserved.

## Output contract

After `ExitPlanMode` approval, three artifacts exist:

1. `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` — committable, valid markdown, all headings present.
2. The plan-mode scratch file — identical contents.
3. One `TaskCreate`'d top-level task per lane, each with `test / impl / verify` children, containing `Depends on:` / `Blocks:` / `Parallel-safe:` metadata in the body.

Those three are the full hand-off surface — everything downstream (manual lane execution or `execute-phase`) reads from them.

## Close-out — Commit artifact (clean-tree guarantee)

After `ExitPlanMode` is approved, before exiting:

1. `git add plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` (and the `_reviews.md` sibling if `--review-external` produced one).
2. `git commit -m "chore(plan): <PHASE_ID> lane plan"`.
3. Run `git status`. If dirty outside the skill's own artifacts, surface via `AskUserQuestion` with `[commit the remaining changes as chore, stash, abort]`.

`execute-phase`'s preflight will reject a dirty tree on its next invocation; this step exists to prevent that.

## Close-out — Reflection + Handoff

After artifacts are committed, resolve paths:

```bash
REFLECTION_PATH=$(python3 ~/.claude/skills/_shared/next_reflection_path.py plan-phase)
HANDOFF_PATH=~/.claude/skills/plan-phase/handoff.md
SKILL_MD=~/.claude/skills/plan-phase/SKILL.md
```

Spawn ONE close-out agent using the `frontier` tier. It writes BOTH files directly via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "plan-phase-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # plan-phase reflection — <ISO timestamp>

      ## What worked
      - <bullet, about the SKILL's instructions>

      ## Improvements to SKILL.md
      - <specific, actionable change to the instructions>

      Do NOT reference this project, codebase, filenames, or domain.
      Feedback is about how the skill's instructions performed, for a
      future meta-skill that digests reflections across runs.

    FILE 2 — REPO-SPECIFIC handoff → write to <HANDOFF_PATH> (overwrites
    any prior handoff from this skill)

      ---
      from: plan-phase
      timestamp: <ISO>
      artifact: <absolute path to plan doc + reviews if any>
      ---

      # Handoff for execute-phase

      ## Summary
      <2-3 sentences: phase planned, lanes count, plan doc path.>

      ## Key decisions made this run
      - <numbered, one line each — lane boundaries, IF-freeze signatures,
        consensus outcomes if --consensus was used>

      ## Open items for execute-phase
      - <concrete — e.g., "SL-2 depends on SL-1's StoreRegistry.get
        signature; ensure lane ordering in dispatch">

      ## Repo-specific gotchas surfaced
      - <quirks of THIS codebase discovered during planning>

      ## Files committed this run
      - <path> @ <commit sha>

      ## Execute-phase's likely scope
      - <file globs from Owned files across lanes>
  """
)
```

After the agent returns, print to the user:

> Plan written to `<plan-doc-path>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<HANDOFF_PATH>`.
>
> Recommended next step: run `/clear` to reset your context window, then invoke `/execute-phase <alias>`. The next skill reads the handoff automatically.
