import json
from pathlib import Path
from unittest.mock import patch
import pytest
from mitraa.responsibilities import jobs
from tests.test_coding_jobs import prepared, Adapter


def accepted(session,settings,roots,tmp_path,new=False,exact=True):
    item,root,_=prepared(session,settings,roots)
    contract=item['contract']
    if exact:
        contract['apply_targets']={'helper.py':'helper.py'}
        contract['apply_snapshot']={'helper.py':contract['snapshot']['helper.py']}
    if new:
        contract['output_files'].append('new.py');contract['snapshot']['new.py']=None
        contract['apply_targets']['new.py']='new.py';contract['apply_snapshot']['new.py']=None
    row=jobs.row(session,item['id']);row.contract_json=json.dumps(contract);session.flush()
    proposal=Adapter().coding_proposal()
    if new:proposal['files']['new.py']='x = 2\n'
    result=jobs.materialize(item['id'],jobs.verify(contract,proposal),tmp_path/'artifacts')
    ready=jobs.transition(session,item['id'],1,{'prepared'},'ready_for_review',result)
    item=jobs.accept(session,item['id'],ready['version'],'Inspected diff',True);session.commit()
    return item,root


def test_default_copy_and_followup_contract(session,settings,roots,tmp_path):
    item,root=accepted(session,settings,roots,tmp_path,exact=False)
    applied=jobs.apply_to_workspace(session,item['id'],item['version'],True,settings);session.commit()
    assert 'return 1' in (root/'helper.py').read_text()
    assert 'return 2' in (root/'helper_byMitraa.py').read_text()
    assert not applied['result']['backups']
    next_job=jobs.create(session,jobs.JobCreate(responsibility_id=item['responsibility_id'],workspace=str(root),
        objective='Further update',acceptance_criteria='Review',source_files=['helper.py'],output_files=['helper.py']),settings)
    assert next_job['contract']['source_files']==['helper_byMitraa.py']
    assert next_job['contract']['output_files']==['helper_byMitraa.py']
    assert next_job['contract']['apply_targets']=={'helper_byMitraa.py':'helper_byMitraa.py'}
    proposal={'files':{'helper_byMitraa.py':'def value():\n    return 3\n'}}
    result=jobs.materialize(next_job['id'],jobs.verify(next_job['contract'],proposal),tmp_path/'artifacts')
    ready=jobs.transition(session,next_job['id'],1,{'prepared'},'ready_for_review',result)
    reviewed=jobs.accept(session,next_job['id'],ready['version'],'Checked follow-up',True)
    saved=jobs.apply_to_workspace(session,next_job['id'],reviewed['version'],True,settings);session.commit()
    assert 'return 3' in (root/'helper_byMitraa.py').read_text()
    assert 'return 1' in (root/'helper.py').read_text()
    assert 'return 2' in Path(saved['result']['backups']['helper_byMitraa.py']).read_text()


def test_custom_coding_name_is_reused(session,settings,roots,tmp_path):
    item,root,_=prepared(session,settings,roots)
    contract=item['contract'];contract['output_files']=['custom.py'];contract['snapshot']['custom.py']=None
    contract['apply_targets']={'custom.py':'custom.py'};contract['apply_snapshot']={'custom.py':None}
    contract['output_names_explicit']=True
    jobs.row(session,item['id']).contract_json=json.dumps(contract);session.flush()
    result=jobs.materialize(item['id'],jobs.verify(contract,{'files':{'custom.py':'print(2)\n'}}),tmp_path/'artifacts')
    ready=jobs.transition(session,item['id'],1,{'prepared'},'ready_for_review',result)
    reviewed=jobs.accept(session,item['id'],ready['version'],'Checked',True)
    jobs.apply_to_workspace(session,item['id'],reviewed['version'],True,settings);session.commit()
    next_job=jobs.create(session,jobs.JobCreate(responsibility_id=item['responsibility_id'],workspace=str(root),
        objective='Update again',acceptance_criteria='Review',source_files=['helper.py'],output_files=['helper.py']),settings)
    assert next_job['contract']['source_files']==['custom.py']
    assert next_job['contract']['apply_targets']=={'custom.py':'custom.py'}
    from mitraa.tools.text_files import known_edit
    from mitraa.security.sandbox import Sandbox
    from types import SimpleNamespace
    assert known_edit(root/'helper.py',SimpleNamespace(session=session,sandbox=Sandbox(settings.allowed_roots)))==root/'custom.py'


def test_apply_updates_original_and_preserves_backup(session,settings,roots,tmp_path):
    item,root=accepted(session,settings,roots,tmp_path,new=True)
    result=jobs.apply_to_workspace(session,item['id'],item['version'],True,settings);session.commit()
    assert result['status']=='applied'
    assert 'return 2' in (root/'helper.py').read_text()
    assert (root/'new.py').read_text()=='x = 2\n'
    assert 'return 1' in Path(result['result']['backups']['helper.py']).read_text()
    with pytest.raises(ValueError):jobs.apply_to_workspace(session,item['id'],result['version'],True,settings)


@pytest.mark.parametrize('change',['source','artifact','backup','permission','confirmation'])
def test_apply_rejects_unsafe_changes(session,settings,roots,tmp_path,change):
    item,root=accepted(session,settings,roots,tmp_path)
    if change=='source':(root/'helper.py').write_text('user changes')
    if change=='artifact':Path(item['result']['artifact_folder'],'helper.py').write_text('changed')
    if change=='backup':(root/('helper.py.mitraa-'+item['id']+'.bak')).write_text('existing backup')
    if change=='permission':settings.mitraa_allowed_roots=str(tmp_path/'elsewhere')
    with pytest.raises(Exception):jobs.apply_to_workspace(session,item['id'],item['version'],change!='confirmation',settings)
    assert (root/'helper.py').read_text()==('user changes' if change=='source' else 'def value():\n    return 1\n')
    session.rollback()


def test_interrupted_apply_can_resume_without_losing_backup(session,settings,roots,tmp_path):
    item,root=accepted(session,settings,roots,tmp_path,new=True)
    import os
    original=os.replace
    calls=[]
    def fail_second(src,dst):
        calls.append(dst)
        if len(calls)==2:raise OSError('simulated interruption')
        original(src,dst)
    with patch('os.replace',side_effect=fail_second):
        with pytest.raises(OSError):jobs.apply_to_workspace(session,item['id'],item['version'],True,settings)
    session.rollback()
    assert 'return 2' in (root/'helper.py').read_text()
    result=jobs.apply_to_workspace(session,item['id'],item['version'],True,settings);session.commit()
    assert result['status']=='applied' and (root/'new.py').exists()
    assert 'return 1' in Path(result['result']['backups']['helper.py']).read_text()
