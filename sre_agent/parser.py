"""Turn raw log text into a structured Signal. Supports Python tracebacks and Java stack traces."""
from __future__ import annotations

import json
import re
from typing import Optional

from .models import Frame, Signal

PY_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')
PY_EXC = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::\s*(?P<msg>.*))?$")
JAVA_FRAME = re.compile(r"^\s*at (?P<func>[\w.$<>]+)\((?P<file>[\w$]+\.\w+):(?P<line>\d+)\)")
JAVA_EXC = re.compile(
    r"(?:^|\s)(?:Caused by: )?(?P<type>(?:[a-z_]\w*\.)+[A-Z]\w*(?:Exception|Error))(?::\s*(?P<msg>.*))?$"
)
NODE_FRAME = re.compile(
    r"^\s*at\s+(?:(?P<func>.+?)\s+\()?(?P<file>(?:[A-Za-z]:)?[^()\s]+):(?P<line>\d+):\d+\)?$"
)


def parse_log(text: str, service: Optional[str] = None) -> Optional[Signal]:
    lines = text.splitlines()
    sig = _parse_graphql(text) or _parse_python(lines) or _parse_java(lines) or _parse_node(lines)
    if sig:
        sig.service = service
        sig.raw = "\n".join(lines[-60:])
    return sig


def _json_values(text: str) -> list[object]:
    decoder = json.JSONDecoder()
    values = []
    try:
        values.append(json.loads(text))
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            value, _ = decoder.raw_decode(line[start:])
        except json.JSONDecodeError:
            continue
        values.append(value)
    return values


def _graphql_error(value: object) -> Optional[dict]:
    if isinstance(value, dict):
        errors = value.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    return error
        for nested in value.values():
            found = _graphql_error(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _graphql_error(nested)
            if found:
                return found
    return None


def _parse_graphql(text: str) -> Optional[Signal]:
    error = next((found for value in _json_values(text) if (found := _graphql_error(value))), None)
    if error is None:
        match = re.search(r"(?:GraphQL\s+error|GraphQLError):\s*(.+)", text, re.IGNORECASE)
        if not match:
            return None
        trace = _parse_node(text.splitlines())
        return Signal("GraphQLError", match.group(1).strip(), trace.frames if trace else [])

    extensions = error.get("extensions")
    extensions = extensions if isinstance(extensions, dict) else {}
    exception = extensions.get("exception")
    exception = exception if isinstance(exception, dict) else {}
    stacktrace = exception.get("stacktrace") or extensions.get("stacktrace") or []
    if isinstance(stacktrace, str):
        stack_lines = stacktrace.splitlines()
    elif isinstance(stacktrace, list):
        stack_lines = [str(line) for line in stacktrace]
    else:
        stack_lines = []

    trace = _parse_python(stack_lines) or _parse_java(stack_lines) or _parse_node(stack_lines)
    name = exception.get("name") or exception.get("type")
    if not isinstance(name, str) or not name:
        name = trace.exc_type if trace and trace.exc_type not in ("Error", "GraphQLError") else "GraphQLError"
    path = error.get("path")
    if not isinstance(path, list) or not all(isinstance(part, (str, int)) for part in path):
        path = None
    code = extensions.get("code")
    return Signal(
        name,
        error["message"].strip(),
        trace.frames if trace else [],
        graphql_path=path,
        graphql_code=code if isinstance(code, str) else None,
    )


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


def _parse_node(lines: list[str]) -> Optional[Signal]:
    frames = []
    for line in lines:
        match = NODE_FRAME.match(line)
        if match:
            frames.append(Frame(match["file"], int(match["line"]), (match["func"] or "<anonymous>").strip()))
    if not frames:
        return None
    header = next((line.strip() for line in lines if re.match(r"^[\w.$]+Error:", line.strip())), "")
    type_name, _, message = header.partition(":")
    return Signal(type_name or "Error", message.strip(), list(reversed(frames)))
