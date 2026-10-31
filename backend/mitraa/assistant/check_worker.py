"""Explicitly approved local Python checks, with durable evidence per artifact."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy import select
from mitraa.db.models import CodingCheck,utcnow
from mitraa.responsibilities import jobs,service
from mitraa.security.sandbox import Sandbox
from mitraa.assistant.check_process import run_check
from mitraa.config import BACKEND_DIR


class CheckRecipe(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: str=Field(pattern='^(unittest|output)$')
    file: str
    expected_output: str=Field(default='',max_length=16000)
    timeout_seconds: int=Field(default=10,ge=1,le=30)

    @field_validator('file')
    @classmethod
    def python_file(cls,value):
        name=jobs.relative(value)
        if Path(name).suffix.lower()!='.py':raise ValueError('Choose a selected Python file.')
        return name


def digest(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def selected_files(item):
    contract=json.loads(item.contract_json);result=json.loads(item.result_json)
    proposed=result.get('files',{})
    if not proposed:raise ValueError('Generate a proposal before checking it.')
    folder=Path(result['artifact_folder'])
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (folder,*folder.parents)):
        raise ValueError('Artifact folder changed.')
    for name,text in proposed.items():
        if jobs.resolve_file(folder.resolve(),name).read_bytes()!=text.encode('utf-8'):
            raise ValueError('Artifact changed. Prepare a fresh proposal before running checks.')
    verified=jobs.verify(contract,{'files':proposed})
    if any(not check['passed'] for check in verified['checks']):raise ValueError('Fix syntax errors before running checks.')
    files={name:text for name,text in contract['snapshot'].items() if text is not None}
    files.update(proposed)
    return contract,proposed,files


def history(session,jid):
    return [dict(id=check.id,status=check.status,recipe=json.loads(check.recipe_json),
        artifact_hash=check.artifact_hash,context_hash=check.context_hash,
        created_at=service.stamp(check.created_at),finished_at=service.stamp(check.finished_at),
        report=json.loads(check.report_json)) for check in session.scalars(select(CodingCheck).where(
            CodingCheck.job_id==jid).order_by(CodingCheck.created_at.desc(),CodingCheck.id.desc()))]


def require_passing_checks(session,item):
    seen=set()
    result=json.loads(item.result_json)
    contract=json.loads(item.contract_json)
    context={name:text for name,text in contract['snapshot'].items() if text is not None}
    context.update(result.get('files',{}))
    for check in history(session,item.id):
        key=(check['recipe']['kind'],check['recipe']['file'])
        if key in seen:continue
        seen.add(key)
        if check['artifact_hash']!=digest(result.get('files',{})) or check['context_hash']!=digest(context):
            raise ValueError('Check evidence is stale. Run checks for the current proposal.')
        if check['status']!='passed':
            raise ValueError('An approved check did not pass. Inspect the results and rerun or prepare a corrected job.')


class CheckWorker:
    def __init__(self,post,factory=None,settings=None):
        self.post=post;self.factory=factory;self.settings=settings
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mitraa-check')
        self.lock=threading.Lock();self.busy=False;self.closed=False;self.cancelled=threading.Event();self.job_id=None

    def start(self,jid,version,recipe,confirmed=False):
        if not confirmed:raise ValueError('Approve local code execution before running a check.')
        recipe=CheckRecipe.model_validate(recipe)
        with self.lock:
            if self.closed or self.busy:raise ValueError('A check is already running or the worker is closing.')
            self.busy=True;self.job_id=jid;self.cancelled.clear()
        self.pool.submit(self.run,jid,version,recipe)

    def cancel(self,jid):
        with self.lock:
            if self.job_id==jid:self.cancelled.set()

    def run(self,jid,version,recipe):
        check_id=None;error=''
        try:
            if self.factory is None:
                from mitraa.db.session import default_session_factory
                self.factory=default_session_factory()
            from mitraa.config import get_settings
            settings=self.settings or get_settings()
            with self.factory() as session:
                item=jobs.row(session,jid)
                if item.version!=version or item.status not in {'ready_for_review','accepted'}:
                    raise ValueError('Reload a ready proposal before running checks.')
                if service.get(session,item.responsibility_id).status in service.TERMINAL:
                    raise ValueError('Reopen the responsibility before running checks.')
                contract,proposed,files=selected_files(item)
                Sandbox(settings.allowed_roots).resolve(contract['workspace'])
                if recipe.file not in files:raise ValueError('Choose a Python file included in the selected context or proposal.')
                check=CodingCheck(job_id=jid,artifact_hash=digest(proposed),context_hash=digest(files),
                    recipe_json=recipe.model_dump_json())
                session.add(check);session.flush();check_id=check.id
                jobs.transition(session,jid,version,{item.status},'checking');session.commit()
            self.post('job_changed',{'id':jid},'')
            storage=BACKEND_DIR/'jobs'
            if storage.is_symlink() or getattr(storage,'is_junction',lambda:False)():
                raise ValueError('Check storage must not be a link.')
            storage.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='check-',dir=storage) as temporary:
                root=Path(temporary)
                for name,text in files.items():
                    path=jobs.resolve_file(root,name);path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(text.encode('utf-8'))
                if self.cancelled.is_set():report=dict(status='cancelled',stdout='',stderr='',exit_code=None)
                else:report=run_check(root,recipe.model_dump(),self.cancelled)
                if self.cancelled.is_set():report['status']='cancelled'
                changed=[]
                for name,text in files.items():
                    try:
                        if jobs.resolve_file(root,name).read_bytes()!=text.encode('utf-8'):changed.append(name)
                    except (OSError,ValueError):changed.append(name)
                report['modified_selected_files']=changed
                if changed and report['status']=='passed':report['status']='failed'
            self.finish(jid,check_id,report)
        except Exception as exc:
            error=str(exc) if isinstance(exc,ValueError) else 'The check could not finish. Inspect the check result and retry.'
            if check_id:self.finish(jid,check_id,dict(status='error',notice=error,error_type=type(exc).__name__,stdout='',stderr='',exit_code=None))
        finally:
            with self.lock:self.busy=False;self.job_id=None
            if not self.closed:self.post('job_check_finished',{'id':jid},error)

    def finish(self,jid,check_id,report):
        with self.factory() as session:
            check=session.get(CodingCheck,check_id)
            if check is None or check.status!='running':return
            item=jobs.row(session,jid)
            if item.status!='checking':report={**report,'status':'cancelled','notice':'Job was cancelled or interrupted. Results were not accepted.'}
            check.status=report['status'];check.report_json=json.dumps(report);check.finished_at=utcnow()
            if item.status=='checking':jobs.transition(session,jid,item.version,{'checking'},'ready_for_review')
            service.event(session,item.responsibility_id,'coding_check_finished',job_id=jid,check_id=check_id,status=check.status)
            session.commit()

    def shutdown(self):
        self.closed=True;self.cancelled.set();self.pool.shutdown(wait=False,cancel_futures=False)
