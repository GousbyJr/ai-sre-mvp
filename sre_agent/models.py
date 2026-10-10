from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Frame:
    file: str
    line: int
    func: str


@dataclass
class Signal:
    """A parsed failure. frames are ordered outermost -> innermost."""
    exc_type: str
    message: str
    frames: list[Frame]
    raw: str = ""
    service: Optional[str] = None
    graphql_path: Optional[list[str | int]] = None
    graphql_code: Optional[str] = None


@dataclass
class Located:
    """A stack frame that maps to a file inside the repo, enriched with code + git context."""
    frame: Frame
    path: str                      # repo-relative path
    line_text: str
    snippet: list[tuple[int, str]]
    blame: Optional[dict] = None   # commit, author, date, summary of the failing line
    recent_commits: list[dict] = field(default_factory=list)
