from datetime import datetime,timezone
from unittest.mock import patch
from mitraa.responsibilities import service
from mitraa.responsibilities.schemas import ResponsibilityCreate,Preferences
from mitraa.tools.responsibility_tools import AddRelativeReminder,RelativeReminderArgs,GetCurrentTime,FollowUpArgs


def test_five_minutes_computed_from_clock_not_model_guess(make_ctx):
    ctx=make_ctx()
    owner=service.create(ctx.session,ResponsibilityCreate(title='Drink water'))
    service.save_preferences(ctx.session,Preferences(timezone='Asia/Kolkata'))
    now=datetime(2026,10,29,15,10,31,tzinfo=timezone.utc)
    with patch('mitraa.tools.responsibility_tools.datetime') as clock:
        clock.now.return_value=now
        result=AddRelativeReminder().run(RelativeReminderArgs(responsibility_id=owner['id'],
            message='Drink water',delay_minutes=5),ctx)
        time=GetCurrentTime().run(FollowUpArgs(),ctx)
    assert result.ok
    assert result.data['reminder']['due_at']=='2026-10-29T15:15:31+00:00'
    assert result.data['local_due_at']=='2026-10-29T20:45:31+05:30'
    assert time.data['local']=='2026-10-29T20:40:31+05:30'
    assert service.get(ctx.session,owner['id']).deadline is None


def test_relative_reminder_rejects_invalid_delays():
    import pytest
    from pydantic import ValidationError
    for value in (0,-5,float('inf'),float('nan'),525601):
        with pytest.raises(ValidationError):
            RelativeReminderArgs(responsibility_id='id',message='Test',delay_minutes=value)
