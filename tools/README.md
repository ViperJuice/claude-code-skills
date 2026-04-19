# tools/

Shared Python utilities used by the planning skills. All are stdlib-only; Python 3.9+ required.

When installed via `install.sh`, these land at `.claude/skills/_shared/` — the planning skills reference them at that path via `$(git rev-parse --show-toplevel)/.claude/skills/_shared/<script>.py`.

## `frontier_model_discovery.py`

Resolves current frontier Gemini and Codex models for the `--review-external` review step. Caches to `~/.claude/cache/frontier_models.json` with a 24-hour TTL.

Usage:

```bash
# Check/emit cache
python3 frontier_model_discovery.py --resolve

# Force refresh
python3 frontier_model_discovery.py --refresh

# Save a resolved result (called after four-tool discovery)
python3 frontier_model_discovery.py --save '{"gemini_model": "...", "codex_model": "...", ...}'
```

On empty/stale cache, `--resolve` prints a structured prompt on stderr asking the calling Claude session to execute the four-tool research pattern (BrightData search, BrightData scrape, fetch, Context7) and save the result via `--save`.

Required only if you use `--review-external` on `plan-phase` or `phase-roadmap-builder`.

## `review_with_cli.py`

Runs an artifact through Gemini and Codex CLIs in parallel and writes a combined markdown review.

Usage:

```bash
python3 review_with_cli.py \
  --artifact path/to/artifact.md \
  --prompt-file path/to/review_prompt.md \
  --out path/to/artifact_reviews.md
```

`--prompt-file` provides a domain-specific review prompt. For backward compatibility with upstream uses (`experiment-orchestrator`), the script also accepts `--kind {plan,phase}` with baked-in experiment-specific prompts.

Reads the frontier-model cache via `frontier_model_discovery.load_cache()`. Fails with a clear error if the cache is missing or incomplete.

Writes a markdown file with sections for each CLI's output plus a note reminding the human:

> When Gemini and Codex flag the same concern, treat it as real. Divergent comments are context, not verdicts — decide which to act on.

Required only if you use `--review-external`.

## `scaffold_docs_catalog.py`

Scaffolds `.claude/docs-catalog.json` — the single source of truth for the cross-cutting documentation files in your repo. Used by the docs-sweep lane (`SL-docs`) that every phase plan includes.

Usage:

```bash
# First-time scaffold (phase-roadmap-builder does this automatically)
python3 scaffold_docs_catalog.py

# Re-scan and merge new doc files created by impl lanes (SL-docs does this)
python3 scaffold_docs_catalog.py --rescan
```

Inventories common doc locations: root-level standards (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, `SECURITY.md`, etc.), agent-facing indexes (`llm.txt`, `llms.txt`, `llms-full.txt`), service manifests (`services.json`, `openapi.*`), and `docs/**`, `rfcs/**`, `adrs/**`. Preserves `touched_by_phases` history when rescanning so the catalog accumulates per-file phase provenance over time.

Committed to git — the catalog is repo state, not ephemeral.

## `next_reflection_path.py`

Emits the next reflection log path for a given skill. Used by the close-out step in artifact-producing skills to name their repo-agnostic reflections.

Usage:

```bash
python3 next_reflection_path.py <skill-name>
# → /home/<user>/.claude/skills/<skill-name>/reflections/<skill-name>-reflection-v<N>.md
```

Globs existing `<skill>-reflection-v*.md` files in the skill's `reflections/` subdir and returns the next incrementing version. Creates the parent directory if absent. Because `~/.claude/skills/<skill>/` is typically a symlink to the source repo, the file physically lands in the source repo (gitignored per `.gitignore`).

Required by the close-out reflection step in every artifact-producing planning-chain skill.
