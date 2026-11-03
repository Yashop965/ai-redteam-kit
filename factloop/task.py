"""Inspect-AI task wiring.

`to_samples` + the type-aware scorer are pure (no model needed) and power the
`author`/`grade` paths. `build_task`/`run` add an optional model-driven
web-research agent (needs a model key or local endpoint).
"""
from __future__ import annotations

import json
from pathlib import Path

from .search import search, fetch_text, value_in_text


def to_samples(cands: list[dict]):
    """Build Inspect Samples: input=question, target=golden (or JSON list for
    enumerations), so the scorer is fully target-driven."""
    from inspect_ai.dataset import Sample

    out = []
    for c in cands:
        items = c.get("golden_items")
        target = json.dumps(items) if items else str(c.get("golden", ""))
        meta = {k: c.get(k) for k in
                ("id", "type", "decoys", "golden_items", "justification",
                 "natural_queries", "verify_queries") if c.get(k) is not None}
        out.append(Sample(input=c.get("pinned_question", ""), target=target, metadata=meta))
    return out


def make_type_scorer():
    """Scorer handling single-value and enumeration targets.

    Enumeration targets are stored as a JSON list string; a sample is CORRECT
    only when every required item appears in the answer. Single-value targets
    are matched with the boundary-aware value_in_text (so '45' != '145').
    """
    from inspect_ai.scorer import scorer, Score

    def _answer_text(output) -> str:
        try:
            comps = getattr(output, "completions", None)
            if comps:
                last = comps[-1]
                return getattr(last, "content", str(last))
        except Exception:  # noqa: BLE001
            pass
        return str(output)

    @scorer(metrics=None)
    def type_scorer(output, target):
        ans = _answer_text(output)
        raw = str(target)
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = None
        verdict, reason = "CORRECT", ""
        if isinstance(parsed, list):
            missing = [i for i in parsed if str(i).lower() not in ans.lower()]
            if not missing:
                reason = "all required items present"
            elif len(missing) == len(parsed):
                verdict, reason = "INCORRECT", "none of the required items present"
            else:
                verdict, reason = "PARTIAL", "missing: " + ", ".join(map(str, missing))
        else:
            if value_in_text(ans, raw):
                reason = "golden value present"
            else:
                verdict, reason = "INCORRECT", f"golden '{raw}' not found in answer"
        return Score(value={"type_scorer": verdict, "reason": reason},
                     metadata={"answer": ans, "target": raw})

    return type_scorer


def build_task(cands: list[dict], model: str, with_tools: bool = True):
    """Build an Inspect Task. Best-effort agent + web tools; falls back to a
    plain generate-solver if the agent/tool API is unavailable."""
    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset

    samples = to_samples(cands)
    scorer = make_type_scorer()
    ds = MemoryDataset(samples)

    if with_tools:
        try:
            from inspect_ai.agent import general
            from inspect_ai.tool import tool, ToolResult

            @tool
            async def web_search(query: str) -> ToolResult:
                """Web search. Returns top results as {title,url,snippet}."""
                res = search(query, 6)
                return ToolResult(content=json.dumps(res, indent=2))

            @tool
            async def read_url(url: str) -> ToolResult:
                """Fetch a page and return its visible text (truncated)."""
                return ToolResult(content=fetch_text(url, 30, 20000))

            solver = general(
                instructions=(
                    "You are a meticulous web-research analyst. Use web_search "
                    "and read_url to find the exact factual answer. Prefer "
                    "primary/official sources. Answer with just the final value."
                ),
                tools=[web_search, read_url],
            )
            return Task(dataset=ds, solver=solver, scorer=scorer, model=model)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] agent/tools unavailable ({e}); using plain generate.")

    from inspect_ai import model as _modelmod  # noqa: F401  (ensures import)
    # Fallback: a single generate() as the solver (no tools).
    from inspect_ai.solver import generate

    async def _solve(state):
        await generate(state, system_message=(
            "Answer the question with the exact factual value only."))
        return state

    return Task(dataset=ds, solver=_solve, scorer=scorer, model=model)


def run(cands: list[dict], model: str, top: int = 5, outdir: str = "out") -> list[dict]:
    """Run the top-N verified candidates against `model`; return a report."""
    import sys
    from inspect_ai import eval as inspect_eval
    from inspect_ai.log import eval_log

    from .verify import analyze_all
    res = analyze_all(cands)
    topc = [r.raw for r in res if r.verified][:top]
    if not topc:
        print("No verified candidates to run.")
        return []
    task = build_task(topc, model)
    outdir_p = Path(outdir)
    outdir_p.mkdir(parents=True, exist_ok=True)
    log = inspect_eval(task, model=model,
                       log_dir=str(outdir_p / "logs"), limit=top)
    report = []
    for entry in (log if isinstance(log, list) else [log]):
        for s in (entry.samples if hasattr(entry, "samples") else []):
            md = getattr(s, "metadata", {}) or {}
            scored = getattr(s, "scores", {})
            ts = None
            for v in (scored.values() if isinstance(scored, dict) else []):
                val = getattr(v, "value", None)
                if isinstance(val, dict) and "type_scorer" in val:
                    ts = val
                    break
            report.append({
                "id": md.get("id"), "type": md.get("type"),
                "target": md.get("golden"),
                "answer": (ts or {}).get("answer", ""),
                "verdict": (ts or {}).get("type_scorer", "?"),
                "reason": (ts or {}).get("reason", ""),
            })
    return report
