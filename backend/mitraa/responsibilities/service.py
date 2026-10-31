"""Transactions are committed by the caller; all timestamps are stored in UTC."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, delete
from mitraa.db.models import Responsibility, ResponsibilityEvent, Reminder, ReminderPreferences, utcnow
from mitraa.responsibilities.schemas import ResponsibilityCreate, ResponsibilityPatch, ReminderCreate, Preferences

TERMINAL = {'completed', 'cancelled'}


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


def utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes for UTC values even with timezone=True.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def stamp(value):
    return utc(value).isoformat() if value is not None else None


def event(session, rid, kind, **details):
    session.add(ResponsibilityEvent(responsibility_id=rid, kind=kind, details_json=json.dumps(details)))


def get(session, rid):
    row = session.get(Responsibility, rid)
    if row is None:
        raise NotFound('Responsibility not found.')
    return row


def as_dict(row):
    return {**{key: getattr(row, key) for key in ('id', 'title', 'outcome', 'next_action', 'notes',
            'status', 'priority', 'timezone', 'completion_note', 'version')},
            'sources': json.loads(row.sources_json), 'deadline': stamp(row.deadline),
            'created_at': stamp(row.created_at), 'updated_at': stamp(row.updated_at),
            'completed_at': stamp(row.completed_at)}


def list_items(session, status=None):
    query = select(Responsibility).order_by(Responsibility.updated_at.desc(), Responsibility.id)
    if status is not None:
        query = query.where(Responsibility.status == status)
    return [as_dict(row) for row in session.scalars(query)]


def create(session, data: ResponsibilityCreate):
    values = data.model_dump(exclude={'sources'})
    if values['deadline'] is not None:
        values['deadline'] = utc(values['deadline'])
    row = Responsibility(**values, sources_json=json.dumps(data.sources))
    session.add(row); session.flush()
    event(session, row.id, 'created', title=row.title)
    return as_dict(row)


def patch(session, rid, data: ResponsibilityPatch):
    row = get(session, rid)
    session.refresh(row)
    changes = data.model_dump(exclude_unset=True, exclude={'expected_version'})
    if any(value is None for key, value in changes.items() if key != 'deadline'):
        raise ValueError('Only deadline may be cleared with null.')
    # Reuse creation validation for editable fields, including source and timezone checks.
    editable = {key: value for key, value in changes.items() if key not in {'status', 'completion_note'}}
    validated = ResponsibilityCreate.model_validate({**{key: as_dict(row)[key] for key in
        ResponsibilityCreate.model_fields}, **editable})
    for key in editable:
        if key == 'sources':
            changes['sources_json'] = json.dumps(validated.sources); del changes['sources']
        else:
            changes[key] = getattr(validated, key)
    if changes.get('deadline') is not None:
        changes['deadline'] = utc(changes['deadline'])
    new_status = changes.get('status', row.status)
    if row.status in TERMINAL and new_status not in {row.status, 'captured', 'active'}:
        raise ValueError('Reopen a finished responsibility as captured or active first.')
    if new_status == 'completed' and row.status != 'completed':
        if not changes.get('completion_note', '').strip():
            raise ValueError('Record how completion was confirmed before marking this complete.')
        changes['completed_at'] = utcnow()
    elif new_status != 'completed':
        changes['completed_at'] = None
        changes['completion_note'] = ''
    elif 'completion_note' in changes and not changes['completion_note'].strip():
        raise ValueError('Completion confirmation cannot be empty.')
    changes.update(updated_at=utcnow(), version=data.expected_version + 1)
    result = session.execute(update(Responsibility).where(Responsibility.id == rid,
        Responsibility.version == data.expected_version).values(**changes),
        execution_options={'synchronize_session': False})
    if result.rowcount != 1:
        raise Conflict('This responsibility changed. Refresh and review it before saving again.')
    event(session, rid, 'updated', fields=sorted(editable), status=new_status,
          completion_note=changes.get('completion_note', row.completion_note))
    if new_status in TERMINAL:
        session.execute(update(Reminder).where(Reminder.responsibility_id == rid,
            Reminder.status.in_(['scheduled', 'due'])).values(status='cancelled'))
    session.flush(); session.expire(row)
    return as_dict(row)


def history(session, rid):
    get(session, rid)
    return [{'id': row.id, 'kind': row.kind, 'details': json.loads(row.details_json),
             'created_at': stamp(row.created_at)} for row in session.scalars(select(ResponsibilityEvent)
             .where(ResponsibilityEvent.responsibility_id == rid).order_by(ResponsibilityEvent.id))]


def forget(session, rid, expected_version):
    row = get(session, rid)
    if row.version != expected_version:
        raise Conflict('This responsibility changed. Refresh before forgetting it.')
    # Claim this version before removing children, including on FK-enforcing DBs.
    result = session.execute(update(Responsibility).where(Responsibility.id == rid,
        Responsibility.version == expected_version).values(version=expected_version + 1),
        execution_options={'synchronize_session': False})
    if result.rowcount != 1:
        raise Conflict('This responsibility changed. Refresh before forgetting it.')
    from mitraa.db.models import CodingJob,CodingCheck
    if session.scalar(select(CodingJob.id).where(CodingJob.responsibility_id==rid,CodingJob.status.in_({'running','checking'}))):
        raise ValueError('Cancel running coding jobs before forgetting this responsibility.')
    session.execute(delete(Reminder).where(Reminder.responsibility_id == rid))
    from mitraa.responsibilities.drafts import forget_for_responsibility
    forget_for_responsibility(session,rid)
    session.execute(delete(CodingCheck).where(CodingCheck.job_id.in_(select(CodingJob.id).where(CodingJob.responsibility_id==rid))))
    session.execute(delete(CodingJob).where(CodingJob.responsibility_id==rid))
    session.execute(delete(ResponsibilityEvent).where(ResponsibilityEvent.responsibility_id == rid))
    session.execute(delete(Responsibility).where(Responsibility.id == rid),
                    execution_options={'synchronize_session': False})
    return {'deleted': rid}


def reminder_dict(row):
    return {'id': row.id, 'responsibility_id': row.responsibility_id, 'message': row.message,
            'due_at': stamp(row.due_at), 'status': row.status, 'notified_at': stamp(row.notified_at),
            'acknowledged_at': stamp(row.acknowledged_at)}


def reminder(session, reminder_id):
    row = session.get(Reminder, reminder_id)
    if row is None:
        raise NotFound('Reminder not found.')
    return row


def add_reminder(session, data: ReminderCreate, now=None):
    owner = get(session, data.responsibility_id)
    if owner.status in TERMINAL:
        raise ValueError('Reopen the responsibility before adding a reminder.')
    now = utc(now or utcnow())
    if utc(data.due_at) <= now:
        raise ValueError('Choose a reminder time in the future.')
    row = Reminder(**{**data.model_dump(), 'due_at': utc(data.due_at)})
    session.add(row); session.flush()
    event(session, owner.id, 'reminder_created', reminder_id=row.id, due_at=stamp(row.due_at))
    return reminder_dict(row)


def list_reminders(session, rid=None):
    query = select(Reminder).order_by(Reminder.due_at, Reminder.id)
    if rid is not None:
        get(session, rid); query = query.where(Reminder.responsibility_id == rid)
    return [reminder_dict(row) for row in session.scalars(query)]


def change_reminder(session, reminder_id, action, due_at=None, now=None):
    row = reminder(session, reminder_id)
    session.refresh(row)
    owner = get(session, row.responsibility_id)
    if row.status in {'acknowledged', 'cancelled'}:
        raise Conflict('This reminder is already closed. Add a new reminder instead.')
    now = utc(now or utcnow())
    if action == 'snooze':
        if due_at is None or utc(due_at) <= now:
            raise ValueError('Choose a snooze time in the future.')
        if owner.status in TERMINAL:
            raise ValueError('This responsibility is already finished.')
        changes = dict(due_at=utc(due_at),status='scheduled',notified_at=None)
    elif action == 'acknowledge':
        changes = dict(status='acknowledged',acknowledged_at=now)
    elif action == 'cancel':
        changes = dict(status='cancelled')
    else:
        raise ValueError('Unknown reminder action.')
    changed = session.execute(update(Reminder).where(Reminder.id == reminder_id,
        Reminder.status == row.status, Reminder.due_at == row.due_at).values(**changes),
        execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        raise Conflict('This reminder changed. Refresh before trying again.')
    session.expire(row)
    event(session, owner.id, 'reminder_' + action, reminder_id=row.id, due_at=stamp(row.due_at))
    session.flush()
    return reminder_dict(row)


def preferences(session, default_timezone='UTC'):
    row = session.get(ReminderPreferences, 1)
    if row is None:
        data = Preferences(timezone=default_timezone)
        row = ReminderPreferences(id=1, **data.model_dump()); session.add(row); session.flush()
    return Preferences(**{key: getattr(row, key) for key in Preferences.model_fields})


def save_preferences(session, data: Preferences):
    preferences(session)
    row = session.get(ReminderPreferences, 1)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    return data.model_dump()


def is_quiet(data: Preferences, now: datetime):
    if not data.quiet_enabled or data.quiet_start == data.quiet_end:
        return False
    local_clock = utc(now).astimezone(ZoneInfo(data.timezone)).strftime('%H:%M')
    start, end = data.quiet_start, data.quiet_end
    return start <= local_clock < end if start < end else local_clock >= start or local_clock < end


def poll(session, now=None, default_timezone='UTC'):
    """Persistent inbox first; notifications are a best-effort convenience."""
    now = utc(now or utcnow())
    prefs = preferences(session, default_timezone)
    active_ids = select(Responsibility.id).where(~Responsibility.status.in_(TERMINAL | {'paused'}))
    session.execute(update(Reminder).where(Reminder.status == 'scheduled', Reminder.due_at <= now,
        Reminder.responsibility_id.in_(active_ids)).values(status='due'))
    rows = list(session.scalars(select(Reminder).where(Reminder.status == 'due',
        Reminder.responsibility_id.in_(active_ids)).order_by(Reminder.due_at, Reminder.id)))
    due = [{**reminder_dict(row), 'title': get(session, row.responsibility_id).title} for row in rows]
    return {'due': due, 'notify': [r for r in due if r['notified_at'] is None]
            if prefs.notifications_enabled and not is_quiet(prefs, now) else [],
            'preferences': prefs.model_dump()}


def mark_notified(session, ids, now=None):
    if ids:
        session.execute(update(Reminder).where(Reminder.id.in_(ids), Reminder.status == 'due',
            Reminder.notified_at.is_(None)).values(notified_at=utc(now or utcnow())))
