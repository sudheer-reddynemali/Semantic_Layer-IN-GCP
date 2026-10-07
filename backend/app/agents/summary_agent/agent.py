from pathlib import Path

from ..common import build_agent

summary_agent = build_agent(
    Path(__file__).parent,
    name="summary_agent",
    description="Summarises KPI performance from BigQuery.",
)
