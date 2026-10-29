from PySide6.QtWidgets import QMessageBox
from mitraa.responsibilities import service
from mitraa.responsibilities.schemas import ResponsibilityCreate
from tests.test_responsibilities_ui import runtime,until,app


def test_offline_checklist_edit_diff_and_review(runtime,session_factory,monkeypatch):
    with session_factory() as session:
        owner=service.create(session,ResponsibilityCreate(title='Portfolio',outcome='Publish a reviewed portfolio',
            next_action='Prepare introduction',sources=['My supplied notes']))
        session.commit()
    runtime.open_drafts(owner); panel=runtime.drafts
    until(lambda:not panel.pending)
    panel.prepare_checklist(); until(lambda:panel.current is not None and not panel.pending)
    assert 'Prepare introduction' in panel.content.toPlainText()
    assert panel.current['review_status']=='pending' and panel.versions.count()==1
    panel.content.setPlainText('# Portfolio\nMy introduction draft.')
    panel.missing.setPlainText('Which projects should be included?')
    panel.save_draft(); until(lambda:not panel.pending and panel.current['version']==2)
    assert '+My introduction draft.' in panel.diff.toPlainText()
    assert panel.versions.count()==2
    panel.review_note.setText('Checked the draft')
    panel.review('accepted')
    assert 'missing facts' in panel.notice.text()
    panel.missing.clear(); panel.content.setPlainText('# Portfolio\nInclude only my confirmed projects.')
    panel.save_draft(); until(lambda:not panel.pending and panel.current['version']==3)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    panel.review_note.setText('Checked each claim against my notes')
    panel.review('accepted'); until(lambda:not panel.pending and panel.current['review_status']=='accepted')
    with session_factory() as session:
        assert service.get(session,owner['id']).status=='captured'
    panel.versions.setCurrentIndex(0)
    assert 'Prepare introduction' in panel.saved_preview.toPlainText()


def test_stale_edit_preserves_unsaved_draft(runtime,session_factory):
    from mitraa.responsibilities import drafts
    with session_factory() as session:
        owner=service.create(session,ResponsibilityCreate(title='Test'))
        row=drafts.create(session,owner['id'],drafts.DraftContent(title='Draft',content='Original'))
        session.commit()
    runtime.open_drafts(owner); panel=runtime.drafts
    until(lambda:not panel.pending and panel.current is not None)
    panel.content.setPlainText('My unsaved edit')
    with session_factory() as session:
        drafts.revise(session,row['id'],drafts.DraftUpdate(title='Draft',content='External edit',expected_version=1))
        session.commit()
    panel.save_draft(); until(lambda:not panel.pending)
    assert 'Reload' in panel.notice.text()
    assert panel.content.toPlainText()=='My unsaved edit' and panel.dirty
