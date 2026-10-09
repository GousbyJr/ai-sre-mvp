import textwrap
from pathlib import Path

from sre_agent.agent import analyze
from sre_agent.history import History, make_signature
from sre_agent.locator import locate
from sre_agent.parser import parse_log

PY = textwrap.dedent('''\
    Traceback (most recent call last):
      File "/srv/app/main.py", line 10, in handler
        run(x)
      File "/srv/app/svc/calc.py", line 3, in run
        return data["amount"]
    KeyError: 'amount'
''')

JAVA = textwrap.dedent('''\
    2026-10-08 ERROR java.lang.IllegalStateException: boom
        at com.acme.Outer.call(Outer.java:5)
    Caused by: java.lang.NullPointerException: x is null
        at com.acme.Inner.work(Inner.java:42)
        at com.acme.Outer.call(Outer.java:4)
        ... 3 more
''')


def make_repo(tmp: Path) -> Path:
    (tmp / "svc").mkdir()
    (tmp / "svc" / "calc.py").write_text("\n\ndef run(data):\n    return data['amount']\n")
    return tmp


def test_parse_python():
    s = parse_log(PY)
    assert s.exc_type == "KeyError" and s.message == "'amount'"
    assert s.frames[-1].func == "run" and s.frames[-1].line == 3


def test_parse_java_root_cause_innermost_last():
    s = parse_log(JAVA)
    assert s.exc_type.endswith("NullPointerException")
    assert s.frames[-1].file == "Inner.java"


def test_locate_resolves_suffix(tmp_path):
    repo = make_repo(tmp_path)
    loc = locate(repo, parse_log(PY))
    assert loc and loc[0].path == "svc/calc.py"


def test_signature_ignores_numbers():
    a = parse_log(PY.replace("'amount'", "'id 123'"))
    b = parse_log(PY.replace("'amount'", "'id 999'"))
    assert make_signature(a, []) == make_signature(b, [])


def test_recurrence_escalates_after_workaround(tmp_path):
    repo = make_repo(tmp_path)
    h = History(str(tmp_path / "h.db"))
    r1 = analyze(PY, repo, h, use_llm=False)
    assert r1.verdict["kind"] == "new"
    h.resolve(r1.incident_id, "bad payload", "restarted", "workaround")
    r2 = analyze(PY, repo, h, use_llm=False)
    assert r2.verdict["kind"] == "recurring"
    assert r2.result["fix_location"]["file"] == "svc/calc.py"


def test_regression_after_permanent_fix(tmp_path):
    repo = make_repo(tmp_path)
    h = History(str(tmp_path / "h.db"))
    r1 = analyze(PY, repo, h, use_llm=False)
    h.resolve(r1.incident_id, "no schema", "added pydantic model", "permanent")
    assert analyze(PY, repo, h, use_llm=False).verdict["kind"] == "regression"
