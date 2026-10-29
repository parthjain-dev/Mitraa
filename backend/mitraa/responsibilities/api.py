"""Local API; these endpoints work without a configured AI provider."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from mitraa.db.session import get_session
from mitraa.responsibilities import service
from mitraa.responsibilities.schemas import ResponsibilityCreate, ResponsibilityPatch, ReminderCreate, SnoozeRequest, Preferences, Status

router = APIRouter()

from mitraa.responsibilities import drafts
from mitraa.responsibilities import jobs
from pydantic import BaseModel,Field


class JobAction(BaseModel):
    expected_version: int=Field(ge=1)
    confirmed: bool=False
    note: str=Field(default='',max_length=5000)


@router.get('/responsibilities/{rid}/coding-jobs')
def coding_jobs(rid: str,session: Session=Depends(get_session)):
    return call(session,jobs.list_jobs,rid)


@router.post('/coding-jobs',status_code=201)
def prepare_coding_job(data: jobs.JobCreate,session: Session=Depends(get_session)):
    from mitraa.config import get_settings
    return call(session,jobs.create,data,get_settings())


@router.get('/coding-jobs/{jid}')
def coding_job(jid: str,session: Session=Depends(get_session)):
    return call(session,lambda s:jobs.as_dict(jobs.row(s,jid)))


@router.post('/coding-jobs/{jid}/cancel')
def cancel_coding_job(jid: str,data: JobAction,session: Session=Depends(get_session)):
    return call(session,jobs.cancel,jid,data.expected_version)


@router.post('/coding-jobs/{jid}/accept')
def accept_coding_job(jid: str,data: JobAction,session: Session=Depends(get_session)):
    return call(session,jobs.accept,jid,data.expected_version,data.note,data.confirmed)


@router.get('/responsibilities/{rid}/drafts')
def prepared_drafts(rid: str, session: Session = Depends(get_session)):
    return call(session,drafts.list_drafts,rid)


@router.post('/responsibilities/{rid}/drafts',status_code=201)
def prepare_draft(rid: str,data: drafts.DraftContent,session: Session = Depends(get_session)):
    return call(session,drafts.create,rid,data)


@router.post('/responsibilities/{rid}/checklist',status_code=201)
def prepare_checklist(rid: str,session: Session = Depends(get_session)):
    return call(session,drafts.checklist,rid)


@router.get('/drafts/{draft_id}')
def draft_detail(draft_id: str,session: Session = Depends(get_session)):
    return call(session,drafts.detail,draft_id)


@router.patch('/drafts/{draft_id}')
def revise_draft(draft_id: str,data: drafts.DraftUpdate,session: Session = Depends(get_session)):
    return call(session,drafts.revise,draft_id,data)


@router.post('/drafts/{draft_id}/review')
def review_draft(draft_id: str,data: drafts.DraftReview,session: Session = Depends(get_session)):
    return call(session,drafts.review,draft_id,data)


def call(session, operation, *args, **kwargs):
    try:
        result = operation(session, *args, **kwargs)
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        code = 404 if isinstance(exc, service.NotFound) else 409 if isinstance(exc, service.Conflict) else 422
        raise HTTPException(code, str(exc)) from exc


@router.get('/responsibilities')
def items(status: Status | None = None, session: Session = Depends(get_session)):
    return service.list_items(session, status)


@router.post('/responsibilities', status_code=201)
def create(data: ResponsibilityCreate, session: Session = Depends(get_session)):
    return call(session, service.create, data)


@router.get('/responsibilities/{rid}')
def detail(rid: str, session: Session = Depends(get_session)):
    return call(session, lambda s: service.as_dict(service.get(s, rid)))


@router.patch('/responsibilities/{rid}')
def patch(rid: str, data: ResponsibilityPatch, session: Session = Depends(get_session)):
    return call(session, service.patch, rid, data)


@router.get('/responsibilities/{rid}/history')
def history(rid: str, session: Session = Depends(get_session)):
    return call(session, service.history, rid)


@router.delete('/responsibilities/{rid}')
def forget(rid: str, confirmed: bool = False, expected_version: int = Query(ge=1, default=1),
           session: Session = Depends(get_session)):
    if not confirmed:
        raise HTTPException(409, 'Forgetting permanently removes this responsibility, its reminders and history. Set confirmed=true.')
    return call(session, service.forget, rid, expected_version)


@router.get('/reminders')
def reminders(responsibility_id: str | None = None, session: Session = Depends(get_session)):
    return call(session, service.list_reminders, responsibility_id)


@router.post('/reminders', status_code=201)
def reminder(data: ReminderCreate, session: Session = Depends(get_session)):
    return call(session, service.add_reminder, data)


@router.post('/reminders/{reminder_id}/snooze')
def snooze(reminder_id: str, data: SnoozeRequest, session: Session = Depends(get_session)):
    return call(session, service.change_reminder, reminder_id, 'snooze', data.due_at)


@router.post('/reminders/{reminder_id}/acknowledge')
def acknowledge(reminder_id: str, session: Session = Depends(get_session)):
    return call(session, service.change_reminder, reminder_id, 'acknowledge')


@router.delete('/reminders/{reminder_id}')
def cancel(reminder_id: str, session: Session = Depends(get_session)):
    return call(session, service.change_reminder, reminder_id, 'cancel')


@router.get('/follow-up')
def follow_up(session: Session = Depends(get_session)):
    # API reads never consume desktop notifications.
    return call(session, service.poll)


@router.get('/reminder-preferences')
def preferences(session: Session = Depends(get_session)):
    return call(session, lambda s: service.preferences(s).model_dump())


@router.put('/reminder-preferences')
def save_preferences(data: Preferences, session: Session = Depends(get_session)):
    return call(session, service.save_preferences, data)
