import os
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools.toolbox_toolset import ToolboxToolset

MODEL = os.getenv("MODEL", "gemini-2.5-flash")
TOOLBOX_URL = os.getenv("TOOLBOX_URL", "http://127.0.0.1:5000")
SHARED_DOMAIN = Path(__file__).parent / "kpi_domain.md"


def build_agent(folder: Path, name: str, description: str) -> Agent:
    """Compose instruction from the agent folder's prompt.md and skill.md plus shared KPI domain notes."""
    parts = [
        (folder / "prompt.md").read_text(encoding="utf-8"),
        SHARED_DOMAIN.read_text(encoding="utf-8"),
        (folder / "skill.md").read_text(encoding="utf-8"),
    ]
    return Agent(
        name=name,
        model=MODEL,
        description=description,
        instruction="\n\n".join(parts),
        tools=[ToolboxToolset(TOOLBOX_URL, toolset_name="kpi")],
    )
