"""Responsibility tools share the same validated service as the local desktop."""
from pydantic import BaseModel, Field, AwareDatetime
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from mitraa.responsibilities import service
from mitraa.responsibilities.schemas import ResponsibilityCreate, ResponsibilityPatch, ReminderCreate, Status
from mitraa.tools.base import Tool, ToolContext, ToolResult, RiskLevel


class CreateResponsibility(Tool):
    name = 'create_responsibility'
    description = 'Capture an ongoing responsibility with its desired outcome, next action and source references. Dates must include a timezone offset. Clarify ambiguous deadlines; never invent them.'
    args_model = ResponsibilityCreate
    base_risk = RiskLevel.LOW

    def run(self, args, ctx):
        return ToolResult.success('Responsibility saved locally.', responsibility=service.create(ctx.session, args))


class ListArgs(BaseModel):
    status: Status | None = None


class ListResponsibilities(Tool):
    name = 'list_responsibilities'
    description = 'List saved responsibilities, including IDs and versions needed to update them. Use before selecting a responsibility; clarify ambiguous matches.'
    args_model = ListArgs
    base_risk = RiskLevel.LOW

    def run(self, args, ctx):
        return ToolResult.success('Saved responsibilities.', responsibilities=service.list_items(ctx.session, args.status))


class UpdateArgs(ResponsibilityPatch):
    responsibility_id: str


class UpdateResponsibility(Tool):
    name = 'update_responsibility'
    description = 'Update a saved responsibility using its current expected_version. Complete only after the user explicitly confirms completion, recording that confirmation in completion_note. Prepared is not submitted. Pausing suppresses reminders; reopening does not recreate closed reminders.'
    args_model = UpdateArgs
    base_risk = RiskLevel.LOW

    def run(self, args, ctx):
        data = ResponsibilityPatch.model_validate(args.model_dump(exclude={'responsibility_id'}, exclude_unset=True))
        return ToolResult.success('Responsibility updated.', responsibility=service.patch(ctx.session, args.responsibility_id, data))


class AddReminder(Tool):
    name = 'add_reminder'
    description = 'Save a local follow-up reminder for a responsibility at a future time with explicit UTC offset. Ask when the intended time is unclear. Local reminders need the desktop app running; overdue reminders catch up when it resumes.'
    args_model = ReminderCreate
    base_risk = RiskLevel.LOW

    def run(self, args, ctx):
        return ToolResult.success('Local reminder saved.', reminder=service.add_reminder(ctx.session, args))


class ReminderActionArgs(BaseModel):
    reminder_id: str
    action: str = Field(description='snooze, acknowledge or cancel')
    due_at: AwareDatetime | None = None


class ChangeReminder(Tool):
    name = 'change_reminder'
    description = 'Snooze a reminder to a specified future time, acknowledge it, or cancel it. Acknowledgement closes the reminder but does not complete the responsibility.'
    args_model = ReminderActionArgs
    base_risk = RiskLevel.LOW

    def run(self, args, ctx):
        return ToolResult.success('Reminder updated.', reminder=service.change_reminder(ctx.session, args.reminder_id, args.action, args.due_at))


class FollowUpArgs(BaseModel):
    pass


class GetFollowUp(Tool):
    name = 'get_follow_up'
    description = 'List saved reminders and overdue follow-ups without marking them read or delivered.'
    args_model = FollowUpArgs
    base_risk = RiskLevel.LOW

    def run(self, args, ctx):
        return ToolResult.success('Local follow-ups.', reminders=service.list_reminders(ctx.session))


ALL_RESPONSIBILITY_TOOLS = [CreateResponsibility(), ListResponsibilities(), UpdateResponsibility(),
                            AddReminder(), ChangeReminder(), GetFollowUp()]

from mitraa.responsibilities import drafts


class PrepareDraftArgs(drafts.DraftContent):
    responsibility_id: str


class PrepareDraft(Tool):
    name='prepare_responsibility_draft'
    description='Save a reviewable local plain-text/Markdown draft for a saved responsibility. Use supplied facts only; add explicit placeholders and missing_facts questions for unknown claims. sources must be references already on the responsibility; references alone do not mean a file was read. No export, execution or submission occurs. Never claim the user has reviewed it.'
    args_model=PrepareDraftArgs
    base_risk=RiskLevel.LOW
    def run(self,args,ctx):
        data=drafts.DraftContent.model_validate(args.model_dump(exclude={'responsibility_id'}))
        return ToolResult.success('Draft saved for user review; nothing submitted.',draft=drafts.create(ctx.session,args.responsibility_id,data))


class DraftListArgs(BaseModel):
    responsibility_id: str


class ListDrafts(Tool):
    name='list_responsibility_drafts'
    description='Read saved drafts, source context, missing facts and current versions for a responsibility.'
    args_model=DraftListArgs
    base_risk=RiskLevel.LOW
    def run(self,args,ctx):
        return ToolResult.success('Prepared drafts.',drafts=drafts.list_drafts(ctx.session,args.responsibility_id))


class ReviseDraftArgs(drafts.DraftUpdate):
    draft_id: str


class ReviseDraft(Tool):
    name='revise_responsibility_draft'
    description='Save a new draft revision with expected_version. Read/list drafts first. Keep sources and missing facts accurate. Every new revision requires fresh user review; this does not complete a responsibility.'
    args_model=ReviseDraftArgs
    base_risk=RiskLevel.LOW
    def run(self,args,ctx):
        data=drafts.DraftUpdate.model_validate(args.model_dump(exclude={'draft_id'}))
        return ToolResult.success('New revision saved for review.',draft=drafts.revise(ctx.session,args.draft_id,data))


ALL_RESPONSIBILITY_TOOLS += [PrepareDraft(),ListDrafts(),ReviseDraft()]


class RelativeReminderArgs(BaseModel):
    responsibility_id: str
    message: str = Field(min_length=1,max_length=500)
    delay_minutes: float = Field(gt=0,le=525600,allow_inf_nan=False,
        description='Minutes from the actual computer clock. For in five minutes use 5. Do not calculate a UTC timestamp.')


class AddRelativeReminder(Tool):
    name='add_relative_reminder'
    description='Schedule a follow-up relative to NOW using the computer clock, e.g. in 5 minutes or 2 hours (120 minutes). Always use this for relative delays instead of guessing due_at. Does not set the responsibility deadline. Returns the confirmed local and UTC time.'
    args_model=RelativeReminderArgs
    base_risk=RiskLevel.LOW

    def run(self,args,ctx):
        now=datetime.now(timezone.utc)
        due=now+timedelta(minutes=args.delay_minutes)
        result=service.add_reminder(ctx.session,ReminderCreate(responsibility_id=args.responsibility_id,
            message=args.message,due_at=due),now=now)
        zone=service.preferences(ctx.session).timezone
        local=due.astimezone(ZoneInfo(zone)).isoformat()
        return ToolResult.success(f'Reminder saved for {local} ({zone}).',reminder=result,
            local_due_at=local,timezone=zone)


class GetCurrentTime(Tool):
    name='get_current_time'
    description='Read the actual current UTC time and the user reminder timezone/local time before interpreting absolute times or checking if a reminder is due. Never infer current time from an earlier message.'
    args_model=FollowUpArgs
    base_risk=RiskLevel.LOW

    def run(self,args,ctx):
        now=datetime.now(timezone.utc)
        zone=service.preferences(ctx.session).timezone
        return ToolResult.success('Current computer time.',utc=now.isoformat(),
            local=now.astimezone(ZoneInfo(zone)).isoformat(),timezone=zone)


ALL_RESPONSIBILITY_TOOLS += [AddRelativeReminder(),GetCurrentTime()]
