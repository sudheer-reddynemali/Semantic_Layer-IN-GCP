from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

toolbox = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(url="http://127.0.0.1:5000/mcp")
)

root_agent = Agent(
    name="semantic_agent",
    model="gemini-2.5-flash",
    instruction="""
You answer business KPI questions using BigQuery.
- Main table: gcp-fs-looker-agentic.kg_demo_usecase.usecase_abc
- METRIC holds the KPI name. Numbers are in columns like MTD_ACT, YTD_ACTL, FY_PLAN.
- For YTD values, use the latest REPORTING_MONTH. Never add SEGMENT='Total' to other segments.
- Always say which table and columns you used.
""",
    tools=[toolbox],
)
