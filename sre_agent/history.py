"""Incident memory (SQLite). This is what turns one-off diagnosis into 'permanent fix' recommendations."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone

from .models import Located, Signal

_NORM = re.compile(r"0x[0-9a-fA-F]+|[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}|\d+")
FIX_TYPES = ("workaround", "hotfix", "permanent")


def make_signature(signal: Signal, located: list[Located]) -> str:
    """Stable fingerprint: same bug => same signature, even if ids/numbers in the message differ."""
    if located:
        f, fn = located[0].path, located[0].frame.func
    elif signal.frames:
        f, fn = signal.frames[-1].file, signal.frames[-1].func
    else:
        f = fn = ""
    msg = _NORM.sub("N", signal.message)[:120]
    return hashlib.sha1("|".join([signal.exc_type, msg, f, fn]).encode()).hexdigest()[:12]


def _tokens(*parts: str) -> set[str]:
    return set(re.findall(r"[a-z_]{3,}", " ".join(parts).lower()))


class History:
    def __init__(self, path: str = "sre_history.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS incidents(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, signature TEXT, exc_type TEXT,
                message TEXT, file TEXT, func TEXT, root_cause TEXT, fix_summary TEXT,
                fix_type TEXT, resolved INTEGER DEFAULT 0)"""
        )
        self.db.commit()

    def record(self, signature: str, signal: Signal, located: list[Located], root_cause: str) -> int:
        f = located[0].path if located else ""
        fn = located[0].frame.func if located else ""
        cur = self.db.execute(
            "INSERT INTO incidents(ts,signature,exc_type,message,file,func,root_cause) VALUES(?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), signature, signal.exc_type,
             signal.message, f, fn, root_cause),
        )
        self.db.commit()
        return cur.lastrowid

    def resolve(self, incident_id: int, root_cause: str, fix: str, fix_type: str) -> None:
        if fix_type not in FIX_TYPES:
            raise ValueError(f"fix_type must be one of {FIX_TYPES}")
        self.db.execute(
            "UPDATE incidents SET root_cause=?, fix_summary=?, fix_type=?, resolved=1 WHERE id=?",
            (root_cause, fix, fix_type, incident_id),
        )
        self.db.commit()

    def similar(self, signature: str, signal: Signal, located: list[Located],
                limit: int = 5, threshold: float = 0.4) -> list[dict]:
        cur_tokens = _tokens(signal.exc_type, signal.message,
                             located[0].frame.func if located else "", located[0].path if located else "")
        scored = []
        for row in self.db.execute("SELECT * FROM incidents"):
            r = dict(row)
            if r["signature"] == signature:
                score = 1.0
            else:
                other = _tokens(r["exc_type"] or "", r["message"] or "", r["func"] or "", r["file"] or "")
                union = cur_tokens | other
                score = len(cur_tokens & other) / len(union) if union else 0.0
            if score >= threshold:
                r["score"] = round(score, 2)
                scored.append(r)
        scored.sort(key=lambda r: (r["score"], r["id"]), reverse=True)
        return scored[:limit]

    def recent(self, n: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (n,))]
