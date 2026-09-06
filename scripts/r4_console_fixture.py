"""Build/serve an explicitly offline controller fixture through the real core.

This opt-in acceptance script is never used as a production provider fallback.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.application.research_controller import (
    ResearchSessionService,
    open_research_session,
    run_research_session,
)
from finagent.visualization.workbench_api import create_workspace_app
from finagent.visualization.workbench_control_api import create_control_app
from tests.r4_controller_fixture import (
    Clock,
    ScriptedProvider,
    admission_fixture,
    factor_steps,
    fixture_policy,
    selection_steps,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--control-port", type=int, default=8766)
    args = parser.parse_args()
    root = args.output.resolve()
    admission, inputs = admission_fixture(root / "inputs")
    factor_ids = [f.factor_id for f in inputs["factors"]]
    audit = SQLiteAgentAuditStore(root / "agent.sqlite")
    provider = ScriptedProvider(
        [*selection_steps(factor_ids)[:2], *factor_steps(admission, factor_ids)]
    )
    runtime = open_research_session(
        admission,
        root / "proposal",
        run_id="offline-proposal",
        objective="Inspect and test a newly proposed factor on historical development data",
        provider=provider,
        provider_id="scripted-offline",
        model_id="fixture",
        audit=audit,
        policy=fixture_policy(),
        clock=Clock(),
    )
    result = run_research_session(runtime)
    if result["terminal"] != "NO_CANDIDATE_RECOMMENDED":
        raise RuntimeError(f"offline fixture failed: {result['terminal']}")
    (root / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Offline fixture: {root}; {result['terminal']}", flush=True)
    if not args.serve:
        return
    import uvicorn

    service = ResearchSessionService(
        admission,
        root / "sessions",
        audit,
        lambda: ScriptedProvider(selection_steps(factor_ids)),
        provider_id="scripted-offline",
        model_id="fixture",
        policy=fixture_policy(),
    )
    control = create_control_app(
        config_paths=(),
        report_paths=(),
        store_path=root / "commands.sqlite",
        export_dir=root / "exports",
        research_service=service,
        cors_origins=(f"http://127.0.0.1:{args.port}",),
    )
    server = uvicorn.Server(
        uvicorn.Config(control, host="127.0.0.1", port=args.control_port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        print(
            f"Explicit scripted provider admitted for fixture only: http://127.0.0.1:{args.port}/agent?run=offline-proposal",
            flush=True,
        )
        app = create_workspace_app(
            report_paths=(),
            config_paths=(),
            agent_audit_path=audit.path,
            command_store_path=root / "commands.sqlite",
            frontend_dir=Path("workspace/dist"),
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        server.should_exit = True
        thread.join(5)


if __name__ == "__main__":
    main()
