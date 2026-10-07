import json
import os
import re
import uuid

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from .agents import summary_agent, visualization_agent  # noqa: E402

APP_NAME = "kpi_insights"
sessions = InMemorySessionService()
runners = {
    "summary": Runner(agent=summary_agent, app_name=APP_NAME, session_service=sessions),
    "visualize": Runner(agent=visualization_agent, app_name=APP_NAME, session_service=sessions),
}

app = FastAPI(title="KPI Insights API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class Query(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


async def run_agent(kind: str, question: str) -> str:
    session_id = uuid.uuid4().hex
    await sessions.create_session(app_name=APP_NAME, user_id="web", session_id=session_id)
    message = types.Content(role="user", parts=[types.Part(text=question)])
    text = ""
    async for event in runners[kind].run_async(
        user_id="web", session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts)
    return text


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/summary")
async def summary(q: Query):
    try:
        return {"summary": await run_agent("summary", q.question)}
    except Exception as exc:
        raise HTTPException(502, f"Agent error: {exc}") from exc


@app.post("/api/visualize")
async def visualize(q: Query):
    try:
        text = await run_agent("visualize", q.question)
    except Exception as exc:
        raise HTTPException(502, f"Agent error: {exc}") from exc
    match = re.search(r"```json\s*(.*?)```", text, re.S)
    chart = None
    if match:
        try:
            chart = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {"message": re.sub(r"```json.*?```", "", text, flags=re.S).strip(), "chart": chart}
