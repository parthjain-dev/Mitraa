import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from mitraa.responsibilities import jobs,service
from mitraa.responsibilities.schemas import ResponsibilityCreate
from mitraa.assistant.coding_worker import CodingWorker


def prepared(session,settings,roots):
    settings.nebius_base_url='https://provider.example/v1';settings.nemotron_model='test';settings.nebius_api_key='secret'
    root=roots['Documents']/'project';root.mkdir(exist_ok=True)
    (root/'helper.py').write_text('def value():\n    return 1\n',encoding='utf-8')
    owner=service.create(session,ResponsibilityCreate(title='Small coding task'))
    data=jobs.JobCreate(responsibility_id=owner['id'],objective='Return 2',acceptance_criteria='Function returns 2',
        workspace=str(root),source_files=['helper.py'],output_files=['helper.py'])
    result=jobs.create(session,data,settings);session.commit()
    return result,root,data


class Adapter:
    def coding_proposal(self,*args):
        return dict(files={'helper.py':'def value():\n    return 2\n'},summary='Changed constant',missing_facts=[])


def test_isolated_coding_review_does_not_change_original(session,session_factory,settings,roots,tmp_path):
    item,root,_=prepared(session,settings,roots)
    worker=CodingWorker(lambda *args:None,session_factory,settings,Adapter(),tmp_path/'artifacts')
    worker.run(item['id'],1)
    with session_factory() as s:
        result=jobs.as_dict(jobs.row(s,item['id']))
        assert result['status']=='ready_for_review'
        assert result['result']['checks'][0]['passed']
        assert '+    return 2' in result['result']['diffs']['helper.py']
        assert (root/'helper.py').read_text()=='def value():\n    return 1\n'
        assert Path(result['result']['artifact_folder'],'helper.py').read_text()=='def value():\n    return 2\n'
        accepted=jobs.accept(s,item['id'],result['version'],'Inspected changed constant',True)
        assert accepted['status']=='accepted' and service.get(s,item['responsibility_id']).status=='captured'
        s.commit()
    worker.shutdown()


@pytest.mark.parametrize('name',['../escape.py','/escape.py','a/../../escape.py','a\\escape.py','.env','secrets.json','evil.exe'])
def test_disallowed_paths_rejected(name):
    with pytest.raises(ValueError):jobs.relative(name)


def test_worker_cannot_choose_extra_files_or_binary_text(session,settings,roots):
    item,_,_=prepared(session,settings,roots)
    with pytest.raises(ValueError):jobs.verify(item['contract'],{'files':{'other.py':'print(1)'}})
    with pytest.raises(ValueError):jobs.verify(item['contract'],{'files':{'helper.py':'\x00'}})
    result=jobs.verify(item['contract'],{'files':{'helper.py':'def broken('}})
    assert not result['checks'][0]['passed']


def test_cancelled_job_discards_late_result(session,session_factory,settings,roots,tmp_path):
    item,root,_=prepared(session,settings,roots)
    class CancelAdapter:
        def coding_proposal(self,*args):
            with session_factory() as s:
                current=jobs.row(s,item['id']);jobs.cancel(s,item['id'],current.version);s.commit()
            return Adapter().coding_proposal()
    worker=CodingWorker(lambda *args:None,session_factory,settings,CancelAdapter(),tmp_path/'artifacts')
    worker.run(item['id'],1)
    with session_factory() as s:assert jobs.row(s,item['id']).status=='cancelled'
    assert not (tmp_path/'artifacts'/item['id']).exists()
    assert 'return 1' in (root/'helper.py').read_text();worker.shutdown()


def test_restart_marks_running_interrupted_without_retry(session,settings,roots):
    item,_,_=prepared(session,settings,roots)
    jobs.transition(session,item['id'],1,{'prepared'},'running');session.commit()
    jobs.recover(session);session.commit()
    assert jobs.row(session,item['id']).status=='interrupted'


def test_approval_required_and_single_worker(session,session_factory,settings,roots,tmp_path):
    item,_,_=prepared(session,settings,roots)
    worker=CodingWorker(lambda *args:None,session_factory,settings,Adapter(),tmp_path/'artifacts')
    with pytest.raises(ValueError):worker.start(item['id'],1)
    worker.busy=True
    with pytest.raises(ValueError):worker.start(item['id'],1,True)
    worker.busy=False;worker.shutdown()


def test_source_change_and_provider_change_invalidate_contract(session,session_factory,settings,roots,tmp_path):
    item,root,_=prepared(session,settings,roots)
    (root/'helper.py').write_text('changed',encoding='utf-8')
    worker=CodingWorker(lambda *args:None,session_factory,settings,Adapter(),tmp_path/'artifacts')
    worker.run(item['id'],1)
    with session_factory() as s:
        current=jobs.as_dict(jobs.row(s,item['id']))
        assert current['status']=='failed' and 'changed' in current['result']['notice']
    worker.shutdown()


def test_modified_artifact_cannot_inherit_verification(session,session_factory,settings,roots,tmp_path):
    item,_,_=prepared(session,settings,roots)
    worker=CodingWorker(lambda *args:None,session_factory,settings,Adapter(),tmp_path/'artifacts')
    worker.run(item['id'],1)
    with session_factory() as s:
        current=jobs.as_dict(jobs.row(s,item['id']))
        Path(current['result']['artifact_folder'],'helper.py').write_text('modified',encoding='utf-8')
        with pytest.raises(ValueError,match='changed'):jobs.accept(s,item['id'],current['version'],'Checked',True)
    worker.shutdown()
