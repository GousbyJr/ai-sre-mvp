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
pip install -e '.[llm]'                    # optional: LLM analysis
export ANTHROPIC_API_KEY=...               # without it, rule-based fallback is used
sre-agent analyze --log error.log --repo /path/to/service --service checkout
sre-agent resolve 1 --type permanent --root-cause "..." --fix "..."
sre-agent history
```

## Next steps
1. Ingest from Datadog/Loki/CloudWatch/Sentry/PagerDuty webhooks instead of log files
2. Embeddings (pgvector) for history; add deploy/metric correlation (what shipped just before?)
3. Open a PR with the patch (human approval required); never auto-merge
4. Eval harness: replay past incidents, score fix-location accuracy
5. Guardrails: read-only repo access, secret scrubbing before sending logs/code to any LLM
