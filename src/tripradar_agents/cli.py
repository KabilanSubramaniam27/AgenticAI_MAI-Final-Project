"""Start the local UI/API pair; MCP processes are scoped to requests and closed automatically."""

import argparse
import os
import signal
import subprocess
import sys
import time

from .config import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true", help="Explicit offline protocol demo")
    args = parser.parse_args()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    if args.fixture:
        env["TRIPRADAR_AGENT_MODE"] = "fixture"
        env["TRIPRADAR_AGENT_DATABASE"] = str(ROOT / "data/runtime/fixture/tripradar.sqlite3")
    env["LANGSMITH_TRACING"] = "false"
    env["LANGCHAIN_TRACING_V2"] = "false"
    processes = []

    def stop(*_):
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "tripradar_agents.api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--no-access-log",
                ],
                env=env,
                cwd=ROOT,
            )
        )
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(ROOT / "src/tripradar_agents/ui.py"),
                    "--server.address=127.0.0.1",
                    "--server.port=8501",
                    "--server.headless=true",
                    "--browser.gatherUsageStats=false",
                ],
                env=env,
                cwd=ROOT,
            )
        )
        print("TripRadar: http://127.0.0.1:8501  API: http://127.0.0.1:8000/docs", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
    finally:
        stop()


if __name__ == "__main__":
    main()
