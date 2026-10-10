import json
import os
import threading
from functools import partial
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sre_agent.web import make_handler


def test_web_ui_serves_and_analyzes_traceback(tmp_path: Path):
    (tmp_path / "calc.py").write_text("def run(data):\n    return data['amount']\n")
    server = HTTPServer(
        ("127.0.0.1", 0),
        partial(make_handler(tmp_path, str(tmp_path / "history.db"))),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base_url) as response:
            page = response.read().decode()
        assert "AI SRE Incident Analyzer" in page
        assert str(tmp_path) in page

        payload = {
            "repo": str(tmp_path),
            "service": "checkout",
            "log": (
                'Traceback (most recent call last):\n'
                '  File "/srv/calc.py", line 2, in run\n'
                "    return data['amount']\n"
                "KeyError: 'amount'\n"
            ),
        }
        request = Request(
            f"{base_url}/analyze",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            result = json.loads(response.read())
        assert result["report"]["error"]["type"] == "KeyError"
        assert "WHERE TO FIX" in result["rendered"]
        assert result["report"]["incident_id"] is not None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_web_ui_returns_clear_error_for_invalid_log(tmp_path: Path):
    server = HTTPServer(
        ("127.0.0.1", 0),
        partial(make_handler(tmp_path, str(tmp_path / "history.db"))),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = Request(
        f"http://127.0.0.1:{server.server_port}/analyze",
        data=json.dumps({"repo": str(tmp_path), "log": "not a traceback"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        try:
            urlopen(request)
            raise AssertionError("Expected HTTP 400 for an invalid traceback")
        except HTTPError as error:
            assert error.code == 400
            assert "No stack trace found" in json.loads(error.read())["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_web_ui_sets_api_key_only_for_server_process(tmp_path: Path, monkeypatch):
    server = HTTPServer(
        ("127.0.0.1", 0),
        partial(make_handler(tmp_path, str(tmp_path / "history.db"))),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    test_key = "test-anthropic-key-not-real"
    request = Request(
        f"{base_url}/settings/key",
        data=json.dumps({"key": test_key}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request) as response:
            result = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"
        assert result["configured"] is True
        assert "key" not in result
        assert test_key not in json.dumps(result)
        assert os.environ["ANTHROPIC_API_KEY"] == test_key
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
