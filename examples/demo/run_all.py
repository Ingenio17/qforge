"""
Run the demo suite and write demo_plots/SUMMARY.md.

    python examples/demo/run_all.py            all ten (about 12 minutes)
    python examples/demo/run_all.py 2 3 10     just these (quickest for a live show)

Each demo is independent, writes to demo_plots/<name>/ and exits non-zero if any of its
checks against an independent calculation fails.
"""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUTPUT = HERE.parents[1] / "demo_plots"
PARALLEL = 3


def run(script: Path):
    started = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, str(script)], cwd=HERE, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    print(done.stdout, end="", flush=True)
    if done.returncode:
        print(done.stderr[-2000:], flush=True)
    return script.stem, done.returncode, time.time() - started


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        import qutip  # noqa: F401
        import scqubits  # noqa: F401
    except ImportError as missing:
        print(f"{missing}. Run this with the environment QubitWeave is installed in (qforge_env).")
        return 2
    wanted = {int(a) for a in sys.argv[1:]}
    scripts = [s for s in sorted(HERE.glob("demo_*.py")) if not wanted or int(s.stem.split("_")[1]) in wanted]
    with ThreadPoolExecutor(PARALLEL) as pool:
        results = list(pool.map(run, scripts))

    lines = ["# Demo checks", "", "Every check compares a demo with an independent calculation.", "",
             "| Demo | Checks passed | Run time |", "|---|---|---|"]
    for stem, code, seconds in results:
        name = stem.removeprefix("demo_")
        checks = pd.read_csv(OUTPUT / name / "checks.csv")
        passed = int((checks["status"] == "PASS").sum())
        lines.append(f"| {name} | {passed} / {len(checks)} | {seconds:.0f} s |")
    if not wanted:
        (OUTPUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return int(any(code for _, code, _ in results))


if __name__ == "__main__":
    sys.exit(main())
