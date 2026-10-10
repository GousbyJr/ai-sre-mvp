from __future__ import annotations

import argparse
import json
import os
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .agent import analyze
from .history import History

MAX_REQUEST_BYTES = 1_048_576

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI SRE Incident Analyzer</title>
  <style>
    :root { color-scheme: dark; font: 16px/1.5 system-ui, sans-serif; background: #10151d; color: #e5eaf2; }
    body { max-width: 960px; margin: 40px auto; padding: 0 20px; }
    h1 { margin-bottom: 4px; } p { color: #aab6c6; margin-top: 0; }
    label { display: block; margin: 18px 0 6px; font-weight: 600; }
    input, textarea, button { box-sizing: border-box; width: 100%; border: 1px solid #364253; border-radius: 6px; padding: 10px; background: #171f2b; color: inherit; font: inherit; }
    textarea { min-height: 220px; resize: vertical; font-family: ui-monospace, monospace; }
    button { width: auto; margin-top: 18px; padding: 10px 18px; background: #2764d8; border: 0; cursor: pointer; font-weight: 700; }
    button:disabled { opacity: .6; cursor: wait; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 18px; border-radius: 6px; background: #171f2b; }
    .error { color: #ff9b9b; }
    .key-settings { margin: 24px 0; padding: 16px; border: 1px solid #364253; border-radius: 6px; }
    .key-settings p, .key-settings small { color: #aab6c6; }
  </style>
</head>
<body>
  <h1>AI SRE Incident Analyzer</h1>
  <p>Paste an error log to locate the likely fix and check incident history.</p>
  <section class="key-settings">
    <h2>LLM analysis</h2>
    <label for="anthropic-key">Anthropic API key</label>
    <input id="anthropic-key" type="password" autocomplete="off" spellcheck="false">
    <button id="set-key" type="button">Set key for this server</button>
    <p id="key-status" aria-live="polite">API key __KEY_STATUS__. The key is sent only to this localhost server and kept in its process memory; it is not saved to browser storage or disk.</p>
  </section>
  <form id="incident-form">
    <label for="repo">Service repository path</label>
    <input id="repo" name="repo" required value="__DEFAULT_REPO__">
    <label for="service">Service name (optional)</label>
    <input id="service" name="service" placeholder="checkout">
    <label for="log">Error log or stack trace</label>
    <textarea id="log" name="log" required placeholder="Paste a GraphQL error response/log, Python traceback, or Java stack trace"></textarea>
    <button id="submit" type="submit">Analyze incident</button>
  </form>
  <pre id="result" aria-live="polite">Analysis results will appear here.</pre>
  <script>
    const form = document.querySelector("#incident-form");
    const result = document.querySelector("#result");
    const submit = document.querySelector("#submit");
    const keyInput = document.querySelector("#anthropic-key");
    const keyStatus = document.querySelector("#key-status");
    document.querySelector("#set-key").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      if (!keyInput.value) {
        keyStatus.textContent = "Enter an API key first.";
        return;
      }
      button.disabled = true;
      keyStatus.textContent = "Setting API key…";
      try {
        const response = await fetch("/settings/key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: keyInput.value })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not set the API key.");
        keyInput.value = "";
        keyStatus.textContent = data.message;
      } catch (error) {
        keyStatus.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      result.className = "";
      result.textContent = "Analyzing incident…";
      try {
        const response = await fetch("/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(Object.fromEntries(new FormData(form)))
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Analysis failed.");
        result.textContent = data.rendered;
      } catch (error) {
        result.className = "error";
        result.textContent = error.message;
      } finally {
        submit.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def make_handler(default_repo: Path, db_path: str):
    class WebHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if urlsplit(self.path).path != "/":
                self.send_error(404)
                return
            key_status = "configured" if os.environ.get("ANTHROPIC_API_KEY") else "not configured"
            body = PAGE.replace(
                "__DEFAULT_REPO__", str(default_repo).replace("&", "&amp;").replace('"', "&quot;")
            ).replace("__KEY_STATUS__", key_status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/settings/key":
                self._set_api_key()
                return
            if path != "/analyze":
                self._send_json(404, {"error": "Not found."})
                return
            try:
                payload = self._read_json_body()
                if not isinstance(payload, dict):
                    raise ValueError("The request body must be a JSON object.")
                log_text = payload.get("log")
                repo_value = payload.get("repo", str(default_repo))
                service = payload.get("service") or None
                if not isinstance(log_text, str) or not log_text.strip():
                    raise ValueError("Enter an error log or stack trace.")
                if not isinstance(repo_value, str) or not isinstance(service, (str, type(None))):
                    raise ValueError("Repository and service values must be strings.")
                repo = Path(repo_value).expanduser().resolve()
                if not repo.is_dir():
                    raise ValueError(f"Repository directory does not exist: {repo}")
                history = History(db_path)
                try:
                    report = analyze(log_text, repo, history, service)
                finally:
                    history.db.close()
                self._send_json(200, {"report": report.to_dict(), "rendered": report.render()})
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "Request body must be valid UTF-8 JSON."})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})

        def _read_json_body(self) -> object:
            if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise ValueError("Content-Type must be application/json.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("A valid Content-Length is required.") from exc
            if length < 1 or length > MAX_REQUEST_BYTES:
                raise ValueError("Request must contain a JSON body smaller than 1 MiB.")
            return json.loads(self.rfile.read(length))

        def _set_api_key(self) -> None:
            try:
                payload = self._read_json_body()
                if not isinstance(payload, dict):
                    raise ValueError("The request body must be a JSON object.")
                key = payload.get("key")
                if not isinstance(key, str) or not key.strip():
                    raise ValueError("Enter an Anthropic API key.")
                os.environ["ANTHROPIC_API_KEY"] = key.strip()
                self._send_json(200, {
                    "configured": True,
                    "message": "API key set for this server process. LLM analysis is enabled.",
                })
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "Request body must be valid UTF-8 JSON."})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})

        def log_message(self, format: str, *args) -> None:
            print(f"{self.address_string()} - {format % args}")

    return WebHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AI SRE local web UI.")
    parser.add_argument("--repo", default=str(Path.cwd()), help="default service repository path")
    parser.add_argument("--db", default=os.getenv("SRE_DB", "sre_history.db"), help="incident history database path")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    default_repo = Path(args.repo).expanduser().resolve()
    if not default_repo.is_dir():
        parser.error(f"repository directory does not exist: {default_repo}")
    if not 0 < args.port < 65536:
        parser.error("--port must be between 1 and 65535")

    server = HTTPServer(("127.0.0.1", args.port), partial(make_handler(default_repo, args.db)))
    print(f"AI SRE UI available at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping AI SRE UI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
