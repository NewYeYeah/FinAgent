from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

research = ROOT / "src/finagent/visualization/research_workspace.py"
text = research.read_text(encoding="utf-8")
text = text.replace("from typing import Any\n", "from typing import Any, cast\n")
text = text.replace(
    '        matches = [\n            item\n            for item in payload["items"]\n',
    '        experiment_items = cast(list[dict[str, Any]], payload["items"])\n        matches = [\n            item\n            for item in experiment_items\n',
)
text = text.replace(
    '        for cycle in self.cycles()["items"]:\n',
    '        cycle_items = cast(list[dict[str, Any]], self.cycles()["items"])\n        for cycle in cycle_items:\n',
)
text = text.replace(
    '        return {\n            "schema_version": "finagent.workspace.research-workspace-status.v1",\n            "agent_audit_configured": self.agent_configured,\n            "accepted_cycle_count": sum(item.get("accepted") is True for item in cycles["items"]),\n',
    '        cycle_items = cast(list[dict[str, Any]], cycles["items"])\n        return {\n            "schema_version": "finagent.workspace.research-workspace-status.v1",\n            "agent_audit_configured": self.agent_configured,\n            "accepted_cycle_count": sum(item.get("accepted") is True for item in cycle_items),\n',
)
research.write_text(text, encoding="utf-8")

market = ROOT / "src/finagent/visualization/market_factor_intelligence.py"
text = market.read_text(encoding="utf-8")
text = text.replace("from typing import Any\n", "from typing import Any, cast\n")
text = text.replace(
    '            for item in self.research_workspace.experiments()["items"]:\n',
    '            experiment_items = cast(\n                list[dict[str, Any]], self.research_workspace.experiments()["items"]\n            )\n            for item in experiment_items:\n',
)
text = text.replace(
    '            graph = self.research_workspace.graph()\n            for node in graph["nodes"]:\n',
    '            graph = self.research_workspace.graph()\n            graph_nodes = cast(list[dict[str, Any]], graph["nodes"])\n            for node in graph_nodes:\n',
)
text = text.replace(
    '        item = next((value for value in payload["items"] if value["model_id"] == model_id), None)\n',
    '        market_items = cast(list[dict[str, Any]], payload["items"])\n        item = next((value for value in market_items if value["model_id"] == model_id), None)\n',
)
text = text.replace(
    '        return {\n            "schema_version": "finagent.workspace.market-factor-status.v1",\n            "market_model_count": len(markets["items"]),\n            "factor_count": len(factors["items"]),\n',
    '        market_items = cast(list[dict[str, Any]], markets["items"])\n        factor_items = cast(list[dict[str, Any]], factors["items"])\n        return {\n            "schema_version": "finagent.workspace.market-factor-status.v1",\n            "market_model_count": len(market_items),\n            "factor_count": len(factor_items),\n',
)
market.write_text(text, encoding="utf-8")
