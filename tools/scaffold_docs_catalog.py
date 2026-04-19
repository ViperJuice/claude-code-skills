#!/usr/bin/env python3
"""Scaffold or refresh .claude/docs-catalog.json.

Run from the repo root. Inventories common documentation files and writes
(or updates) `.claude/docs-catalog.json`. Three modes:

    scaffold_docs_catalog.py              # scaffold if absent; no-op if exists
    scaffold_docs_catalog.py --rescan     # re-scan repo; merge new files,
                                          # preserve existing touched_by_phases history
    scaffold_docs_catalog.py --force      # alias for --rescan
    scaffold_docs_catalog.py --path <dir> # override .claude location

Typical use:

- `phase-roadmap-builder` calls without flags on first run to bootstrap.
- `SL-docs` lane calls with `--rescan` at the start of its work to pick
  up any new doc files created by impl lanes in the current phase.

History (`touched_by_phases`) is always preserved. The SL-docs lane then
edits the file in place to add the current phase alias to files it actually
changed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Known well-named files we always look for at the repo root or common locations.
KNOWN_FILES = [
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "MIGRATION.md",
    "ARCHITECTURE.md",
    "DESIGN.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    # AI/agent-facing indexes
    "llm.txt",
    "llms.txt",
    "llms-full.txt",
    # Service manifests
    "services.json",
    "openapi.yaml",
    "openapi.yml",
    "openapi.json",
]

# Directories to scan recursively for *.md (one level deep on purpose —
# avoids sucking in generated or vendored docs).
SCAN_DIRS = ["docs", ".claude", "specs", "plans", "rfcs", "adrs"]

DEFAULT_PURPOSES = {
    "README.md": "root project README",
    "CHANGELOG.md": "release changelog",
    "CONTRIBUTING.md": "contribution guidelines",
    "CODE_OF_CONDUCT.md": "code of conduct",
    "SECURITY.md": "security policy",
    "MIGRATION.md": "migration guide",
    "ARCHITECTURE.md": "system architecture",
    "DESIGN.md": "design notes",
    "AGENTS.md": "agent/tooling instructions",
    "CLAUDE.md": "Claude Code project instructions",
    "GEMINI.md": "Gemini CLI instructions",
    "llm.txt": "agent-facing repo index",
    "llms.txt": "agent-facing repo index (multi-file)",
    "llms-full.txt": "agent-facing full repo context",
    "services.json": "service manifest",
    "openapi.yaml": "OpenAPI specification",
    "openapi.yml": "OpenAPI specification",
    "openapi.json": "OpenAPI specification",
}


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        )
        return Path(out.decode().strip())
    except subprocess.CalledProcessError:
        return Path.cwd()


def _find_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for name in KNOWN_FILES:
        p = root / name
        if p.is_file():
            found.append(p)
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            if p.is_file():
                found.append(p)
    # Dedup while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _purpose_for(rel: str) -> str:
    name = Path(rel).name
    if name in DEFAULT_PURPOSES:
        return DEFAULT_PURPOSES[name]
    if rel.startswith("specs/") and name.startswith("phase-plans"):
        return "multi-phase roadmap spec"
    if rel.startswith("plans/") and name.startswith("phase-plan"):
        return "per-phase lane plan"
    if rel.startswith("rfcs/") or rel.startswith("adrs/"):
        return "design record / RFC"
    return "markdown document"


def build_catalog(root: Path, prior: dict | None = None) -> dict:
    files = _find_files(root)
    prior_files = (prior or {}).get("files", {})
    catalog = {
        "version": 1,
        "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {},
    }
    for p in files:
        rel = str(p.relative_to(root))
        prev = prior_files.get(rel, {})
        catalog["files"][rel] = {
            "purpose": prev.get("purpose") or _purpose_for(rel),
            "touched_by_phases": list(prev.get("touched_by_phases", [])),
        }
    return catalog


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rescan", "--force", dest="rescan", action="store_true",
                    help="re-scan repo; merge new files, preserve history")
    ap.add_argument("--path", type=Path, default=None, help="override .claude dir")
    args = ap.parse_args(argv[1:])

    root = _repo_root()
    catalog_path = (args.path or (root / ".claude")) / "docs-catalog.json"

    existing: dict | None = None
    if catalog_path.exists():
        try:
            existing = json.loads(catalog_path.read_text())
        except json.JSONDecodeError:
            print(f"warn: existing {catalog_path} is not valid JSON; rebuilding", file=sys.stderr)
            existing = None
        if not args.rescan:
            print(f"catalog exists at {catalog_path}; no-op. Use --rescan to refresh.")
            return 0

    catalog = build_catalog(root, prior=existing)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"wrote {catalog_path} ({len(catalog['files'])} files inventoried)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
