from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plotly.graph_objects import Figure

from .research_report import ResearchReportView
from .trace_reader import AgentTraceView


def _go():
    try:
        import plotly.graph_objects as go
    except ImportError as exc:
        raise ImportError(
            "research figures require the optional visualization extra: "
            "python -m pip install -e '.[visualization]'"
        ) from exc
    return go


def development_validation_scatter(report: ResearchReportView) -> Figure:
    go = _go()
    rows = report.candidate_rows()
    figure = go.Figure()
    for selected in (False, True):
        values = [row for row in rows if bool(row["selected"]) is selected]
        if not values:
            continue
        figure.add_trace(
            go.Scatter(
                x=[row["development_rank_icir"] for row in values],
                y=[row["validation_rank_icir"] for row in values],
                mode="markers+text",
                text=[row["feature_id"] for row in values],
                textposition="top center",
                name="selected" if selected else "candidate",
                marker={
                    "size": 12 if selected else 9,
                    "symbol": "diamond" if selected else "circle",
                },
                customdata=[row["feature_digest"] for row in values],
                hovertemplate=(
                    "%{text}<br>Dev RankICIR=%{x:.4f}<br>Val RankICIR=%{y:.4f}"
                    "<br>%{customdata}<extra></extra>"
                ),
            )
        )
    coordinates = [
        float(row[metric])
        for row in rows
        for metric in ("development_rank_icir", "validation_rank_icir")
    ]
    bound = max((abs(value) for value in coordinates), default=0.1)
    bound = max(bound * 1.15, 0.05)
    figure.add_shape(
        type="line",
        x0=-bound,
        x1=bound,
        y0=-bound,
        y1=bound,
        line={"dash": "dot"},
    )
    figure.add_hline(y=0.0, line={"dash": "dash"})
    figure.add_vline(x=0.0, line={"dash": "dash"})
    figure.update_layout(
        title="Development vs validation RankICIR",
        xaxis_title="Development RankICIR",
        yaxis_title="Validation RankICIR",
        xaxis={"range": [-bound, bound]},
        yaxis={"range": [-bound, bound]},
        height=520,
    )
    return figure


def rolling_rank_ic(report: ResearchReportView, digest: str) -> Figure:
    go = _go()
    figure = go.Figure()
    for split in ("development", "validation"):
        rows = report.rolling_rows(digest, split)
        if rows:
            figure.add_trace(
                go.Scatter(
                    x=[row["end"] for row in rows],
                    y=[row["rank_ic"] for row in rows],
                    mode="lines+markers",
                    name=split,
                    hovertemplate=(
                        "%{x}<br>Rolling RankIC=%{y:.4f}<extra>" + split + "</extra>"
                    ),
                )
            )
    figure.add_hline(y=0.0, line={"dash": "dash"})
    figure.update_layout(
        title="Rolling RankIC",
        xaxis_title="Window end",
        yaxis_title="RankIC",
        height=460,
    )
    return figure


def subperiod_rank_ic(report: ResearchReportView, digest: str) -> Figure:
    go = _go()
    figure = go.Figure()
    for split in ("development", "validation"):
        rows = report.subperiod_rows(digest, split)
        if rows:
            figure.add_trace(
                go.Bar(
                    x=[row["period"] for row in rows],
                    y=[row["rank_ic"] for row in rows],
                    name=split,
                    customdata=[row["rank_icir"] for row in rows],
                    hovertemplate=(
                        "%{x}<br>RankIC=%{y:.4f}<br>RankICIR=%{customdata:.4f}"
                        "<extra></extra>"
                    ),
                )
            )
    figure.add_hline(y=0.0, line={"dash": "dash"})
    figure.update_layout(
        title="Subperiod RankIC",
        xaxis_title="Subperiod",
        yaxis_title="RankIC",
        barmode="group",
        height=440,
    )
    return figure


def quantile_returns(report: ResearchReportView, digest: str) -> Figure:
    go = _go()
    rows = report.quantile_rows(digest)
    figure = go.Figure()
    for split in ("development", "validation"):
        values = [row for row in rows if row["split"] == split]
        if values:
            figure.add_trace(
                go.Bar(
                    x=[row["quantile"] for row in values],
                    y=[row["mean_return"] for row in values],
                    name=split,
                    hovertemplate="%{x}<br>Mean forward return=%{y:.6f}<extra></extra>",
                )
            )
    figure.add_hline(y=0.0, line={"dash": "dash"})
    figure.update_layout(
        title="Quantile mean forward returns",
        xaxis_title="Factor quantile",
        yaxis_title="Mean forward return",
        barmode="group",
        height=440,
    )
    return figure


def correlation_heatmap(report: ResearchReportView, split: str) -> Figure:
    go = _go()
    labels, matrix = report.correlation_matrix(split)
    figure = go.Figure(
        data=go.Heatmap(
            z=matrix,
            x=labels,
            y=labels,
            zmin=-1.0,
            zmax=1.0,
            text=[[f"{value:.2f}" for value in row] for row in matrix],
            texttemplate="%{text}",
            hovertemplate=(
                "%{y} × %{x}<br>Rank correlation=%{z:.4f}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        title=f"{split.title()} factor-value correlation",
        height=max(480, 38 * len(labels)),
        xaxis={"side": "top"},
    )
    return figure


def ensemble_weights(report: ResearchReportView) -> Figure:
    go = _go()
    components = report.frozen_ensemble.get("components", ())
    values = [value for value in components if isinstance(value, dict)]
    figure = go.Figure(
        data=go.Bar(
            x=[
                str(value.get("feature_id", value.get("feature_digest", "")))
                for value in values
            ],
            y=[float(value.get("weight", 0.0)) for value in values],
            customdata=[int(value.get("direction", 0)) for value in values],
            hovertemplate=(
                "%{x}<br>Weight=%{y:.4f}<br>Frozen direction=%{customdata}"
                "<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        title="Frozen development ensemble weights",
        xaxis_title="Factor",
        yaxis_title="Weight",
        height=420,
    )
    return figure


def universe_eligibility(report: ResearchReportView) -> Figure:
    go = _go()
    rows = report.universe_rows()
    figure = go.Figure()
    for metric, label in (
        ("average_eligible_assets", "average"),
        ("minimum_eligible_assets", "minimum"),
        ("maximum_eligible_assets", "maximum"),
        ("first_session_eligible_assets", "first session"),
    ):
        figure.add_trace(
            go.Bar(
                x=[row["split"] for row in rows],
                y=[row[metric] for row in rows],
                name=label,
            )
        )
    figure.update_layout(
        title="PIT eligible assets by split",
        xaxis_title="Split",
        yaxis_title="Assets",
        barmode="group",
        height=420,
    )
    return figure


def llm_usage(trace: AgentTraceView) -> Figure:
    go = _go()
    rows = trace.llm_rows()
    labels = [f"call {index + 1}" for index in range(len(rows))]
    figure = go.Figure()
    for key, label in (
        ("prompt_tokens", "prompt"),
        ("reasoning_tokens", "reasoning"),
        ("completion_tokens", "completion"),
    ):
        figure.add_trace(
            go.Bar(
                x=labels,
                y=[row[key] for row in rows],
                name=label,
            )
        )
    figure.update_layout(
        title="LLM token usage",
        xaxis_title="LLM span",
        yaxis_title="Tokens",
        barmode="group",
        height=420,
    )
    return figure
