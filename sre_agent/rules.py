"""Deterministic fallback analyzer (no LLM needed). Same output schema as the LLM path."""
from __future__ import annotations

from .models import Located, Signal


def _rule(signal: Signal, code: str) -> dict:
    t = signal.exc_type.split(".")[-1]
    msg = signal.message
    low = msg.lower()

    if "nonetype" in low:
        return dict(
            cause=f"A value that can be None is used without a check: `{code}`. Usually an upstream lookup/call returned None (missing record, expired or unknown key).",
            mitigation="Guard the failing line and return a clear 4xx/default for the bad input; if one input triggers it, reject that input at the boundary.",
            permanent="Make the producer's contract explicit: raise a domain error (e.g. NotFound) instead of returning None, handle it once at the call site, and type the function Optional/Result so mypy flags unguarded uses.",
            patch="# producer\nvalue = lookup(key)\nif value is None:\n    raise NotFoundError(key)   # or return a typed Result\n\n# call site\ntry:\n    value = lookup(key)\nexcept NotFoundError:\n    return error_response(400, 'unknown key')",
            tests="Add a test that passes the missing/expired key and asserts a handled 4xx, not a 500.",
            prevention="Enable mypy --strict on this module; validate request payloads at the API boundary.")
    if t == "KeyError":
        return dict(
            cause=f"Required key {msg} is missing from a dict/payload at `{code}`.",
            mitigation="Use .get() with an explicit failure path for this key and return a 4xx for the malformed payload.",
            permanent="Validate payloads against a schema (pydantic/dataclass) at the boundary so shape errors surface once, with a clear message, instead of KeyErrors deep in the code.",
            patch="class Payload(BaseModel):\n    amount: Decimal\n\npayload = Payload.model_validate(raw)  # fails fast at the boundary",
            tests="Add a test with the key missing and assert a validation error.",
            prevention="Schema-validate every inbound message/event; add contract tests with upstream producers.")
    if t == "ZeroDivisionError":
        return dict(
            cause=f"Divisor can be zero at `{code}` (empty set / zero count not handled).",
            mitigation="Return 0/None for the empty case at this line.",
            permanent="Define the empty-input behavior explicitly in the function and cover it with a test; avoid computing ratios from raw counts without a guard.",
            patch="return numerator / denominator if denominator else 0.0",
            tests="Add a test with an empty input.",
            prevention="Property-based tests on aggregation helpers.")
    if t == "IndexError":
        return dict(
            cause=f"Index out of range at `{code}` (empty or shorter-than-expected sequence).",
            mitigation="Check length before indexing and handle the empty case.",
            permanent="Replace positional assumptions with explicit unpacking/validation at the data's entry point.",
            patch="if not items:\n    return handle_empty()\nfirst = items[0]",
            tests="Test with empty and single-element input.",
            prevention="Validate upstream response shapes.")
    if any(k in t.lower() for k in ("timeout", "connection", "operationalerror", "unavailable")) or "timed out" in low or "connection" in low:
        return dict(
            cause=f"Dependency call failed (`{t}: {msg}`) at `{code}`: no resilience around a network/DB dependency.",
            mitigation="Check dependency health; restart/scale only if the pool is exhausted. Raise timeouts temporarily if the dependency is slow but healthy.",
            permanent="Wrap the call with explicit timeouts, bounded retries with exponential backoff + jitter (idempotent calls only), a circuit breaker, and right-sized connection pools. Alert on dependency latency, not just errors.",
            patch="resp = retry(call, attempts=3, backoff=exp_jitter(0.2, 2.0), timeout=2.0)\n# + circuit breaker around `call`",
            tests="Fault-injection test: dependency times out -> request degrades gracefully.",
            prevention="Add SLO + latency alert on this dependency; load-test pool sizing.")
    if t in ("ValueError", "JSONDecodeError", "UnicodeDecodeError"):
        return dict(
            cause=f"Input could not be parsed/converted at `{code}`: {msg}",
            mitigation="Reject the bad input with a 4xx and log the offending payload id.",
            permanent="Parse and validate at the boundary into typed objects; never pass raw strings deeper.",
            patch="try:\n    parsed = parse(raw)\nexcept ValueError as e:\n    raise BadRequest(str(e))",
            tests="Test with malformed input and assert a handled 4xx.",
            prevention="Fuzz the parser; add input validation metrics.")
    return dict(
        cause=f"{t}: {msg} raised at `{code}`. Not covered by built-in rules; set ANTHROPIC_API_KEY for LLM analysis.",
        mitigation="Roll back the most recent change to this file if the error began after a deploy.",
        permanent="Identify the invariant the code assumes, enforce it at the boundary, and add a regression test reproducing this stack trace.",
        patch="# add a guard/validation for the violated assumption on the failing line",
        tests="Add a regression test that reproduces the failing input.",
        prevention="Add an alert on this error signature.")


def heuristic(signal: Signal, located: list[Located], verdict: dict) -> dict:
    top = located[0] if located else None
    code = top.line_text.strip() if top else "<source not found in repo>"
    r = _rule(signal, code)
    prevention = r["prevention"]
    if verdict["kind"] in ("recurring", "regression", "similar"):
        prevention = f"HISTORY: {verdict['text']} {prevention}"
    return {
        "summary": f"{signal.exc_type}: {signal.message}",
        "root_cause": r["cause"],
        "confidence": 0.35,
        "fix_location": {
            "file": top.path if top else (signal.frames[-1].file if signal.frames else "unknown"),
            "line": top.frame.line if top else (signal.frames[-1].line if signal.frames else 0),
            "function": top.frame.func if top else (signal.frames[-1].func if signal.frames else ""),
            "reason": "Deepest in-repo frame where the failure surfaces. If the bad value originates upstream, fix its producer (see caller frames).",
        },
        "immediate_mitigation": r["mitigation"],
        "permanent_fix": {
            "description": r["permanent"], "patch": r["patch"], "tests": r["tests"], "prevention": prevention,
        },
    }
