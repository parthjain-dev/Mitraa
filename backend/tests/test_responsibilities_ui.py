from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal, QDateTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest
from mitraa.assistant.ui.responsibilities import DeskRuntime, ReminderDialog, wall_instant, date_editor
from mitraa.db.models import Reminder
from mitraa.responsibilities import service
from mitraa.responsibilities.schemas import Preferences

app=QApplication.instance() or QApplication([])


class Tray(QObject):
    messageClicked=Signal()
    def __init__(self): super().__init__(); self.messages=[]
    def showMessage(self,*args): self.messages.append(args)
    def isSystemTrayAvailable(self): return True
    def supportsMessages(self): return True


def until(predicate):
    for _ in range(100):
        app.processEvents()
        if predicate(): return
        QTest.qWait(20)
    assert predicate(), 'Desktop operation did not finish'


@pytest.fixture
def runtime(session_factory):
    with session_factory() as session:
        service.save_preferences(session,Preferences(quiet_enabled=False)); session.commit()
    tray=Tray(); value=DeskRuntime(tray,SimpleNamespace(worker=None),factory=session_factory)
    value.timer.stop()
    until(lambda:bool(value.snapshot))
    yield value
    value.shutdown(); app.processEvents()


def test_desktop_capture_edit_and_complete_without_provider(runtime):
    desk=runtime.desk
    desk.title.setText('Prepare for interview'); desk.outcome.setPlainText('Ready for the interview')
    desk.next_action.setText('Read role description'); desk.save()
    until(lambda:bool(desk.selected_id) and not desk.pending_save)
    rid=desk.selected_id
    assert desk.items[rid]['next_action']=='Read role description'
    desk.state.setCurrentText('completed'); desk.save()
    assert 'confirmed completion' in desk.notice.text()
    desk.confirmation.setText('I completed my preparation checklist'); desk.save()
    until(lambda:not desk.pending_save)
    assert desk.items[rid]['status']=='completed' and desk.items[rid]['completed_at']


def test_dirty_edits_survive_background_refresh_and_stale_save_is_rejected(runtime,session_factory):
    desk=runtime.desk; desk.title.setText('Original'); desk.save()
    until(lambda:bool(desk.selected_id) and not desk.pending_save)
    rid=desk.selected_id
    desk.title.setText('Unsaved personal edit')
    from mitraa.responsibilities.schemas import ResponsibilityPatch
    with session_factory() as session:
        service.patch(session,rid,ResponsibilityPatch(expected_version=1,title='Newer external edit')); session.commit()
    runtime.refresh(); until(lambda:runtime.snapshot['responsibilities'][0]['version']==2)
    assert desk.title.text()=='Unsaved personal edit' and desk.version==1
    desk.save(); until(lambda:not desk.pending_save)
    assert 'Refresh' in desk.notice.text() and desk.title.text()=='Unsaved personal edit'


def test_reminder_dialog_and_delivery_can_notify_again_after_snooze(runtime,session_factory):
    desk=runtime.desk; desk.title.setText('Application'); desk.save()
    until(lambda:bool(desk.selected_id) and not desk.pending_save)
    rid=desk.selected_id
    dialog=ReminderDialog(runtime,desk.items[rid]); dialog.zone.setText('UTC')
    when=datetime.now(timezone.utc)+timedelta(hours=1)
    dialog.when.setDateTime(QDateTime.fromString(when.strftime('%Y-%m-%dT%H:%M:%S'),'yyyy-MM-ddTHH:mm:ss'))
    dialog.save(); until(lambda:len(runtime.snapshot['reminders'])==1)
    mid=runtime.snapshot['reminders'][0]['id']
    with session_factory() as session:
        session.get(Reminder,mid).due_at=datetime.now(timezone.utc)-timedelta(minutes=1); session.commit()
    runtime.refresh(); until(lambda:len(runtime.tray.messages)==1)
    until(lambda:runtime.snapshot['reminders'][0]['notified_at'] is not None)
    runtime.refresh(); QTest.qWait(100); assert len(runtime.tray.messages)==1
    runtime.worker.submit('reminder_action',reminder_id=mid,action='snooze',due_at=datetime.now(timezone.utc)+timedelta(hours=1))
    until(lambda:runtime.snapshot['reminders'][0]['status']=='scheduled')
    with session_factory() as session:
        session.get(Reminder,mid).due_at=datetime.now(timezone.utc)-timedelta(minutes=1); session.commit()
    runtime.refresh(); until(lambda:len(runtime.tray.messages)==2)
    assert 'Application' not in str(runtime.tray.messages)
    runtime.worker.submit('reminder_action',reminder_id=mid,action='acknowledge')
    until(lambda:runtime.snapshot['reminders'][0]['status']=='acknowledged')
    assert runtime.snapshot['responsibilities'][0]['status']=='captured'


@pytest.mark.parametrize('wall',['2026-03-08T02:30:00','2026-11-01T01:30:00'])
def test_wall_times_reject_nonexistent_or_ambiguous_dst(wall):
    editor=date_editor(); editor.setDateTime(QDateTime.fromString(wall,'yyyy-MM-ddTHH:mm:ss'))
    with pytest.raises(ValueError): wall_instant(editor,'America/New_York')


def test_explicit_timezone_converts_to_utc():
    editor=date_editor(); editor.setDateTime(QDateTime.fromString('2026-10-21T15:30:00','yyyy-MM-ddTHH:mm:ss'))
    assert wall_instant(editor,'Asia/Kolkata')=='2026-10-21T10:00:00+00:00'


def make_due(runtime, session_factory):
    from mitraa.responsibilities.schemas import ResponsibilityCreate, ReminderCreate
    with session_factory() as session:
        owner=service.create(session,ResponsibilityCreate(title='Test local reminder'))
        row=service.add_reminder(session,ReminderCreate(responsibility_id=owner['id'],
            message='Check the alert',due_at=datetime.now(timezone.utc)+timedelta(minutes=1)))
        saved=session.get(Reminder,row['id'])
        saved.due_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        saved.notified_at=datetime.now(timezone.utc)  # OS already requested, user missed it
        session.commit()
    runtime.refresh(); until(lambda:runtime.alert.isVisible())
    return row['id']


def test_local_alert_works_without_system_notifications_and_snoozes(runtime,session_factory):
    runtime.tray.supportsMessages=lambda:False
    mid=make_due(runtime,session_factory)
    assert runtime.alert.reminder_id==mid and not runtime.tray.messages
    runtime.alert.snooze.click(); runtime.alert.snooze.click()
    until(lambda:runtime.snapshot['reminders'][0]['status']=='scheduled')
    assert not runtime.alert.isVisible()
    with session_factory() as session:
        saved=session.get(Reminder,mid)
        assert saved.notified_at is None
        saved.due_at=datetime.now(timezone.utc)-timedelta(seconds=1); session.commit()
    runtime.refresh(); until(lambda:runtime.alert.isVisible())
    runtime.alert.ack.click()
    until(lambda:runtime.snapshot['reminders'][0]['status']=='acknowledged')
    assert not runtime.alert.isVisible()
    assert runtime.snapshot['responsibilities'][0]['status']=='captured'


def test_dismissed_local_alert_stays_in_inbox_without_reopening(runtime,session_factory):
    make_due(runtime,session_factory)
    runtime.alert.reject(); runtime.refresh()
    QTest.qWait(150); app.processEvents()
    assert not runtime.alert.isVisible() and runtime.snapshot['due']


def test_local_alert_respects_notification_preferences(runtime,session_factory):
    make_due(runtime,session_factory)
    payload=runtime.snapshot
    runtime.update_alert({**payload,'preferences':{**payload['preferences'],'notifications_enabled':False}})
    assert not runtime.alert.isVisible()
    runtime.update_alert({**payload,'preferences':{**payload['preferences'],
        'quiet_enabled':True,'quiet_start':'00:00','quiet_end':'23:59','timezone':'UTC'}})
    # Use an explicit, always-quiet predicate for deterministic UI wiring.
    from unittest.mock import patch
    with patch('mitraa.responsibilities.service.is_quiet',return_value=True):
        runtime.update_alert(payload)
    assert not runtime.alert.isVisible()
