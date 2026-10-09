from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import analyze
from .history import FIX_TYPES, History


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sre-agent", description="AI SRE: where to fix + permanent fix")
    p.add_argument("--db", default=os.getenv("SRE_DB", "sre_history.db"))
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="analyze an error log")
    a.add_argument("--log", default="-", help="log file, or - for stdin")
    a.add_argument("--repo", default=".", help="path to the service's git repo")
    a.add_argument("--service")
    a.add_argument("--json", action="store_true")
    a.add_argument("--no-record", action="store_true")
    a.add_argument("--no-llm", action="store_true")

    r = sub.add_parser("resolve", help="record how an incident was actually fixed (teaches the agent)")
    r.add_argument("id", type=int)
    r.add_argument("--root-cause", required=True)
    r.add_argument("--fix", required=True)
    r.add_argument("--type", required=True, choices=FIX_TYPES)

    sub.add_parser("history", help="list recent incidents")

    args = p.parse_args(argv)
    hist = History(args.db)

    if args.cmd == "analyze":
        text = sys.stdin.read() if args.log == "-" else open(args.log, errors="replace").read()
        try:
            rep = analyze(text, args.repo, hist, args.service, not args.no_record, not args.no_llm)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(rep.to_dict(), indent=2, default=str) if args.json else rep.render())
    elif args.cmd == "resolve":
        hist.resolve(args.id, args.root_cause, args.fix, args.type)
        print(f"incident #{args.id} marked {args.type}")
    else:
        for r_ in hist.recent():
            print(f"#{r_['id']} {r_['ts'][:10]} {r_['exc_type']} {r_['file']}:{r_['func']} fix={r_['fix_type'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
