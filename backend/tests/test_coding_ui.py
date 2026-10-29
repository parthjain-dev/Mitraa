from PySide6.QtWidgets import QMessageBox
from mitraa.responsibilities import jobs,service
from tests.test_responsibilities_ui import runtime,until
from tests.test_coding_jobs import prepared,Adapter


def test_prepare_review_contract_and_run_with_fake_adapter(runtime,session_factory,settings,roots,tmp_path,monkeypatch):
    with session_factory() as session:
        item,root,_=prepared(session,settings,roots)
        owner=service.as_dict(service.get(session,item['responsibility_id']))
    monkeypatch.setattr('mitraa.config.get_settings',lambda:settings)
    runtime.coder.settings=settings;runtime.coder.adapter=Adapter();runtime.coder.artifact_base=tmp_path/'artifacts'
    runtime.open_jobs(owner);panel=runtime.jobs
    until(lambda:panel.current is not None and not panel.pending)
    assert str(root) in panel.details.toPlainText()
    assert 'return 1' in panel.details.toPlainText()
    panel.objective.setText('Different objective');panel.start()
    assert 'Form changed' in panel.notice.text() and not runtime.coder.busy
    panel.objective.setText(item['objective'])
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.No)
    panel.start();assert not runtime.coder.busy
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.Yes)
    panel.start()
    # The real broker performs several isolated disk/SQLite operations; allow
    # for Windows sandbox filesystem latency rather than a two-second UI limit.
    from PySide6.QtTest import QTest
    for _ in range(400):
        QTest.qWait(25)
        if not runtime.coder.busy:break
    assert not runtime.coder.busy
    until(lambda:not panel.pending)
    panel.refresh();until(lambda:not panel.pending and panel.current['status']=='ready_for_review')
    assert '+    return 2' in panel.diff.toPlainText()
    assert 'No generated code or tests were executed' in panel.proposal.toPlainText()
    panel.note.setText('Inspected the proposal against criteria');panel.accept()
    until(lambda:not panel.pending and panel.current['status']=='accepted')
    assert 'return 1' in (root/'helper.py').read_text()
