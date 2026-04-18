"""Discover current frontier Gemini + Codex models via the same four-tool
pattern used for literature review: BrightData search, BrightData scrape,
fetch, Context7.

This script does NOT call PMCP tools directly (the Python runtime doesn't
have access to the MCP gateway). Instead, it acts as a *contract*:

1. When called with ``--resolve``, it checks the cache
   (``~/.claude/cache/frontier_models.json``). If fresh (<24h), returns it.
2. If stale, it prints a structured prompt block that the calling Claude
   session must execute via PMCP tools, then writes the resolved values
   back to cache.

The four-tool pattern for model discovery:
- **Search**: ``brightdata::search_engine`` for
  "Google Gemini latest model <YEAR> extended thinking most capable" and
  "OpenAI GPT latest model <YEAR> Codex".
- **Scrape**: ``brightdata::scrape_as_markdown`` on the top hits (Google AI
  blog, OpenAI release notes, model-card pages) to confirm model IDs,
  context windows, and thinking/effort flags.
- **Fetch**: ``fetch::*`` for known URLs as a fallback
  (``ai.google.dev``, ``platform.openai.com``).
- **Context7**: ``context7::query-docs`` on the ``gemini-cli`` and
  ``codex`` packages to confirm the CLI flag names.

Output schema cached to disk::

    {
      "gemini_model": "gemini-3.1-pro-preview",
      "gemini_thinking_flag": "--extended-thinking",
      "codex_model": "gpt-5.4",
      "codex_effort_flag": "--reasoning-effort=high",
      "resolved_at": "2026-04-14T12:00:00+00:00"
    }
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

CACHE_PATH = Path.home() / ".claude" / "cache" / "frontier_models.json"
CACHE_TTL_SEC = 24 * 3600


def _is_fresh(data: dict) -> bool:
    ts = data.get("resolved_at")
    if not ts:
        return False
    try:
        then = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return False
    now = _dt.datetime.now(_dt.timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=_dt.timezone.utc)
    return (now - then).total_seconds() < CACHE_TTL_SEC


def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return None


def save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {**data, "resolved_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    CACHE_PATH.write_text(json.dumps(data, indent=2))


def discovery_prompt(year: int | None = None) -> str:
    year = year or _dt.date.today().year
    return f"""Resolve the current frontier Gemini and Codex CLI models.

Use all four PMCP tool families, in order:

1. brightdata::search_engine with these queries:
     - "most capable Google Gemini model {year} extended thinking CLI"
     - "OpenAI GPT {year} Codex CLI latest model reasoning effort"
   Capture top 5 result URLs each.

2. brightdata::scrape_as_markdown on the top 2 URLs per query. Look for:
     - Gemini: model ID (e.g. "gemini-3.1-pro-preview"), flag for extended
       thinking / reasoning mode
     - GPT/Codex: model ID (e.g. "gpt-5.4"), flag for reasoning effort

3. fetch on canonical pages as fallback if scrape fails:
     - https://ai.google.dev/gemini-api/docs/models
     - https://platform.openai.com/docs/models

4. context7::resolve-library-id then query-docs for:
     - library "gemini-cli": confirm -m flag and thinking/reasoning flag name
     - library "openai codex CLI": confirm -m flag and reasoning-effort flag

Write the result back with save_cache() using this shape:
  {{
    "gemini_model":        "<id>",
    "gemini_thinking_flag":"<flag or ''>",
    "codex_model":         "<id>",
    "codex_effort_flag":   "<flag or ''>"
  }}

If any field cannot be resolved confidently, leave it as "" rather than
guessing. The skill will surface empty fields to the user.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolve", action="store_true",
                    help="Print resolution prompt if cache stale; else print cached values.")
    ap.add_argument("--refresh", action="store_true",
                    help="Force re-resolution (ignore cache).")
    ap.add_argument("--show", action="store_true",
                    help="Print cached values as JSON, or empty if no cache.")
    ap.add_argument("--save", type=str, default=None,
                    help="JSON string to write to cache (used by Claude after resolving).")
    args = ap.parse_args(argv)

    if args.save:
        data = json.loads(args.save)
        save_cache(data)
        json.dump(load_cache(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.show:
        cache = load_cache()
        json.dump(cache or {}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    cache = load_cache()
    if cache and _is_fresh(cache) and not args.refresh:
        json.dump(cache, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print("# frontier_model_discovery: cache stale or --refresh. "
          "Run the following via PMCP tools then call:")
    print("#   python -m frontier_model_discovery --save '<json>'")
    print()
    print(discovery_prompt())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
