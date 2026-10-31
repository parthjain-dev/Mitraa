"""Bounded coding proposals: selected text in, validated isolated text out. No shell."""
import ast
import difflib
import hashlib
import json
from pathlib import Path,PurePosixPath
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,update
from mitraa.config import BACKEND_DIR
from mitraa.db.models import CodingJob,FileAction,utcnow
from mitraa.responsibilities import service
from mitraa.security.sandbox import Sandbox,SandboxViolation

SUFFIXES={'.py','.md','.txt','.json','.js','.ts','.css','.html'}
MAX_BYTES=24000


class JobCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    responsibility_id: str
    objective: str=Field(min_length=1,max_length=3000)
    acceptance_criteria: str=Field(min_length=1,max_length=3000)
    workspace: str
    source_files: list[str]=Field(default_factory=list,max_length=8)
    output_files: list[str]=Field(min_length=1,max_length=8)
    max_output_tokens: int=Field(default=2048,ge=256,le=4096)
    timeout_seconds: int=Field(default=60,ge=10,le=120)
    output_names_explicit: bool=False


def relative(value):
    if '\\' in value or ':' in value or '\x00' in value: raise ValueError('Use plain relative paths with forward slashes.')
    path=PurePosixPath(value)
    if not value or path.is_absolute() or any(p in {'.','..'} for p in value.split('/')):
        raise ValueError('Paths must stay inside the selected workspace.')
    if path.suffix.lower() not in SUFFIXES or any(p.startswith('.') or
        any(word in p.lower() for word in ('secret','credential','token','password')) for p in path.parts):
        raise ValueError('Select supported source text, not credentials, hidden files or executables.')
    return path.as_posix()


def resolve_file(root,name):
    path=root
    for part in PurePosixPath(relative(name)).parts:
        path=path/part
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)(): raise ValueError('Links and junctions are not allowed in coding selections.')
    if not path.resolve().is_relative_to(root): raise ValueError('File escapes the workspace.')
    return path


def read_text(path,max_bytes=MAX_BYTES):
    if not path.exists(): return None
    if not path.is_file(): raise ValueError('Select text files, not folders.')
    with path.open('rb') as stream: raw=stream.read(max_bytes+1)
    if len(raw)>max_bytes or b'\x00' in raw: raise ValueError('Selected text is too large or binary.')
    try: return raw.decode('utf-8')
    except UnicodeDecodeError: raise ValueError('Selected files must be UTF-8 text.') from None


def row(session,jid):
    item=session.get(CodingJob,jid)
    if item is None: raise service.NotFound('Coding job not found.')
    session.refresh(item); return item


def as_dict(item,content=True):
    contract=json.loads(item.contract_json)
    result=json.loads(item.result_json)
    if content:
        from sqlalchemy.orm import object_session
        from mitraa.assistant.check_worker import history
        session=object_session(item)
        if session is not None:
            result['test_runs']=history(session,item.id)
            if result['test_runs']:result['verification']='Approved local check evidence is listed in test_runs. Passing checks do not prove every acceptance criterion.'
    if not content: contract={**contract,'snapshot':{k:'[selected text]' for k in contract['snapshot']}}
    return dict(id=item.id,responsibility_id=item.responsibility_id,status=item.status,version=item.version,
        objective=item.objective,acceptance_criteria=item.criteria,contract=contract,result=result,
        created_at=service.stamp(item.created_at),updated_at=service.stamp(item.updated_at))


def create(session,data,settings):
    owner=service.get(session,data.responsibility_id)
    if owner.status in service.TERMINAL: raise ValueError('Reopen the responsibility first.')
    try: root=Sandbox(settings.allowed_roots).resolve(data.workspace)
    except SandboxViolation as exc: raise ValueError(str(exc)) from None
    if not root.is_dir(): raise ValueError('Workspace must be an existing permitted folder.')
    inputs=list(dict.fromkeys(relative(n.strip()) for n in data.source_files))
    outputs=list(dict.fromkeys(relative(n.strip()) for n in data.output_files))
    redirects={}
    if not data.output_names_explicit:
        for name in set(inputs+outputs):
            source=resolve_file(root,name)
            target=None
            record=session.scalars(select(FileAction).where(FileAction.action=='write_text_file',
                FileAction.src==str(source),FileAction.undone.is_(False)).order_by(FileAction.id.desc()).limit(1)).first()
            if record: target=Path(record.dst)
            if target is None:
                for previous in session.scalars(select(CodingJob).where(CodingJob.status=='applied').order_by(CodingJob.updated_at.desc())):
                    old_contract=json.loads(previous.contract_json)
                    if old_contract['workspace']!=str(root):continue
                    old_result=json.loads(previous.result_json)
                    saved={**old_result.get('saved_files',{}),**old_result.get('working_copies',{})}
                    if name in saved:target=Path(saved[name]);break
            if target is not None and target.parent==source.parent and target.exists():
                redirects[name]=relative(target.relative_to(root).as_posix())
        inputs=list(dict.fromkeys(redirects.get(name,name) for name in inputs))
        outputs=list(dict.fromkeys(redirects.get(name,name) for name in outputs))
    snapshot={}
    for name in dict.fromkeys(inputs+outputs):
        text=read_text(resolve_file(root,name))
        if name in inputs and text is None: raise ValueError('A selected source file no longer exists.')
        snapshot[name]=text
    if sum(len((text or '').encode('utf-8')) for text in snapshot.values())>MAX_BYTES:
        raise ValueError('Selected context exceeds 24 KB. Choose fewer files.')
    endpoint=settings.nebius_base_url
    parsed=urlsplit(endpoint)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Configure a valid AI endpoint first.')
    if parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1','::1'}):
        raise ValueError('Provider must use HTTPS or loopback HTTP.')
    if not settings.nemotron_model: raise ValueError('Configure the AI model first.')
    targets={name:(name if data.output_names_explicit or name in redirects.values() or snapshot[name] is None or Path(name).stem.lower().endswith('_bymitraa')
        else str(PurePosixPath(name).with_name(Path(name).stem+'_byMitraa'+Path(name).suffix))) for name in outputs}
    if len({name.lower() for name in targets.values()})!=len(targets): raise ValueError('Output destinations overlap.')
    for name,target in targets.items():
        if target!=name and resolve_file(root,target).exists():
            raise ValueError('The working-copy name already exists. Select that file explicitly or choose a different output name.')
    apply_snapshot={target:read_text(resolve_file(root,target),64000) for target in targets.values()}
    contract=dict(workspace=str(root),source_files=inputs,output_files=outputs,snapshot=snapshot,
        apply_targets=targets,apply_snapshot=apply_snapshot,output_names_explicit=data.output_names_explicit,
        provider=parsed.hostname,endpoint=endpoint,model=settings.nemotron_model,
        max_output_tokens=data.max_output_tokens,timeout_seconds=data.timeout_seconds,max_calls=1,
        execution='No commands, imports, package installation, browsing or original-workspace writes')
    item=CodingJob(responsibility_id=owner.id,objective=data.objective.strip(),criteria=data.acceptance_criteria.strip(),
        contract_json=json.dumps(contract))
    if not item.objective or not item.criteria: raise ValueError('Enter an objective and acceptance criteria.')
    session.add(item); session.flush()
    service.event(session,owner.id,'coding_prepared',job_id=item.id)
    return as_dict(item)


def list_jobs(session,rid):
    service.get(session,rid)
    return [as_dict(item,False) for item in session.scalars(select(CodingJob).where(
        CodingJob.responsibility_id==rid).order_by(CodingJob.created_at.desc()))]


def transition(session,jid,version,allowed,status,result=None):
    values=dict(status=status,version=version+1,updated_at=utcnow())
    if result is not None: values['result_json']=json.dumps(result)
    changed=session.execute(update(CodingJob).where(CodingJob.id==jid,CodingJob.version==version,
        CodingJob.status.in_(allowed)).values(**values),execution_options={'synchronize_session':False})
    if changed.rowcount!=1: raise service.Conflict('Job changed. Reload before acting.')
    item=row(session,jid)
    service.event(session,item.responsibility_id,'coding_'+status,job_id=jid,version=item.version)
    return as_dict(item)


def cancel(session,jid,version):
    return transition(session,jid,version,{'prepared','running','checking','ready_for_review','verification_failed'},'cancelled')


def recover(session):
    session.execute(update(CodingJob).where(CodingJob.status=='running').values(status='interrupted',
        version=CodingJob.version+1,updated_at=utcnow(),result_json=json.dumps({'notice':'Interrupted by restart. Not retried automatically.'})))
    from mitraa.db.models import CodingCheck
    session.execute(update(CodingCheck).where(CodingCheck.status=='running').values(status='interrupted',finished_at=utcnow(),
        report_json=json.dumps({'notice':'Interrupted by restart. Run again with approval.'})))
    session.execute(update(CodingJob).where(CodingJob.status=='checking').values(status='ready_for_review',
        version=CodingJob.version+1,updated_at=utcnow()))


def accept(session,jid,version,note,confirmed):
    item=row(session,jid)
    if service.get(session,item.responsibility_id).status in service.TERMINAL:
        raise ValueError('Reopen the responsibility before reviewing coding work.')
    if not confirmed or not note.strip(): raise ValueError('Explicit review confirmation and a note are required.')
    from mitraa.assistant.check_worker import require_passing_checks
    require_passing_checks(session,item)
    result=json.loads(item.result_json)
    if result.get('missing_facts'): raise ValueError('Resolve missing facts in a new job before accepting.')
    if item.status=='ready_for_review':
        folder=Path(result['artifact_folder'])
        if folder.is_symlink() or getattr(folder,'is_junction',lambda:False)(): raise ValueError('Artifact folder changed.')
        folder=folder.resolve()
        for name,text in result['files'].items():
            path=resolve_file(folder,name)
            with path.open('rb') as stream: raw=stream.read(64001)
            if raw!=text.encode(): raise ValueError('An isolated artifact changed after verification. Prepare a new job.')
    return transition(session,jid,version,{'ready_for_review'},'accepted',dict(result,review_note=note.strip()))


def apply_to_workspace(session,jid,version,confirmed,settings):
    """Explicit local integration. A durable journal permits retry after partial writes."""
    import os
    import re
    import tempfile
    item=row(session,jid)
    if not confirmed: raise ValueError('Confirm replacing the reviewed files first.')
    if item.version!=version or item.status!='accepted':
        raise service.Conflict('Accept the review and reload before applying changes.')
    from mitraa.assistant.check_worker import require_passing_checks
    require_passing_checks(session,item)
    if service.get(session,item.responsibility_id).status in service.TERMINAL:
        raise ValueError('Reopen the responsibility before applying changes.')
    if not re.fullmatch('[a-f0-9]{32}',jid): raise ValueError('Invalid job identifier.')
    contract=json.loads(item.contract_json); result=json.loads(item.result_json)
    root=Path(contract['workspace'])
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (root,*root.parents)):
        raise ValueError('Workspace links and junctions are not allowed.')
    root=Sandbox(settings.allowed_roots).resolve(str(root))
    if not root.is_dir(): raise ValueError('Original workspace no longer exists.')
    folder=Path(result['artifact_folder'])
    if folder.is_symlink() or getattr(folder,'is_junction',lambda:False)(): raise ValueError('Artifact folder changed.')
    files=result['files']
    checked=verify(contract,{'files':files,'missing_facts':result.get('missing_facts',[])})
    if checked['missing_facts'] or any(not c['passed'] for c in checked['checks']):
        raise ValueError('Resolve failed checks and missing facts before applying.')
    for name,text in files.items():
        if resolve_file(folder.resolve(),name).read_bytes()!=text.encode('utf-8'):
            raise ValueError('Reviewed artifact changed. Prepare a new job.')
    journal=folder/'apply-journal.json'
    if journal.is_symlink(): raise ValueError('Apply journal must not be a link.')
    # Older contracts retain their reviewed destinations; prepare a new contract
    # to use the new copy policy, rather than silently changing an approval.
    targets=contract.get('apply_targets',{name:name for name in files})
    destination_files={targets[name]:text for name,text in files.items()}
    destination_snapshot=contract.get('apply_snapshot',contract['snapshot'])
    expected={'workspace':str(root),'files':destination_files,'snapshot':contract['snapshot']}
    resuming=journal.exists()
    if resuming and json.loads(journal.read_text(encoding='utf-8'))!=expected:
        raise ValueError('Apply journal changed. Inspect the files manually.')
    paths={}; backups={}
    # Check every selected input as well as outputs before modifying anything.
    for name,before in contract['snapshot'].items():
        path=resolve_file(root,name); current=read_text(path,64000)
        if current!=before and not(resuming and name in destination_files and current==destination_files[name]):
            raise ValueError('Workspace file changed since preparation: '+name+'. Prepare a new job.')
    for name,text in destination_files.items():
        path=resolve_file(root,name)
        current=read_text(path,64000);before=destination_snapshot[name]
        if current!=before and not(resuming and current==text):
            raise ValueError('Working copy changed since preparation: '+name+'. Prepare a new job.')
        if not path.parent.is_dir(): raise ValueError('Output parent folder must already exist: '+name)
        backup=path.with_name(path.name+'.mitraa-'+jid+'.bak')
        if backup.is_symlink() or getattr(backup,'is_junction',lambda:False)(): raise ValueError('Backup path is a link.')
        if backup.exists() and (not resuming or before is None or backup.read_bytes()!=before.encode('utf-8')):
            raise ValueError('Backup already exists or changed: '+str(backup))
        paths[name]=path
        if before is not None: backups[name]=str(backup)
    # Claim the DB version before writes. The journal/backups remain if a crash rolls it back.
    saved_files={name:str(root/targets[name]) for name in files}
    working_copies=dict(saved_files)
    if len(contract['source_files'])==1 and len(files)==1:
        working_copies[contract['source_files'][0]]=next(iter(saved_files.values()))
    applied=transition(session,jid,version,{'accepted'},'applied',dict(result,applied_workspace=str(root),backups=backups,
        saved_files=saved_files,working_copies=working_copies))
    if not resuming:
        with journal.open('x',encoding='utf-8') as stream:
            json.dump(expected,stream); stream.flush(); os.fsync(stream.fileno())
    for name,path in paths.items():
        before=destination_snapshot[name]; text=destination_files[name]
        current=read_text(resolve_file(root,name),64000)
        if current!=before and not(resuming and current==text):
            raise ValueError('Workspace changed during apply: '+name)
        if before is not None:
            backup=Path(backups[name])
            if not backup.exists():
                with backup.open('xb') as stream:
                    stream.write(before.encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
        if current==text: continue
        fd,temp=tempfile.mkstemp(prefix='.mitraa-',suffix='.tmp',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(text.encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
            if read_text(resolve_file(root,name),64000)!=current: raise ValueError('Workspace changed during apply: '+name)
            os.replace(temp,path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return applied


def verify(contract,proposal):
    if not isinstance(proposal,dict) or set(proposal)-{'files','summary','missing_facts'}:
        raise ValueError('Worker returned an invalid proposal.')
    files=proposal.get('files')
    if not isinstance(files,dict) or not files or len(files)>8: raise ValueError('Worker must return 1–8 proposed files.')
    if set(files)-set(contract['output_files']): raise ValueError('Worker proposed a path outside the approved outputs.')
    missing=proposal.get('missing_facts',[])
    if not isinstance(missing,list) or len(missing)>30 or any(not isinstance(x,str) or len(x)>1000 for x in missing):
        raise ValueError('Invalid missing-fact questions.')
    if any(not isinstance(v,str) or '\x00' in v for v in files.values()): raise ValueError('Worker output must be plain text.')
    if sum(len(v.encode()) for v in files.values())>64000: raise ValueError('Proposed files exceed 64 KB.')
    checks=[]; diffs={}
    for name,text in files.items():
        relative(name)
        error=''
        try:
            if name.endswith('.py'): ast.parse(text,filename=name)
            elif name.endswith('.json'): json.loads(text)
            else: continue
        except (SyntaxError,ValueError) as exc: error=type(exc).__name__
        checks.append(dict(file=name,check='Static syntax only',passed=not error,error=error))
    for name,text in files.items():
        diffs[name]='\n'.join(difflib.unified_diff((contract['snapshot'].get(name) or '').splitlines(),text.splitlines(),
            fromfile='Original/'+name,tofile='Proposed/'+name,lineterm=''))
    artifact_hash=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    return dict(files=files,diffs=diffs,checks=checks,artifact_hash=artifact_hash,missing_facts=missing,
        summary=str(proposal.get('summary',''))[:3000],verification='No generated code or tests were executed. Check acceptance criteria manually.')


def materialize(jid,result,base=None):
    import re
    if not re.fullmatch('[a-f0-9]{32}',jid): raise ValueError('Invalid isolated job identifier.')
    storage=base or BACKEND_DIR/'jobs'
    if storage.is_symlink() or getattr(storage,'is_junction',lambda:False)(): raise ValueError('Job storage must not be a link.')
    root=storage.resolve()
    root.mkdir(exist_ok=True)
    folder=root/jid
    if folder.exists(): raise ValueError('Job artifact folder already exists; refusing to overwrite.')
    folder.mkdir()
    for name,text in result['files'].items():
        path=resolve_file(folder,name); path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8',newline='') as output: output.write(text)
    result['artifact_folder']=str(folder)
    return result
