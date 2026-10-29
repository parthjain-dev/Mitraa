"""FastAPI app. Run with: python -m mitraa.main (binds to 127.0.0.1 only)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from mitraa import __version__, audit
from mitraa.agent.llm import LLMClient, LLMError, NemotronClient
from mitraa.agent.orchestrator import AgentResponse, ApprovalError, ConversationNotFound, Orchestrator
from mitraa.config import Settings, get_settings
from mitraa.db.models import Conversation, Message, Memory, Project
from mitraa.db.session import get_session
from mitraa.memory import store
from mitraa.planning import service
from mitraa.planning.models import MemberSpec, Scenario, TaskSpec
from mitraa.tools.registry import ToolRegistry, build_default_registry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Mitraa", version=__version__)
from mitraa.responsibilities.api import router as responsibilities_router
app.include_router(responsibilities_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=10_000)


class ApproveRequest(BaseModel):
    approval_id: str
    approved: bool


@lru_cache
def get_registry() -> ToolRegistry:
    return build_default_registry()


@lru_cache
def _nemotron() -> NemotronClient:
    return NemotronClient(get_settings())


def get_llm() -> LLMClient:
    try:
        return _nemotron()
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_orchestrator(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: ToolRegistry = Depends(get_registry),
    llm: LLMClient = Depends(get_llm),
) -> Orchestrator:
    return Orchestrator(llm, session, settings, registry=registry)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get('/usage')
def token_usage(session: Session = Depends(get_session)):
    from mitraa.usage import summary
    return summary(session)


@app.post("/chat", response_model=AgentResponse)
def chat(request: ChatRequest, agent: Orchestrator = Depends(get_orchestrator)) -> AgentResponse:
    try:
        return agent.run(request.conversation_id, request.message)
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Conversation {exc} not found") from exc


@app.post("/chat/approve", response_model=AgentResponse)
def approve(request: ApproveRequest, agent: Orchestrator = Depends(get_orchestrator)) -> AgentResponse:
    try:
        return agent.resume(request.approval_id, request.approved)
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/conversations")
def list_conversations(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.scalars(select(Conversation).order_by(Conversation.created_at.desc()).limit(100))
    return [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id))
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tool_calls": json.loads(m.tool_calls_json) if m.tool_calls_json else None,
                "tool_call_id": m.tool_call_id,
                "name": m.name,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@app.get("/tools")
def list_tools(registry: ToolRegistry = Depends(get_registry)) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "risk": str(t.base_risk), "parameters": t.schema()["function"]["parameters"]}
        for t in registry.list()
    ]


@app.get("/audit")
def get_audit(
    limit: int = Query(50, ge=1, le=500),
    conversation_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return [audit.to_dict(row) for row in audit.recent(session, limit, conversation_id)]


class MemoryRequest(BaseModel):
    type: str
    key: str
    value: str


@app.get("/memory")
def get_memory(type: str | None = None, session: Session = Depends(get_session)) -> list[dict]:
    return [store.as_dict(m) for m in store.list_memories(session, type)]


@app.post("/memory")
def put_memory(request: MemoryRequest, session: Session = Depends(get_session)) -> dict:
    try:
        row = store.remember(session, request.type, request.key, request.value)
        session.commit()
        return store.as_dict(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/memory/{memory_id}")
def delete_memory(memory_id: str, session: Session = Depends(get_session)) -> dict:
    row = session.get(Memory, memory_id)
    if row is None:
        raise HTTPException(404, "Memory not found")
    session.delete(row)
    session.commit()
    return {"deleted": memory_id}


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    goal: str = ""
    deadline_days: int | None = Field(default=None, ge=1)
    team: list[MemberSpec] = Field(default_factory=lambda: [MemberSpec(name="You")])


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    goal: str | None = None
    deadline_days: int | None = Field(default=None, ge=1)
    weekends_working: bool | None = None


@app.get("/projects")
def get_projects(session: Session = Depends(get_session)) -> list[dict]:
    return [service.project_dict(p) for p in session.scalars(select(Project).order_by(Project.created_at.desc()))]


@app.post("/projects")
def post_project(request: ProjectRequest, session: Session = Depends(get_session)) -> dict:
    row = service.create_project(session, request.name, request.goal, request.deadline_days, request.team)
    session.commit()
    return service.project_dict(row)


@app.get("/projects/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        project, tasks, members = service.project_data(session, project_id)
        return {**service.project_dict(project), "tasks": [t.model_dump(mode="json") for t in tasks],
                "members": [m.model_dump(mode="json") for m in members]}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.patch("/projects/{project_id}")
def patch_project(project_id: str, changes: ProjectPatch, session: Session = Depends(get_session)) -> dict:
    try:
        project = service.project_or_error(session, project_id)
        for key, value in changes.model_dump(exclude_unset=True).items():
            if key in {"name", "goal", "weekends_working"} and value is None:
                raise ValueError(f"{key} cannot be null.")
            setattr(project, key, value)
        session.commit()
        return service.project_dict(project)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/projects/{project_id}")
def delete_project(project_id: str, confirmed: bool = False, session: Session = Depends(get_session)) -> dict:
    if not confirmed:
        raise HTTPException(409, "Project deletion requires confirmed=true.")
    try:
        service.delete_project(session, project_id)
        session.commit()
        return {"deleted": project_id}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/projects/{project_id}/schedule")
def get_schedule(project_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return service.schedule(session, project_id).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/projects/{project_id}/simulate")
def post_simulate(project_id: str, scenario: Scenario, session: Session = Depends(get_session)) -> dict:
    try:
        return service.scenario(session, project_id, scenario).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/tasks")
def get_tasks(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    try:
        _, tasks, _ = service.project_data(session, project_id)
        return [t.model_dump(mode="json") for t in tasks]
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/tasks")
def post_task(project_id: str, task: TaskSpec, session: Session = Depends(get_session)) -> dict:
    try:
        row = service.add_task(session, project_id, task)
        session.commit()
        return {"id": row.id, "project_id": row.project_id, **task.model_dump(mode="json")}
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc


@app.patch("/tasks/{task_id}")
def patch_task(task_id: str, changes: dict, session: Session = Depends(get_session)) -> dict:
    try:
        row = service.update_task(session, task_id, changes)
        session.commit()
        return {"id": row.id, "key": row.key, "title": row.title, "status": row.status,
                "estimated_hours": row.estimated_hours}
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        service.delete_task(session, task_id)
        session.commit()
        return {"deleted": task_id}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def run() -> None:
    import uvicorn

    uvicorn.run("mitraa.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
