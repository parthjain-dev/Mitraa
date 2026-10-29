"""The agent loop: chat -> LLM -> tool call -> validate -> permission -> execute -> audit -> repeat."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from mitraa import audit
from mitraa.usage import tracked
from mitraa.agent.llm import LLMClient, LLMError, ToolCallRequest
from mitraa.agent.prompts import build_system_prompt
from mitraa.memory.retrieval import top_k
from mitraa.config import Settings
from mitraa.db.models import Conversation, Message, PendingApproval, ToolCall, utcnow
from mitraa.security.permissions import evaluate
from mitraa.security.sandbox import Sandbox, SandboxViolation
from mitraa.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from mitraa.tools.registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)

MAX_TOOL_MESSAGE_CHARS = 12_000


class Step(BaseModel):
    id: str
    tool: str
    args: dict[str, Any] | str
    risk: str
    status: str
    summary: str


class ApprovalInfo(BaseModel):
    approval_id: str
    tool: str
    args: dict[str, Any]
    risk: str
    description: str
    reasons: list[str]


class AgentResponse(BaseModel):
    type: Literal["message", "approval_required"]
    conversation_id: str
    text: str
    pending_approval: ApprovalInfo | None = None
    steps: list[Step] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)


class ConversationNotFound(Exception):
    pass


class ApprovalError(Exception):
    pass


class _Stop(Exception):
    """Ends the run early with a final message to the user."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


@dataclass
class _Run:
    conversation_id: str
    steps_used: int = 0
    invalid_args: int = 0
    steps: list[Step] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        llm: LLMClient,
        session: Session,
        settings: Settings,
        registry: ToolRegistry | None = None,
        sandbox: Sandbox | None = None,
        on_step: Callable[[Step], None] | None = None,
    ) -> None:
        self.llm = llm
        self.session = session
        self.settings = settings
        self.registry = registry or build_default_registry()
        self.sandbox = sandbox or Sandbox(settings.allowed_roots)
        self.on_step = on_step

    # ------------------------------------------------------------ public API

    @tracked
    def run(self, conversation_id: str | None, user_message: str, *, save_user: bool = True) -> AgentResponse:
        conversation = self._conversation(conversation_id, user_message)
        self._expire_pending(conversation.id)
        if save_user:
            self._save(conversation.id, "user", content=user_message)
        self.session.commit()
        return self._loop(_Run(conversation.id))

    @tracked
    def resume(self, approval_id: str, approved: bool) -> AgentResponse:
        pending = self.session.get(PendingApproval, approval_id)
        if pending is None:
            raise ApprovalError(f"No approval with id {approval_id}.")
        if pending.status != "pending":
            raise ApprovalError(f"This approval was already {pending.status}.")
        tool = self.registry.get(pending.tool)
        row = self.session.get(ToolCall, pending.audit_id)
        if tool is None or row is None:
            raise ApprovalError("The pending action is no longer available.")

        state = _Run(pending.conversation_id, steps_used=pending.steps_used)
        pending.status = "approved" if approved else "denied"
        pending.resolved_at = utcnow()
        args = tool.args_model.model_validate_json(pending.args_json)

        if approved:
            result = self._execute(tool, args, row, state.conversation_id, approved=True)
        else:
            result = ToolResult.fail("User denied this action. Do not retry it; offer an alternative if useful.")
            audit.finish(row, "denied", "User denied the action.")
        self._complete(state, pending.llm_call_id, pending.tool, row, result)

        remaining = [ToolCallRequest.from_json(c) for c in json.loads(pending.remaining_calls_json)]
        try:
            paused = self._process_calls(state, remaining)
        except _Stop as stop:
            return self._finish(state, stop.text)
        return paused or self._loop(state)

    # ------------------------------------------------------------ loop

    def _loop(self, state: _Run) -> AgentResponse:
        max_steps = self.settings.mitraa_max_steps
        while state.steps_used < max_steps:
            messages = self._history(state.conversation_id)
            try:
                reply = self.llm.chat(messages, self.registry.schemas())
            except LLMError as exc:
                logger.warning("LLM call failed: %s", exc)
                return self._finish(state, f"Sorry, I couldn't reach the language model: {exc}", save=False)
            state.steps_used += 1

            if not reply.tool_calls:
                return self._finish(state, reply.content or "Done.")

            self._save(
                state.conversation_id,
                "assistant",
                content=reply.content or None,
                tool_calls_json=json.dumps([c.to_openai() for c in reply.tool_calls]),
            )
            self.session.commit()
            try:
                paused = self._process_calls(state, reply.tool_calls)
            except _Stop as stop:
                return self._finish(state, stop.text)
            if paused:
                return paused

        done = [f"{s.tool} ({s.status})" for s in state.steps]
        summary = f" Actions taken: {', '.join(done)}." if done else ""
        return self._finish(state, f"I stopped after {max_steps} steps without finishing.{summary} Tell me how to continue.")

    def _process_calls(self, state: _Run, calls: list[ToolCallRequest]) -> AgentResponse | None:
        for index, call in enumerate(calls):
            try:
                paused = self._handle_call(state, call, calls[index + 1 :])
            except _Stop:
                for rest in calls[index + 1 :]:
                    self._save_tool_result(state.conversation_id, rest.id, rest.name, ToolResult.fail("Skipped."))
                self.session.commit()
                raise
            if paused:
                return paused
        return None

    def _handle_call(self, state: _Run, call: ToolCallRequest, remaining: list[ToolCallRequest]) -> AgentResponse | None:
        tool = self.registry.get(call.name)
        if tool is None:
            self._invalid(state, call, f"Unknown tool '{call.name}'. Available tools: {', '.join(self.registry.names())}.")
            return None
        if call.error:
            self._invalid(state, call, f"Invalid arguments: {call.error}. Fix and retry.")
            return None
        try:
            args = tool.args_model.model_validate(call.arguments or {})
        except ValidationError as exc:
            self._invalid(state, call, f"Invalid arguments: {_format_validation(exc)}. Fix and retry.")
            return None

        ctx = self._ctx(state.conversation_id)
        assessment = evaluate(tool, args, ctx)
        row = audit.start(self.session, state.conversation_id, tool.name, args.model_dump(mode='json'), str(assessment.level), call.id)

        if assessment.error:
            result = ToolResult.fail(assessment.error)
            audit.finish(row, "error", assessment.error)
        elif assessment.level == RiskLevel.BLOCKED:
            reason = "; ".join(assessment.reasons)
            result = ToolResult.fail(f"Blocked: {reason} Do not retry; explain this to the user.")
            audit.finish(row, "blocked", reason)
        elif assessment.needs_approval:
            return self._pause(state, call, tool, args, row, assessment.level, assessment.reasons, remaining)
        else:
            result = self._execute(tool, args, row, state.conversation_id, approved=False, checked=True)
        self._complete(state, call.id, tool.name, row, result)
        return None

    # ------------------------------------------------------------ execution

    def _execute(
        self, tool: Tool, args: BaseModel, row: ToolCall, conversation_id: str, approved: bool, checked: bool = False
    ) -> ToolResult:
        ctx = self._ctx(conversation_id, audit_id=row.id, approved=approved)
        if not checked:  # re-check at execution time: the filesystem may have changed since approval
            assessment = evaluate(tool, args, ctx)
            if assessment.error or assessment.level == RiskLevel.BLOCKED:
                reason = assessment.error or "; ".join(assessment.reasons)
                audit.finish(row, "error" if assessment.error else "blocked", reason)
                return ToolResult.fail(f"Not executed: {reason}")
        self.session.commit()  # the audit row survives even if the tool crashes

        started = time.perf_counter()
        status = "success"
        try:
            result = tool.run(args, ctx)
            status = "success" if result.ok else "error"
        except SandboxViolation as exc:
            result, status = ToolResult.fail(f"Blocked: {exc.reason}"), "blocked"
        except Exception as exc:  # a tool bug must not crash the agent loop
            logger.exception("Tool %s crashed", tool.name)
            result, status = ToolResult.fail(f"{tool.name} failed: {type(exc).__name__}: {exc}"), "error"
        audit.finish(row, status, result.message, int((time.perf_counter() - started) * 1000))
        return result

    def _pause(
        self,
        state: _Run,
        call: ToolCallRequest,
        tool: Tool,
        args: BaseModel,
        row: ToolCall,
        level: RiskLevel,
        reasons: list[str],
        remaining: list[ToolCallRequest],
    ) -> AgentResponse:
        pending = PendingApproval(
            conversation_id=state.conversation_id,
            audit_id=row.id,
            llm_call_id=call.id,
            tool=tool.name,
            args_json=args.model_dump_json(),
            risk=str(level),
            reasons_json=json.dumps(reasons),
            remaining_calls_json=json.dumps([c.to_json() for c in remaining]),
            steps_used=state.steps_used,
        )
        self.session.add(pending)
        audit.finish(row, "pending", "Waiting for user approval.")
        self.session.commit()
        self._record_step(state, row)
        description = tool.describe(args)
        return AgentResponse(
            type="approval_required",
            conversation_id=state.conversation_id,
            text=f"Mitraa wants to: {description}. Allow?",
            pending_approval=ApprovalInfo(
                approval_id=pending.id,
                tool=tool.name,
                args=args.model_dump(mode='json'),
                risk=str(level),
                description=description,
                reasons=reasons,
            ),
            steps=state.steps,
        )

    def _invalid(self, state: _Run, call: ToolCallRequest, message: str) -> None:
        """Feed an argument error back to the model; allow one repair per run."""
        state.invalid_args += 1
        row = audit.start(self.session, state.conversation_id, call.name, call.raw_arguments, "UNKNOWN", call.id)
        audit.finish(row, "error", message)
        self._complete(state, call.id, call.name, row, ToolResult.fail(message))
        if state.invalid_args > 1:
            raise _Stop(f"I couldn't put together a valid request for '{call.name}', so I stopped. Could you rephrase?")

    def _complete(self, state: _Run, call_id: str, tool_name: str, row: ToolCall, result: ToolResult) -> None:
        self._save_tool_result(state.conversation_id, call_id, tool_name, result)
        self.session.commit()
        self._record_step(state, row)

    def _record_step(self, state: _Run, row: ToolCall) -> None:
        data = audit.to_dict(row)
        step = Step(id=row.id, tool=row.tool, args=data["args"], risk=row.risk, status=row.status, summary=row.result_summary)
        state.steps.append(step)
        if self.on_step:
            self.on_step(step)

    def _finish(self, state: _Run, text: str, save: bool = True) -> AgentResponse:
        if save:
            self._save(state.conversation_id, "assistant", content=text)
            self.session.commit()
        return AgentResponse(type="message", conversation_id=state.conversation_id, text=text, steps=state.steps)

    # ------------------------------------------------------------ persistence

    def _ctx(self, conversation_id: str, audit_id: str = "", approved: bool = False) -> ToolContext:
        return ToolContext(
            session=self.session,
            conversation_id=conversation_id,
            sandbox=self.sandbox,
            settings=self.settings,
            registry=self.registry,
            audit_id=audit_id,
            approved=approved,
            llm=self.llm,
        )

    def _conversation(self, conversation_id: str | None, first_message: str) -> Conversation:
        if conversation_id:
            conversation = self.session.get(Conversation, conversation_id)
            if conversation is None:
                raise ConversationNotFound(conversation_id)
            return conversation
        conversation = Conversation(title=first_message.strip()[:80])
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def _expire_pending(self, conversation_id: str) -> None:
        """A new user message cancels any unanswered approval, keeping the history valid for the API."""
        pendings = self.session.scalars(
            select(PendingApproval)
            .where(PendingApproval.conversation_id == conversation_id, PendingApproval.status == "pending")
            .order_by(PendingApproval.created_at)
        ).all()
        for pending in pendings:
            pending.status = "expired"
            pending.resolved_at = utcnow()
            row = self.session.get(ToolCall, pending.audit_id)
            if row is not None:
                audit.finish(row, "denied", "Not approved: the user sent a new message instead.")
            self._save_tool_result(
                conversation_id, pending.llm_call_id, pending.tool,
                ToolResult.fail("The user did not approve this action, so it was cancelled."),
            )
            for call in json.loads(pending.remaining_calls_json):
                self._save_tool_result(
                    conversation_id, call["id"], call["name"],
                    ToolResult.fail("Skipped because an earlier action was not approved."),
                )

    def _save(self, conversation_id: str, role: str, **fields: Any) -> None:
        self.session.add(Message(conversation_id=conversation_id, role=role, **fields))

    def _save_tool_result(self, conversation_id: str, call_id: str, name: str, result: ToolResult) -> None:
        self._save(conversation_id, "tool", content=_tool_content(result), tool_call_id=call_id, name=name)

    def _history(self, conversation_id: str) -> list[dict[str, Any]]:
        limit = self.settings.mitraa_history_limit
        rows = list(
            self.session.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(limit)
            )
        )[::-1]
        # Start at a user message so no tool result is orphaned from its assistant call.
        while rows and rows[0].role != "user":
            rows.pop(0)
        if not rows:
            last_user = self.session.scalars(
                select(Message.id)
                .where(Message.conversation_id == conversation_id, Message.role == "user")
                .order_by(Message.id.desc())
                .limit(1)
            ).first()
            if last_user is not None:
                rows = list(
                    self.session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id, Message.id >= last_user)
                        .order_by(Message.id)
                    )
                )

        last_user = next((row.content or "" for row in reversed(rows) if row.role == "user"), "")
        memories = top_k(self.session, last_user)
        self.session.commit()
        memory_lines = "\n".join(f"- [{m.type}] {m.key}: {m.value}" for m in memories)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.sandbox.describe_roots(), memory_lines)}
        ]
        for row in rows:
            if row.role == "assistant" and row.tool_calls_json:
                messages.append({"role": "assistant", "content": row.content, "tool_calls": json.loads(row.tool_calls_json)})
            elif row.role == "tool":
                messages.append({"role": "tool", "tool_call_id": row.tool_call_id, "content": row.content or ""})
            else:
                messages.append({"role": row.role, "content": row.content or ""})
        return messages


def _tool_content(result: ToolResult) -> str:
    text = result.model_dump_json()
    if len(text) <= MAX_TOOL_MESSAGE_CHARS:
        return text
    return json.dumps(
        {"ok": result.ok, "message": result.message, "data_truncated": text[:MAX_TOOL_MESSAGE_CHARS]},
        ensure_ascii=False,
    )


def _format_validation(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"]) or "arguments"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
