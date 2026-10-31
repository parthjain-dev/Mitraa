import json
from pathlib import Path
import threading
import pytest
from mitraa.assistant.check_process import run_check
from mitraa.assistant.check_worker import CheckRecipe,CheckWorker,history,digest
from mitraa.db.models import CodingCheck
from mitraa.responsibilities import jobs,service
from tests.test_coding_jobs import prepared,Adapter


def ready(session,settings,roots,tmp_path,tests=None):
    item,root,_=prepared(session,settings,roots)
    contract=item['contract']
    if tests is not None:
        contract['snapshot']['test_value.py']=tests
        contract['source_files'].append('test_value.py')
        jobs.row(session,item['id']).contract_json=json.dumps(contract);session.flush()
    result=jobs.materialize(item['id'],jobs.verify(contract,Adapter().coding_proposal()),tmp_path/'artifacts')
    item=jobs.transition(session,item['id'],1,{'prepared'},'ready_for_review',result);session.commit()
    return item,root


def test_unit_tests_use_proposal_and_persist_evidence(session,session_factory,settings,roots,tmp_path):
    tests='import unittest\nfrom helper import value\nclass TestValue(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value(), 2)\n'
    item,root=ready(session,settings,roots,tmp_path,tests)
    worker=CheckWorker(lambda *args:None,session_factory,settings)
    worker.run(item['id'],item['version'],CheckRecipe(kind='unittest',file='test_value.py'))
    with session_factory() as s:
        check=history(s,item['id'])[0]
        assert check['status']=='passed',check
        assert 'Ran 1 test' in check['report']['stderr']
        current=jobs.as_dict(jobs.row(s,item['id']))
        assert current['status']=='ready_for_review' and current['result']['test_runs'][0]['finished_at']
        assert 'return 1' in (root/'helper.py').read_text()
        row=jobs.row(s,item['id']);original_contract=row.contract_json
        changed=json.loads(original_contract);changed['snapshot']['test_value.py']+='\n# changed context\n'
        row.contract_json=json.dumps(changed);s.flush()
        with pytest.raises(ValueError,match='stale'):jobs.accept(s,item['id'],current['version'],'Inspect',True)
        row.contract_json=original_contract;s.flush()
        assert jobs.accept(s,item['id'],current['version'],'Inspected tests',True)['status']=='accepted'
    worker.shutdown()


def test_failure_blocks_acceptance_until_successful_rerun(session,session_factory,settings,roots,tmp_path):
    item,_=ready(session,settings,roots,tmp_path)
    worker=CheckWorker(lambda *args:None,session_factory,settings)
    recipe=CheckRecipe(kind='output',file='helper.py',expected_output='not printed')
    worker.run(item['id'],item['version'],recipe)
    with session_factory() as s:
        current=jobs.row(s,item['id']);version=current.version
        assert history(s,item['id'])[0]['status']=='failed'
        with pytest.raises(ValueError,match='did not pass'):jobs.accept(s,item['id'],version,'Review',True)
    recipe.expected_output=''
    worker.run(item['id'],version,recipe)
    with session_factory() as s:
        current=jobs.row(s,item['id'])
        assert history(s,item['id'])[0]['status']=='passed'
        assert jobs.accept(s,item['id'],current.version,'Checked',True)['status']=='accepted'
    worker.shutdown()


@pytest.mark.parametrize('kind,code,expected,status',[
    ('output','print("hello")\n','hello','passed'),
    ('unittest','x = 1\n','','failed'),
    ('output','while True: pass\n','','timed_out'),
    ('output','print("x" * 100000)\n','','output_limit'),
    ('unittest','raise SystemExit(0)\n','','failed'),
])
def test_real_process_limits(tmp_path,kind,code,expected,status):
    (tmp_path/'check.py').write_text(code)
    report=run_check(tmp_path,dict(kind=kind,file='check.py',expected_output=expected,timeout_seconds=1),threading.Event())
    assert report['status']==status,report
    assert len(report['stdout'].encode())<=32768


def test_stop_terminates_process_and_environment_is_filtered(tmp_path,monkeypatch):
    monkeypatch.setenv('MITRAA_TEST_PRIVATE_VALUE','not-for-child')
    path=tmp_path/'check.py';path.write_text('import os\nprint(os.environ.get("MITRAA_TEST_PRIVATE_VALUE", "absent"))\n')
    recipe=dict(kind='output',file='check.py',expected_output='absent',timeout_seconds=3)
    assert run_check(tmp_path,recipe,threading.Event())['status']=='passed'
    # A new copy for each execution, as used by the worker.
    other=tmp_path/'second';other.mkdir();(other/'check.py').write_text('while True: pass\n')
    event=threading.Event();timer=threading.Timer(.2,event.set);timer.start()
    try:assert run_check(other,recipe,event)['status']=='cancelled'
    finally:timer.cancel()


def test_subprocess_and_memory_limits_are_enforced(tmp_path):
    code=('import subprocess, sys\n'
        'try:\n    subprocess.run([sys.executable, "-c", "pass"], check=True)\n'
        'except OSError:\n    print("child blocked")\n'
        'try:\n    data = bytearray(1024 * 1024 * 1024)\n'
        'except MemoryError:\n    print("memory bounded")\n')
    (tmp_path/'check.py').write_text(code)
    report=run_check(tmp_path,dict(kind='output',file='check.py',expected_output='child blocked\nmemory bounded',timeout_seconds=5),threading.Event())
    assert report['status']=='passed',report


def test_approval_single_worker_and_selection_validation(session,session_factory,settings,roots,tmp_path):
    item,_=ready(session,settings,roots,tmp_path)
    worker=CheckWorker(lambda *args:None,session_factory,settings)
    recipe=dict(kind='output',file='helper.py')
    with pytest.raises(ValueError):worker.start(item['id'],item['version'],recipe)
    worker.busy=True
    with pytest.raises(ValueError):worker.start(item['id'],item['version'],recipe,True)
    worker.busy=False
    worker.run(item['id'],item['version'],CheckRecipe(kind='output',file='unselected.py'))
    with session_factory() as s:assert not history(s,item['id'])
    worker.shutdown()


def test_restart_preserves_artifacts_and_invalidates_running_check(session,settings,roots,tmp_path):
    item,_=ready(session,settings,roots,tmp_path)
    session.add(CodingCheck(job_id=item['id'],artifact_hash=digest(item['result']['files']),context_hash='x',recipe_json='{}'))
    jobs.transition(session,item['id'],item['version'],{'ready_for_review'},'checking');session.commit()
    jobs.recover(session);session.commit()
    current=jobs.as_dict(jobs.row(session,item['id']))
    assert current['status']=='ready_for_review' and current['result']['artifact_folder']
    assert history(session,item['id'])[0]['status']=='interrupted'
    check_id=history(session,item['id'])[0]['id']
    owner=service.get(session,item['responsibility_id'])
    service.forget(session,owner.id,owner.version);session.commit()
    assert session.get(CodingCheck,check_id) is None


def test_modified_test_copy_does_not_pass(session,session_factory,settings,roots,tmp_path):
    tests='from pathlib import Path\nPath("helper.py").write_text("changed")\n'
    item,root=ready(session,settings,roots,tmp_path,tests)
    worker=CheckWorker(lambda *args:None,session_factory,settings)
    worker.run(item['id'],item['version'],CheckRecipe(kind='output',file='test_value.py'))
    with session_factory() as s:
        check=history(s,item['id'])[0]
        assert check['status']=='failed' and check['report']['modified_selected_files']==['helper.py']
    assert 'return 1' in (root/'helper.py').read_text()
    worker.shutdown()
