"""Turn raw log text into a structured Signal. Supports Python tracebacks and Java stack traces."""
from __future__ import annotations

import re
from typing import Optional

from .models import Frame, Signal

PY_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')
PY_EXC = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::\s*(?P<msg>.*))?$")
JAVA_FRAME = re.compile(r"^\s*at (?P<func>[\w.$<>]+)\((?P<file>[\w$]+\.\w+):(?P<line>\d+)\)")
JAVA_EXC = re.compile(
    r"(?:^|\s)(?:Caused by: )?(?P<type>(?:[a-z_]\w*\.)+[A-Z]\w*(?:Exception|Error))(?::\s*(?P<msg>.*))?$"
)


def parse_log(text: str, service: Optional[str] = None) -> Optional[Signal]:
    lines = text.splitlines()
    sig = _parse_python(lines) or _parse_java(lines)
    if sig:
        sig.service = service
        sig.raw = "\n".join(lines[-60:])
    return sig


def _parse_python(lines: list[str]) -> Optional[Signal]:
    starts = [i for i, l in enumerate(lines) if "Traceback (most recent call last)" in l]
    if not starts:
        return None
    frames: list[Frame] = []
    exc = None
    i = starts[-1] + 1
    while i < len(lines):
        l = lines[i]
        m = PY_FRAME.search(l)
        if m:
            frames.append(Frame(m["file"], int(m["line"]), m["func"].strip()))
        elif l.startswith((" ", "\t")) or not l.strip():
            pass  # source line, caret marker, or blank
        else:
            m = PY_EXC.match(l.strip())
            if m:
                exc = (m["type"], (m["msg"] or "").strip())
            break
        i += 1
    if not exc:
        return None
    return Signal(exc[0], exc[1], frames)


def _parse_java(lines: list[str]) -> Optional[Signal]:
    best = None
    for i, l in enumerate(lines):
        m = JAVA_EXC.search(l.rstrip())
        if not m:
            continue
        frames = []
        for nxt in lines[i + 1:]:
            fm = JAVA_FRAME.match(nxt)
            if fm:
                frames.append(Frame(fm["file"], int(fm["line"]), fm["func"]))
            elif nxt.strip().startswith("..."):
                continue
            else:
                break
        if frames:
            best = Signal(m["type"], (m["msg"] or "").strip(), list(reversed(frames)))
    return best
