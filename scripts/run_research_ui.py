#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "research_ui.py"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the read-only FinAgent Streamlit research UI."
    )
    parser.add_argument("--report", type=Path, help="A2/A2.5 acceptance report JSON")
    parser.add_argument(
        "--feature-store",
        type=Path,
        help="generated_features.sqlite used for read-only source inspection",
    )
    parser.add_argument("--trace", type=Path, help="Agent observability JSONL trace")
    parser.add_argument(
        "--phoenix-url",
        default=os.environ.get("FINAGENT_PHOENIX_URL", "http://localhost:6006"),
    )
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="localhost")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--enable-usage-stats",
        action="store_true",
        help="opt in to Streamlit usage telemetry; disabled by default",
    )
    parser.add_argument(
        "--show-email-prompt",
        action="store_true",
        help="show Streamlit's first-run email prompt; disabled by default",
    )
    parser.add_argument("--print-command", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not APP.is_file():
        raise FileNotFoundError(APP)
    if importlib.util.find_spec("streamlit") is None:
        raise RuntimeError(
            "Streamlit is not installed. Run: "
            "python -m pip install -e '.[visualization]'"
        )
    if args.report is not None:
        os.environ["FINAGENT_RESEARCH_REPORT"] = str(args.report.expanduser())
    if args.feature_store is not None:
        os.environ["FINAGENT_FEATURE_STORE"] = str(args.feature_store.expanduser())
    if args.trace is not None:
        os.environ["FINAGENT_AGENT_TRACE_JSONL"] = str(args.trace.expanduser())
    os.environ["FINAGENT_PHOENIX_URL"] = str(args.phoenix_url)

    usage_stats = "true" if args.enable_usage_stats else "false"
    show_email_prompt = "true" if args.show_email_prompt else "false"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.address",
        str(args.address),
        "--server.port",
        str(args.port),
        "--server.headless",
        "true" if args.headless else "false",
        "--server.showEmailPrompt",
        show_email_prompt,
        "--browser.gatherUsageStats",
        usage_stats,
    ]
    if args.print_command:
        print(" ".join(command))
        return 0

    environment = os.environ.copy()
    environment["STREAMLIT_SERVER_SHOW_EMAIL_PROMPT"] = show_email_prompt
    environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = usage_stats
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
