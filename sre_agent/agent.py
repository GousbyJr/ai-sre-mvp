"""Orchestrates: parse -> locate -> recall history -> diagnose (LLM, else rules) -> report."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .history import History, make_signature
from .llm import ask_json
from .locator import locate
from .models import Located, Signal
from .parser import parse_log
from .report import Report
from .rules import heuristic

SYSTEM = """You are a senior Site Reliability Engineer. Given a production error, the exact code around each
in-repo stack frame, git blame/recent commits, and this team's past incident history, you must:
1. Pinpoint the EXACT file, line and function where the fix belongs. This may be a caller or the producer of
   a bad value rather than the frame that raised; justify the choice.
2. Give the real root cause (not just the symptom).
3. Give an immediate mitigation for the on-call.
4. Give a PERMANENT fix that removes the class of bug, with a concrete code patch (unified diff or snippet),
   tests, and prevention (alerts, types, validation).
5. Use history: if this incident recurred after a workaround/hotfix, say the symptom was masked and fix the
   underlying cause; if it was permanently fixed before, treat it as a regression and point at what changed;
   reuse proven past fixes when relevant.
Be specific and grounded in the provided code. Do not invent files or lines. Respond with ONLY JSON."""

SCHEMA = """{
  "summary": str,
  "root_cause": str,
  "confidence": number between 0 and 1,
  "fix_location": {"file": str, "line": int, "function": str, "reason": str},
  "immediate_mitigation": str,
  "permanent_fix": {"description": str, "patch": str, "tests": str, "prevention": str}
}"""


def history_verdict(matches: list[dict], signature: str) -> dict:
    exact = [m for m in matches if m["signature"] == signature]
    permanent = [m for m in exact if m.get("fix_type") == "permanent"]
    if permanent:
        ids = ", ".join(f"#{m['id']}" for m in permanent)
        return {"kind": "regression", "text": f"Same failure was permanently fixed before ({ids}). This is a regression: check what changed in that code path since."}
    if exact:
        ids = ", ".join(f"#{m['id']}" for m in exact)
        types = sorted({m.get("fix_type") or "unresolved" for m in exact})
        return {"kind": "recurring", "text": f"Seen {len(exact)} time(s) before ({ids}); remedies so far: {', '.join(types)}. None permanent, so the symptom is being masked. Fix the root cause."}
    fixed = [m for m in matches if m.get("fix_summary")]
    if fixed:
        return {"kind": "similar", "text": f"{len(fixed)} similar past incident(s) had recorded fixes; reuse what worked."}
    return {"kind": "new", "text": "No comparable past incident."}


def build_prompt(signal: Signal, located: list[Located], verdict: dict, matches: list[dict]) -> str:
    p = [f"ERROR: {signal.exc_type}: {signal.message}", f"SERVICE: {signal.service or 'unknown'}",
         "STACK (outermost -> innermost):"]
    p += [f"  {f.file}:{f.line} in {f.func}" for f in signal.frames]
    for l in located:
        p.append(f"\n--- {l.path}:{l.frame.line} in {l.frame.func} ---")
        p += [f"{'>>' if n == l.frame.line else '  '} {n:4d} | {t}" for n, t in l.snippet]
        if l.blame:
            p.append(f"blame(line): {l.blame}")
        if l.recent_commits:
            p.append("recent commits to file: " + "; ".join(f"{c['date']} {c['author']}: {c['summary']}" for c in l.recent_commits))
    p.append(f"\nHISTORY VERDICT: {verdict['kind']} - {verdict['text']}")
    for m in matches:
        p.append(f"  past #{m['id']} score={m['score']} cause={m['root_cause']!r} fix_type={m['fix_type']} fix={m['fix_summary']!r}")
    p.append(f"\nReturn JSON matching exactly:\n{SCHEMA}")
    return "\n".join(p)


def _normalize(result: dict, located: list[Located]) -> dict:
    top = located[0] if located else None
    fl = result.setdefault("fix_location", {})
    fl.setdefault("file", top.path if top else "unknown")
    fl.setdefault("line", top.frame.line if top else 0)
    fl.setdefault("function", top.frame.func if top else "")
    fl.setdefault("reason", "")
    pf = result.setdefault("permanent_fix", {})
    for k in ("description", "patch", "tests", "prevention"):
        pf.setdefault(k, "")
    result.setdefault("summary", "")
    result.setdefault("root_cause", "")
    result.setdefault("confidence", 0.5)
    result.setdefault("immediate_mitigation", "")
    return result


def analyze(log_text: str, repo: str | Path, history: Optional[History] = None,
            service: Optional[str] = None, record: bool = True, use_llm: bool = True) -> Report:
    signal = parse_log(log_text, service)
    if not signal:
        raise ValueError("No stack trace found in the supplied log.")
    located = locate(repo, signal)
    signature = make_signature(signal, located)
    matches = history.similar(signature, signal, located) if history else []
    verdict = history_verdict(matches, signature)

    result = ask_json(SYSTEM, build_prompt(signal, located, verdict, matches)) if use_llm else None
    source = "llm" if result else "heuristic"
    if not result:
        result = heuristic(signal, located, verdict)
    result = _normalize(result, located)

    incident_id = history.record(signature, signal, located, result["root_cause"]) if history and record else None
    return Report(signal, located, signature, verdict, matches, result, source, incident_id)
