# AI SRE MVP

Doesn't just say *what's* broken. It tells you **exactly where the fix belongs** (file:line:function, with
git blame) and recommends a **permanent fix** informed by your **incident history**.

## Pipeline
`log -> parser -> locator (repo + git blame/log) -> history (SQLite recall) -> diagnosis -> report`

| Module | Job |
|---|---|
| `parser.py` | Python tracebacks + Java stack traces -> structured `Signal` |
| `locator.py` | Maps frames to repo files, code snippet, `git blame`, recent commits |
| `history.py` | Stable error signature + similarity search over past incidents |
| `agent.py` | Builds context, computes history verdict (`new / similar / recurring / regression`), calls LLM |
| `rules.py` | Deterministic fallback when no LLM key is set |
| `report.py` | Human + JSON output |

## Why it recommends permanent fixes
- **recurring**: same signature, only workarounds recorded -> symptom is masked, fix root cause
- **regression**: previously fixed permanently -> look at what changed since
- **similar**: reuse fixes that worked on near matches

Close the loop after every incident: `sre-agent resolve <id> --type permanent --root-cause ... --fix ...`

## Run
```bash
python demo/run_demo.py                    # crash -> diagnosis -> workaround -> recurrence escalation
python -m sre_agent.web                    # local browser UI at http://127.0.0.1:8000
python -m sre_agent.web --repo /path/to/service --port 8080
pip install -e '.[llm]'                    # optional: LLM analysis
export ANTHROPIC_API_KEY=...               # without it, rule-based fallback is used
sre-agent analyze --log error.log --repo /path/to/service --service checkout
sre-agent resolve 1 --type permanent --root-cause "..." --fix "..."
sre-agent history
```

The web UI binds to localhost only. Paste a GraphQL JSON error response/log, Python traceback, or Java
stack trace, select the service repository path, and submit it to see the diagnosis and incident-history
result. GraphQL `errors` entries include their error message, path, extension code, and any Node.js,
Python, or Java stack trace exposed by the server.

For LLM analysis, install the optional `llm` extra and enter the Anthropic API key in the UI's
**LLM analysis** section. The key is sent to the localhost server, kept in that server process's
environment only, and cleared when the server stops; it is not saved to browser storage or disk.

## Sample inputs

`demo/samples/` contains 10 standalone service error-log lines, 10 Python tracebacks, and 10 Java stack
traces. The standalone lines are examples of log context; the current parser analyzes Python tracebacks
and Java stack traces, not arbitrary single-line log messages. Analyze a trace at a time:

```powershell
python -m sre_agent.cli analyze --log demo\samples\python_tracebacks\python_01.txt --repo . --no-llm --no-record
python -m sre_agent.cli analyze --log demo\samples\java_stack_traces\java_01.txt --repo . --no-llm --no-record
```

Change the sample number from `01` to `10` to try another trace. The samples use fictional services and
contain no real credentials or customer data.

## Next steps
1. Ingest from Datadog/Loki/CloudWatch/Sentry/PagerDuty webhooks instead of log files
2. Embeddings (pgvector) for history; add deploy/metric correlation (what shipped just before?)
3. Open a PR with the patch (human approval required); never auto-merge
4. Eval harness: replay past incidents, score fix-location accuracy
5. Guardrails: read-only repo access, secret scrubbing before sending logs/code to any LLM
