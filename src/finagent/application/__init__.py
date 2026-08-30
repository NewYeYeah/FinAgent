"""Typed application boundary for governed FinAgent commands."""

from .ashare_portfolio_workflow import (
    PortfolioValidationOptions,
    run_portfolio_validation,
)
from .ashare_research_workflows import (
    DevelopmentResearchOptions,
    HistoricalWorkflowResult,
    RobustResearchOptions,
    load_toml_section,
    run_development_factor_research,
    run_robust_research,
)
from .command_contracts import (
    CommandEvent,
    CommandIntent,
    CommandRecord,
    CommandResult,
    CommandRun,
)
from .command_store import SQLiteCommandStore
from .control_services import (
    APPLICATION_SERVICE_BINDINGS as HISTORICAL_APPLICATION_SERVICE_BINDINGS,
    ApplicationCommandExecution,
    ApplicationCommandInvocation,
    ApplicationServiceRegistry,
    ConfigValidationApplicationService,
    DevelopmentResearchApplicationService,
    LocalAshareCertificationApplicationService,
    PortfolioValidationApplicationService,
    ReviewBundleExportApplicationService,
    RobustResearchApplicationService,
    default_application_service_registry as historical_application_service_registry,
)

# V3 Evidence/Control compatibility boundary. The original generic catalog remains the
# frozen vocabulary record with only the three pre-A-C1 reviewed services. A-C1 uses
# HISTORICAL_APPLICATION_SERVICE_BINDINGS + historical_application_service_registry
# through the dedicated Historical Control Plane composition.
APPLICATION_SERVICE_BINDINGS: dict[str, str] = {
    command_id: HISTORICAL_APPLICATION_SERVICE_BINDINGS[command_id]
    for command_id in (
        "config.validate",
        "data.certify_local_ashare",
        "review.export_bundle",
    )
}


def default_application_service_registry(config_registry) -> ApplicationServiceRegistry:
    return ApplicationServiceRegistry(
        (
            ConfigValidationApplicationService(config_registry),
            LocalAshareCertificationApplicationService(),
            ReviewBundleExportApplicationService(),
        )
    )


__all__ = [
    "APPLICATION_SERVICE_BINDINGS",
    "HISTORICAL_APPLICATION_SERVICE_BINDINGS",
    "ApplicationCommandExecution",
    "ApplicationCommandInvocation",
    "ApplicationServiceRegistry",
    "CommandEvent",
    "CommandIntent",
    "CommandRecord",
    "CommandResult",
    "CommandRun",
    "ConfigValidationApplicationService",
    "DevelopmentResearchApplicationService",
    "DevelopmentResearchOptions",
    "HistoricalWorkflowResult",
    "LocalAshareCertificationApplicationService",
    "PortfolioValidationApplicationService",
    "PortfolioValidationOptions",
    "ReviewBundleExportApplicationService",
    "RobustResearchApplicationService",
    "RobustResearchOptions",
    "SQLiteCommandStore",
    "default_application_service_registry",
    "historical_application_service_registry",
    "load_toml_section",
    "run_development_factor_research",
    "run_portfolio_validation",
    "run_robust_research",
]
