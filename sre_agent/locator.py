"""Map stack frames to repo files and attach code + git context (blame, recent commits)."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Located, Signal

SKIP = ("site-packages", "dist-packages", "<frozen", "/lib/python", "node_modules", "<string>", "<stdin>")


def _git(repo: Path, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=15)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _resolve(repo: Path, file: str) -> Optional[Path]:
    if any(s in file for s in SKIP):
        return None
    p = Path(file)
    parts = p.parts[1:] if p.is_absolute() else p.parts
    for i in range(len(parts)):
        cand = repo.joinpath(*parts[i:])
        if cand.is_file() and repo in cand.resolve().parents:
            return cand.resolve()
    if len(parts) == 1:  # Java frames only carry a bare file name
        for c in repo.rglob(parts[0]):
            if ".git" not in c.parts:
                return c.resolve()
    return None


def _snippet(path: Path, line: int, ctx: int = 6) -> list[tuple[int, str]]:
    try:
        src = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    lo, hi = max(1, line - ctx), min(len(src), line + ctx)
    return [(n, src[n - 1]) for n in range(lo, hi + 1)]


def _blame(repo: Path, rel: str, line: int) -> Optional[dict]:
    out = _git(repo, "blame", "-L", f"{line},{line}", "--porcelain", "--", rel)
    if not out:
        return None
    d = {"commit": out.split()[0][:8]}
    for l in out.splitlines():
        if l.startswith("author "):
            d["author"] = l[7:]
        elif l.startswith("author-time "):
            d["date"] = datetime.fromtimestamp(int(l[12:]), timezone.utc).date().isoformat()
        elif l.startswith("summary "):
            d["summary"] = l[8:]
    return d


def _recent(repo: Path, rel: str, n: int = 5) -> list[dict]:
    out = _git(repo, "log", f"-n{n}", "--format=%h%x09%an%x09%ad%x09%s", "--date=short", "--", rel)
    rows = []
    for l in (out or "").splitlines():
        h, a, d, s = (l.split("\t") + ["", "", "", ""])[:4]
        rows.append({"commit": h, "author": a, "date": d, "summary": s})
    return rows


def locate(repo: str | Path, signal: Signal) -> list[Located]:
    """Return in-repo frames, deepest first."""
    repo = Path(repo).resolve()
    found: list[Located] = []
    for fr in reversed(signal.frames):
        path = _resolve(repo, fr.file)
        if not path:
            continue
        rel = path.relative_to(repo).as_posix()
        snip = _snippet(path, fr.line)
        text = next((t for n, t in snip if n == fr.line), "")
        found.append(Located(fr, rel, text, snip, _blame(repo, rel, fr.line), _recent(repo, rel)))
    return found
