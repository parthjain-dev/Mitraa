"""One bounded coding job at a time. No subprocesses or generated code execution."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from mitraa.responsibilities import jobs
from mitraa.db.models import ModelUsage
from mitraa.usage import events


class CodingWorker:
    def __init__(self,post,factory=None,settings=None,adapter=None,artifact_base=None):
        self.post=post; self.factory=factory; self.settings=settings; self.adapter=adapter
        self.artifact_base=artifact_base; self.lock=threading.Lock(); self.busy=False; self.closed=False
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mitraa-coding')

    def start(self,jid,version,confirmed=False):
        if not confirmed: raise ValueError('Review the provider and selected file contract before starting.')
        with self.lock:
            if self.busy or self.closed: raise ValueError('A coding job is already running or the worker is closing.')
            self.busy=True
        self.pool.submit(self.run,jid,version)

    def run(self,jid,version):
        collected=[]; token=events.set(collected)
        try:
            if self.factory is None:
                from mitraa.db.session import default_session_factory
                self.factory=default_session_factory()
            from mitraa.config import get_settings
            settings=self.settings or get_settings()
            with self.factory() as session:
                item=jobs.row(session,jid); contract=jobs.as_dict(item)['contract']
                if jobs.service.get(session,item.responsibility_id).status in jobs.service.TERMINAL:
                    raise ValueError('Responsibility is closed. Reopen it and prepare a new contract.')
                if settings.nebius_base_url!=contract['endpoint'] or settings.nemotron_model!=contract['model']:
                    raise ValueError('AI configuration changed. Prepare a new job and review its provider.')
                # Revalidate selected snapshots immediately before transmission.
                from mitraa.security.sandbox import Sandbox
                root=Sandbox(settings.allowed_roots).resolve(contract['workspace'])
                for name,text in contract['snapshot'].items():
                    if jobs.read_text(jobs.resolve_file(root,name))!=text:
                        raise ValueError('Selected source/output files changed. Prepare a fresh job.')
                objective=item.objective; criteria=item.criteria
                jobs.transition(session,jid,version,{'prepared'},'running'); session.commit()
            self.post('job_changed',{'id':jid},'')
            if self.adapter is None:
                from mitraa.agent.llm import NemotronClient
                adapter=NemotronClient(settings)
            else: adapter=self.adapter
            started=time.monotonic()
            proposal=adapter.coding_proposal(contract,objective,criteria)
            if time.monotonic()-started>contract['timeout_seconds']:
                raise ValueError('Time budget exceeded. Late proposal discarded; no original files changed.')
            result=jobs.verify(contract,proposal)
            with self.factory() as session:
                item=jobs.row(session,jid)
                if item.status!='running' or self.closed: return
                result=jobs.materialize(jid,result,self.artifact_base)
                status='ready_for_review' if all(c['passed'] for c in result['checks']) else 'verification_failed'
                jobs.transition(session,jid,item.version,{'running'},status,result); session.commit()
        except Exception as exc:
            # No raw provider errors/prompts/keys in persistent diagnostic text.
            message=str(exc) if isinstance(exc,ValueError) else 'Coding job failed. Narrow the objective or check the provider connection.'
            if self.factory:
                with self.factory() as session:
                    item=jobs.row(session,jid)
                    if item.status in {'prepared','running'}:
                        jobs.transition(session,jid,item.version,{item.status},'failed',{'notice':message}); session.commit()
        finally:
            events.reset(token)
            try:
                if self.factory and collected:
                    with self.factory() as session:
                        session.add_all(ModelUsage(request_id=jid,conversation_id=None,**event) for event in collected)
                        session.commit()
            finally:
                with self.lock: self.busy=False
            if not self.closed: self.post('job_changed',{'id':jid},'')

    def shutdown(self):
        self.closed=True
        # Requests already sent may finish remotely; their output is discarded.
        self.pool.shutdown(wait=False,cancel_futures=False)
