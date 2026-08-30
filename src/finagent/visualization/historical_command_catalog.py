from __future__ import annotations

from dataclasses import replace

from .workbench_control_catalog import CommandCatalog, CommandSpec, default_command_catalog

_AC1_BINDINGS: dict[str, tuple[str, str]] = {
    "research.run_development": (
        "Run bounded A2/A2.5 development research through the reviewed in-process "
        "application workflow. The production reserve is never read.",
        "finagent.application.control_services.DevelopmentResearchApplicationService",
    ),
    "research.run_a2p6": (
        "Run the preregistered A2.6 robust ResearchProgram through the reviewed "
        "in-process application workflow while keeping the production reserve untouched.",
        "finagent.application.control_services.RobustResearchApplicationService",
    ),
    "portfolio.run_a4": (
        "Run execution-aware internal A4 portfolio validation through the reviewed "
        "in-process application workflow. No promotion, PAPER or broker authority is granted.",
        "finagent.application.control_services.PortfolioValidationApplicationService",
    ),
}


def _ac1_spec(spec: CommandSpec) -> CommandSpec:
    replacement = _AC1_BINDINGS.get(spec.command_id)
    if replacement is None:
        return spec
    description, binding_ref = replacement
    return replace(
        spec,
        description=description,
        binding_kind="application_service",
        binding_ref=binding_ref,
        gateway_readiness="application_service_ready",
    )


def default_historical_command_catalog() -> CommandCatalog:
    """Return the frozen V3 vocabulary with A-C1 historical L1 bindings activated."""

    base = default_command_catalog()
    return CommandCatalog(tuple(_ac1_spec(spec) for spec in base.specs))
