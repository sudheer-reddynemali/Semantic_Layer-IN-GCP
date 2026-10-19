from fastapi import FastAPI
from pydantic import BaseModel
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from semantic_agent.agent import root_agent

APP_NAME = "semantic_agent"

app = FastAPI(title="Semantic Agent API")
session_service = InMemorySessionService()
runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)

class AskRequest(BaseModel):
    question:str
    user_id: str = "demo-user"
    session_id:str | None = None #pass it back to keep the conversation going





class AskResponse (BaseModel):
    answer:str
    session_id:str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    #Start a new conversation or continue an existing one 
    session = None
    if req.session_id:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=req.user_id, session_id=req.session_id
        )
    
    if session is None:
        session = await session_service.create_session(app_name=APP_NAME, user_id=req.user_id)

    message = types.Content(role = "user", parts = [types.Part(text = req.question)])

    answer = ""

    async for event in runner.run_async(
        user_id=req.user_id, session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            answer = "".join(p.text or "" for p in event.content.parts)

    
    return AskResponse(answer=answer, session_id = session.id)
    