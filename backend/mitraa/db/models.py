"""SQLAlchemy models: conversations, messages, audit log, approvals, undo log."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | tool
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # assistant only
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # tool only
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # tool only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCall(Base):
    """The audit log: one row per tool call the model makes."""

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    llm_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool: Mapped[str] = mapped_column(String(100))
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    risk: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # success | error | denied | pending | blocked
    result_summary: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PendingApproval(Base):
    __tablename__ = "pending_approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id"))
    llm_call_id: Mapped[str] = mapped_column(String(100))
    tool: Mapped[str] = mapped_column(String(100))
    args_json: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(String(16))
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    # Tool calls from the same assistant turn that still need processing.
    remaining_calls_json: Mapped[str] = mapped_column(Text, default="[]")
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | denied | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FileAction(Base):
    """Undo log. Rows sharing a group_id came from one tool call and are undone together."""

    __tablename__ = "file_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32))  # move | copy | rename | create_folder | delete
    src: Mapped[str] = mapped_column(Text, default="")
    dst: Mapped[str] = mapped_column(Text, default="")
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("type", "key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(16), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[str] = mapped_column(String(10))
    deadline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekends_working: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    estimated_hours: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="todo")
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    hours_per_day: Mapped[float] = mapped_column(Float, default=6)
    unavailable_dates_json: Mapped[str] = mapped_column(Text, default="[]")


class Responsibility(Base):
    __tablename__ = "responsibilities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="captured", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    completion_note: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResponsibilityEvent(Base):
    __tablename__ = "responsibility_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    responsibility_id: Mapped[str] = mapped_column(ForeignKey("responsibilities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    responsibility_id: Mapped[str] = mapped_column(ForeignKey("responsibilities.id"), index=True)
    message: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReminderPreferences(Base):
    __tablename__ = "reminder_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    quiet_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="08:00")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PreparedDraft(Base):
    __tablename__ = 'prepared_drafts'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    responsibility_id: Mapped[str] = mapped_column(ForeignKey('responsibilities.id'), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DraftRevision(Base):
    __tablename__ = 'draft_revisions'
    __table_args__ = (UniqueConstraint('draft_id','version'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey('prepared_drafts.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(32), default='pending')
    review_note: Mapped[str] = mapped_column(Text, default='')
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelUsage(Base):
    __tablename__ = 'model_usage'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True,index=True)
    provider: Mapped[str] = mapped_column(String(250))
    model: Mapped[str] = mapped_column(String(250))
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int | None] = mapped_column(Integer,nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer,nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow,index=True)


class CodingJob(Base):
    __tablename__ = 'coding_jobs'
    id: Mapped[str] = mapped_column(String(32),primary_key=True,default=new_id)
    responsibility_id: Mapped[str] = mapped_column(ForeignKey('responsibilities.id'),index=True)
    status: Mapped[str] = mapped_column(String(32),default='prepared',index=True)
    objective: Mapped[str] = mapped_column(Text)
    criteria: Mapped[str] = mapped_column(Text)
    contract_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text,default='{}')
    version: Mapped[int] = mapped_column(Integer,default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)


class CodingCheck(Base):
    __tablename__ = 'coding_checks'
    id: Mapped[str] = mapped_column(String(32),primary_key=True,default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey('coding_jobs.id'),index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64))
    context_hash: Mapped[str] = mapped_column(String(64))
    recipe_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32),default='running')
    report_json: Mapped[str] = mapped_column(Text,default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
