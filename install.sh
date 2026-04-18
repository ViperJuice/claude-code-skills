#!/usr/bin/env bash
# Install claude-code-skills into ~/.claude/skills/ or a project's .claude/skills/.
#
# Usage:
#   ./install.sh              # install to ~/.claude/skills/ (user scope)
#   ./install.sh .claude      # install to ./.claude/skills/ (project scope)
#
# Creates symlinks (not copies) so `git pull` in this repo updates installed
# skills immediately. Use `./install.sh --copy` if you prefer copies.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="symlink"
TARGET_BASE="$HOME/.claude"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --copy) MODE="copy"; shift ;;
        --help|-h)
            head -10 "$0" | sed 's|^# ||; s|^#$||'
            exit 0
            ;;
        *) TARGET_BASE="$(cd "$1" && pwd)"; shift ;;
    esac
done

SKILLS_DIR="$TARGET_BASE/skills"
mkdir -p "$SKILLS_DIR"

install_entry() {
    local src="$1"
    local dest="$2"
    if [[ "$MODE" == "symlink" ]]; then
        ln -sfn "$src" "$dest"
    else
        rm -rf "$dest"
        cp -r "$src" "$dest"
    fi
    echo "  $MODE: $dest"
}

echo "Installing claude-code-skills to: $SKILLS_DIR"

# Planning chain
for d in "$REPO_ROOT"/planning-chain/*/; do
    [[ -d "$d" ]] || continue
    install_entry "${d%/}" "$SKILLS_DIR/$(basename "$d")"
done

# Efficiency kit
for d in "$REPO_ROOT"/efficiency-kit/*/; do
    [[ -d "$d" ]] || continue
    install_entry "${d%/}" "$SKILLS_DIR/$(basename "$d")"
done

# Shared tools — land at .claude/skills/_shared/ to match the paths in SKILL.md
mkdir -p "$SKILLS_DIR/_shared"
for f in "$REPO_ROOT"/tools/*.py; do
    [[ -f "$f" ]] || continue
    if [[ "$MODE" == "symlink" ]]; then
        ln -sf "$f" "$SKILLS_DIR/_shared/$(basename "$f")"
    else
        cp "$f" "$SKILLS_DIR/_shared/$(basename "$f")"
    fi
    echo "  $MODE: $SKILLS_DIR/_shared/$(basename "$f")"
done

# Template (optional reference for writing your own skills)
install_entry "$REPO_ROOT/_template" "$SKILLS_DIR/_template"

echo ""
echo "Done. Skills installed at: $SKILLS_DIR"
echo "See $REPO_ROOT/CONSIDERATIONS.md for prerequisites and custom-tool setup."
