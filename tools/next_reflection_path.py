#!/usr/bin/env python3
"""Emit the next reflection-log path for a skill.

Usage:
    next_reflection_path.py <skill-name>

Globs ~/.claude/skills/<skill>/reflections/<skill>-reflection-v*.md and
prints the next path at v<N+1>. v1 on first run. Creates the parent
directory if absent.

The path physically resolves through whatever ~/.claude/skills/<skill>/
symlinks to (dotfiles, claude-code-skills clone, or a local copy). Repos
should gitignore `<skill>/reflections/` so these files don't pollute
history.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"-reflection-v(\d+)\.md$")


def next_reflection_path(skill_name: str) -> Path:
    base = Path.home() / ".claude" / "skills" / skill_name / "reflections"
    base.mkdir(parents=True, exist_ok=True)
    max_version = 0
    for existing in base.glob(f"{skill_name}-reflection-v*.md"):
        m = VERSION_RE.search(existing.name)
        if m:
            try:
                max_version = max(max_version, int(m.group(1)))
            except ValueError:
                continue
    return base / f"{skill_name}-reflection-v{max_version + 1}.md"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <skill-name>", file=sys.stderr)
        return 2
    print(next_reflection_path(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
