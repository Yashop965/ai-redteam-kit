"""CLI: author / grade / run for factloop (keyless factuality red-team loop).

  author   verify + score + rank candidates, emit paste-ready form blocks.
  grade    score a model answer you pasted from Google Search Mode; on a
           failure, emit the submission form block.
  run      (optional, needs a model) drive an Inspect web-research agent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from factloop.verify import analyze_all, analyze, CandidateResult
from factloop.formblock import ranked_markdown, form_block, _golden_line
from factloop.search import value_in_text


def _load(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        p = Path(__file__).parent / "candidates.json"
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_author(args) -> int:
    cands = _load(args.candidates)
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        cands = [c for c in cands if c.get("id") in keep]
    print(f"[author] {len(cands)} candidates -> verifying + scoring via web "
          f"search ({'search' if not args.no_search else 'offline'} mode) ...", flush=True)
    if args.no_search:
        # offline: skip web; mark all unverified, keep metadata only
        results = [CandidateResult(
            id=c.get("id", ""), type=c.get("type", ""),
            pinned_question=c.get("pinned_question", ""),
            golden=str(c.get("golden", "")),
            decoys=[str(d) for d in c.get("decoys", [])],
            verified=False, evidence_domains=[], sources=c.get("source_urls", []),
            buried=False, decoy_salient=False, breaker_score=0.0,
            notes="offline (no web)", raw=c) for c in cands]
    else:
        results = analyze_all(cands, fast=args.fast)
        for r in results:
            flag = "OK " if r.verified else "BAD"
            print(f"  [{flag}] {r.id:<22} score={r.breaker_score:<5} "
                  f"ver={r.verified} strong={r.strong} "
                  f"buried={r.buried} decoy?={r.decoy_salient}")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results.json").write_text(
        json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8")
    (outdir / "form_blocks.md").write_text(ranked_markdown(results), encoding="utf-8")
    print(f"\n[author] wrote {outdir/'results.json'} and {outdir/'form_blocks.md'}")
    valid = [r for r in results if r.verified]
    if valid:
        print(f"[author] top {min(args.limit, len(valid))} to test manually:")
        for i, r in enumerate(valid[:args.limit], 1):
            print(f"  {i}. {r.id}  ->  test: {r.pinned_question!r}")
    return 0


def _target_of(cand: dict):
    items = cand.get("golden_items")
    return items if items else str(cand.get("golden", ""))


def _grade_answer(answer: str, cand: dict) -> tuple[str, str]:
    target = _target_of(cand)
    if isinstance(target, list):
        missing = [i for i in target if str(i).lower() not in answer.lower()]
        if not missing:
            return "CORRECT", "all required items present"
        if len(missing) == len(target):
            return "INCORRECT", "none of the required items present"
        return "PARTIAL", "missing: " + ", ".join(map(str, missing))
    return ("CORRECT" if value_in_text(answer, str(target)) else "INCORRECT",
            "golden present" if value_in_text(answer, str(target))
            else f"golden '{target}' not found in answer")


def cmd_grade(args) -> int:
    cands = _load(args.candidates)
    cand = next((c for c in cands if c.get("id") == args.id), None)
    if cand is None:
        print(f"[grade] unknown id '{args.id}'. Available: "
              f"{', '.join(c.get('id','') for c in cands)}", file=sys.stderr)
        return 2
    answer = args.answer if args.answer is not None else sys.stdin.read().strip()
    verdict, reason = _grade_answer(answer, cand)
    print(f"[grade] {args.id}: {verdict} - {reason}")
    if verdict != "CORRECT":
        # this is a breaker: emit the submission form block (offline; the block
        # is built from the candidate's own fields - no web needed to grade).
        res = CandidateResult(
            id=cand.get("id", ""), type=cand.get("type", ""),
            pinned_question=cand.get("pinned_question", ""),
            golden=str(cand.get("golden", "")),
            decoys=[str(d) for d in cand.get("decoys", [])],
            verified=True, evidence_domains=[],
            sources=cand.get("source_urls", []),
            buried=True, decoy_salient=True, breaker_score=0.0,
            notes="graded: model failed",
            raw=cand)
        print("\n=== SUBMISSION FORM BLOCK (model failed this one) ===\n")
        print(form_block(res))
        print("\n=== MODEL OUTPUT TO PASTE VERBATIM ===\n")
        print(answer)
    return 0


def cmd_run(args) -> int:
    from factloop.task import run as task_run
    cands = _load(args.candidates)
    report = task_run(cands, model=args.model, top=args.top, outdir=args.out)
    if not report:
        return 1
    fails = [r for r in report if r["verdict"] in ("INCORRECT", "PARTIAL")]
    print(f"[run] {len(report)} candidates vs {args.model}; "
          f"{len(fails)} failures:")
    for r in report:
        mark = "FAIL" if r["verdict"] in ("INCORRECT", "PARTIAL") else "ok  "
        print(f"  [{mark}] {r['id']}: {r['verdict']} - {r['reason']}")
        print(f"        target={r['target']!r} answer={ (r['answer'] or '')[:80]!r}")
    if fails:
        print("\n[run] first failure is your submission; open "
              f"{args.out}/logs for full traces.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="factloop (keyless factuality red-team loop)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("author", help="verify + score + rank + emit form blocks")
    a.add_argument("--candidates", default="candidates.json")
    a.add_argument("--out", default="out")
    a.add_argument("--limit", type=int, default=5)
    a.add_argument("--no-search", action="store_true",
                   help="skip web verification (offline; candidates stay unverified)")
    a.add_argument("--only", default="",
                   help="comma-separated candidate ids to process (faster iteration)")
    a.add_argument("--fast", action="store_true",
                   help="snippet-only verification (skip page fetches; much quicker)")
    a.set_defaults(fn=cmd_author)

    g = sub.add_parser("grade", help="score a pasted model answer; emit block on fail")
    g.add_argument("--id", required=True)
    g.add_argument("--answer", default=None,
                   help="model output to score; if omitted, read from stdin")
    g.add_argument("--candidates", default="candidates.json")
    g.add_argument("--no-search", action="store_true")
    g.set_defaults(fn=cmd_grade)

    r = sub.add_parser("run", help="run an Inspect web-research agent (needs a model)")
    r.add_argument("--model", required=True,
                   help="e.g. openai/gpt-4o, anthropic/claude-3-5-sonnet, or local")
    r.add_argument("--top", type=int, default=5)
    r.add_argument("--candidates", default="candidates.json")
    r.add_argument("--out", default="out")
    r.set_defaults(fn=cmd_run)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
