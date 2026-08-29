from __future__ import annotations

from finagent.application import CommandIntent as ApplicationCommandIntent
from finagent.application import CommandResult as ApplicationCommandResult
from finagent.application import CommandRun as ApplicationCommandRun
from finagent.visualization import CommandIntent as VisualizationCommandIntent
from finagent.visualization import CommandResult as VisualizationCommandResult
from finagent.visualization import CommandRun as VisualizationCommandRun


def test_visualization_reexports_application_command_contracts() -> None:
    assert VisualizationCommandIntent is ApplicationCommandIntent
    assert VisualizationCommandRun is ApplicationCommandRun
    assert VisualizationCommandResult is ApplicationCommandResult
