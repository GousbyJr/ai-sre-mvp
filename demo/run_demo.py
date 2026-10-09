"""End-to-end demo: a real crash -> diagnosis -> on-call applies a workaround -> same crash recurs -> agent escalates."""
import shutil, subprocess, sys, tempfile, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sre_agent.agent import analyze  # noqa: E402
from sre_agent.history import History  # noqa: E402


def git(repo, *a):
    subprocess.run(["git", "-c", "user.name=dev", "-c", "user.email=dev@example.com", "-C", str(repo), *a],
                   check=True, capture_output=True)


def main():
    work = Path(tempfile.mkdtemp(prefix="sre-demo-"))
    repo = work / "repo"
    shutil.copytree(ROOT / "demo" / "app", repo / "app", ignore=shutil.ignore_patterns("__pycache__"))
    try:
        git(repo, "init", "-q"); git(repo, "add", "."); git(repo, "commit", "-q", "-m", "checkout: add coupon discounts")
    except (OSError, subprocess.CalledProcessError):
        print("(git unavailable: blame skipped)")
    sys.path.insert(0, str(repo))
    from app.checkout import checkout

    hist = History(str(work / "history.db"))

    def crash():
        try:
            checkout({"total": 100.0, "coupon_code": "EXPIRED5"})
        except Exception:
            return traceback.format_exc()

    print("##### INCIDENT 1 #####")
    r1 = analyze(crash(), repo, hist, service="checkout")
    print(r1.render())
    hist.resolve(r1.incident_id, "Expired coupon code returned None", "Removed coupon from the order by hand", "workaround")

    print("\n##### INCIDENT 2 (same bug, days later) #####")
    print(analyze(crash(), repo, hist, service="checkout").render())


if __name__ == "__main__":
    main()
