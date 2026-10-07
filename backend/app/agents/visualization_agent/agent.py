from pathlib import Path

from ..common import build_agent

visualization_agent = build_agent(
    Path(__file__).parent,
    name="visualization_agent",
    description="Produces chart specs for KPI data from BigQuery.",
)
