from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import Located, Signal


@dataclass
class Report:
    signal: Signal
    located: list[Located]
    signature: str
    verdict: dict
    matches: list[dict]
    result: dict
    source: str                    # "llm" | "heuristic"
    incident_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id, "signature": self.signature, "analyzer": self.source,
            "error": {"type": self.signal.exc_type, "message": self.signal.message, "service": self.signal.service},
            "graphql": {
                "path": self.signal.graphql_path,
                "code": self.signal.graphql_code,
            } if self.signal.graphql_path is not None or self.signal.graphql_code is not None else None,
            "history": {"verdict": self.verdict["kind"], "text": self.verdict["text"], "matches": self.matches},
            **self.result,
        }

    def _loc_for(self, fl: dict) -> Optional[Located]:
        for l in self.located:
            if l.path == fl.get("file") and l.frame.line == fl.get("line"):
                return l
        return None

    def render(self) -> str:
        s, r = self.signal, self.result
        fl, pf = r["fix_location"], r["permanent_fix"]
        o = [
            f"INCIDENT  {s.exc_type}: {s.message}",
            f"  service={s.service or '-'}  signature={self.signature}  incident_id={self.incident_id or '-'}  analyzer={self.source}",
        ]
        if s.graphql_path is not None:
            o.append(f"  GraphQL path: {'.'.join(str(part) for part in s.graphql_path)}")
        if s.graphql_code:
            o.append(f"  GraphQL code: {s.graphql_code}")
        o += ["", "WHERE TO FIX", f"  {fl['file']}:{fl['line']}  in {fl['function']}()"]
        loc = self._loc_for(fl)
        if loc:
            for n, t in loc.snippet:
                o.append(f"  {'>' if n == loc.frame.line else ' '} {n:4d} | {t}")
            if loc.blame:
                b = loc.blame
                o.append(f"  last change to this line: {b.get('author')} {b.get('date')} ({b.get('commit')}) \"{b.get('summary')}\"")
        o.append(f"  why: {fl['reason']}")
        o += ["", f"ROOT CAUSE  (confidence {r.get('confidence', 0):.0%})", f"  {r['root_cause']}",
              "", "IMMEDIATE MITIGATION", f"  {r['immediate_mitigation']}",
              "", "PERMANENT FIX", f"  {pf['description']}"]
        if pf.get("patch"):
            o += ["  patch / sketch:"] + [f"    {l}" for l in str(pf["patch"]).splitlines()]
        o += [f"  tests: {pf.get('tests', '')}", f"  prevention: {pf.get('prevention', '')}",
              "", f"HISTORY  [{self.verdict['kind']}]", f"  {self.verdict['text']}"]
        for m in self.matches:
            fix = f"{m['fix_type']}: {m['fix_summary']}" if m.get("fix_summary") else "no fix recorded"
            o.append(f"  - #{m['id']} {m['ts'][:10]} score={m['score']} -> {fix}")
        return "\n".join(o)
