"""Run an artifact through both Gemini and Codex CLIs in parallel.

Generalized fork of experiment-orchestrator's review_with_cli.py. The
reviewer prompt can come from a file (``--prompt-file``) for per-skill
customization, or from the baked-in constants via ``--kind``.

Usage::

    # Per-skill prompt file
    python -m review_with_cli \
        --artifact plans/phase-plan-v1-p1.md \
        --prompt-file /path/to/review_prompt.md \
        --out plans/phase-plan-v1-p1_reviews.md

    # Legacy experiment-orchestrator mode
    python -m review_with_cli \
        --artifact specs/experiment_log/stage_50.md \
        --kind plan \
        --out specs/experiment_log/stage_50_reviews.md

Discovers models via ``frontier_model_discovery`` (24h cache).
Each reviewer gets identical input; agreements are real signal, divergences
are context for the human.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_model_discovery import load_cache


PLAN_REVIEW_PROMPT = textwrap.dedent("""
    Review the following experiment stage plan for a transformer-model
    research project running on a queue-scheduled multi-GPU cluster.
    Assess, concretely:

    1. Falsifiability — is every sub-hypothesis tied to a phase whose
       outcome could in principle falsify it?
    2. Scheduling — given the hard-dep DAG described, could any phase be
       parallelized earlier?
    3. Redundancy — is any phase already covered by prior work cited in
       the literature-review section?
    4. Methodology gaps — is the independent variable crisp? Are controls
       and baselines matched in every phase?
    5. Over-fitting to one outcome — does the stage's decision tree cover
       both "hypothesis survives" and "hypothesis fails"?

    Be specific. Cite phase IDs and line numbers.

    ARTIFACT:
""").strip()

PHASE_REVIEW_PROMPT = textwrap.dedent("""
    Review the following phase script running on a queue-scheduled GPU
    worker. Assess, concretely:

    1. Determinism — uncontrolled randomness that would make results
       unreproducible?
    2. Correctness — does the independent variable isolate what the
       docstring claims?
    3. Resource sizing — will this OOM on the stated VRAM tier?
    4. Canonical conventions — output path, CLI flags, progress match
       the project reference?
    5. Silent failure modes — any .to(device)/cast/slice that could
       silently degrade?

    Be specific. Cite line numbers.

    ARTIFACT:
""").strip()


def _run_cli(cmd: list[str], stdin: str, label: str) -> dict:
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"label": label, "ok": False, "error": "timeout"}
    except FileNotFoundError as e:
        return {"label": label, "ok": False, "error": f"cli not installed: {e}"}
    return {
        "label": label,
        "ok": p.returncode == 0,
        "stdout": p.stdout,
        "stderr": p.stderr[-2000:] if p.stderr else "",
        "returncode": p.returncode,
    }


def _gemini_cmd(model: str, thinking_flag: str, prompt: str) -> list[str]:
    cmd = ["gemini", "-m", model, "-p", prompt]
    if thinking_flag:
        cmd.append(thinking_flag)
    return cmd


def _codex_cmd(model: str, effort_flag: str, prompt: str) -> list[str]:
    cmd = ["codex", "exec", "-m", model]
    if effort_flag:
        cmd.append(effort_flag)
    cmd.append(prompt)
    return cmd


def _resolve_prompt_head(kind: str | None, prompt_file: Path | None) -> str:
    if prompt_file is not None:
        if not prompt_file.exists():
            raise FileNotFoundError(f"prompt file not found: {prompt_file}")
        return prompt_file.read_text().strip()
    if kind == "plan":
        return PLAN_REVIEW_PROMPT
    if kind == "phase":
        return PHASE_REVIEW_PROMPT
    raise ValueError("Either --prompt-file or --kind {plan,phase} must be supplied")


def review(artifact_path: Path, prompt_head: str) -> dict:
    if not artifact_path.exists():
        raise FileNotFoundError(artifact_path)

    body = artifact_path.read_text()
    prompt = f"{prompt_head}\n\n{body}"

    models = load_cache() or {}
    gemini_model = models.get("gemini_model") or ""
    codex_model = models.get("codex_model") or ""
    if not gemini_model or not codex_model:
        return {
            "ok": False,
            "error": (
                "frontier_model_discovery cache is empty or incomplete. "
                "Run `python3 frontier_model_discovery.py --resolve` to emit the "
                "discovery prompt, execute the four-tool pattern, then "
                "`--save <json>` to populate."
            ),
            "models": models,
        }

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        fut_g = pool.submit(
            _run_cli,
            _gemini_cmd(gemini_model, models.get("gemini_thinking_flag", ""), prompt),
            "", "gemini",
        )
        fut_c = pool.submit(
            _run_cli,
            _codex_cmd(codex_model, models.get("codex_effort_flag", ""), prompt),
            "", "codex",
        )
        g = fut_g.result()
        c = fut_c.result()

    return {
        "ok": g["ok"] and c["ok"],
        "artifact": str(artifact_path),
        "gemini_model": gemini_model,
        "codex_model": codex_model,
        "gemini": g,
        "codex": c,
    }


def render_markdown(result: dict) -> str:
    if not result.get("ok") and "error" in result:
        return f"# Review failed\n\n{result['error']}\n"

    lines = [f"# Review of `{result['artifact']}`", ""]
    lines.append(f"- **Gemini model**: `{result['gemini_model']}`")
    lines.append(f"- **Codex model**: `{result['codex_model']}`")
    lines.append("")
    lines.append("## Gemini")
    lines.append("")
    lines.append(result["gemini"].get("stdout", "").strip() or "_(no output)_")
    lines.append("")
    lines.append("## Codex")
    lines.append("")
    lines.append(result["codex"].get("stdout", "").strip() or "_(no output)_")
    lines.append("")
    lines.append("## Notes for the human reviewer")
    lines.append("")
    lines.append(
        "When Gemini and Codex flag the same concern, treat it as real. "
        "Divergent comments are context, not verdicts — decide which to act on."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt-file", type=Path, help="Path to a markdown prompt file")
    group.add_argument("--kind", choices=("plan", "phase"), help="Use a baked-in experiment prompt")
    args = ap.parse_args(argv)

    try:
        prompt_head = _resolve_prompt_head(args.kind, args.prompt_file)
        result = review(args.artifact, prompt_head)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(result))
    json.dump({"ok": result.get("ok", False), "out": str(args.out)}, sys.stdout)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
