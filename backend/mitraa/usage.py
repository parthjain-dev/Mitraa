"""Provider-reported usage only. Never persist prompts, keys, or response content."""
from contextvars import ContextVar
from datetime import datetime,timezone
from functools import wraps
import logging
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from mitraa.db.models import ModelUsage

log=logging.getLogger(__name__)
events=ContextVar('mitraa_usage_events',default=None)


def report(event):
    collector=events.get()
    if collector is not None: collector.append(event)


def totals(rows):
    return dict(calls=len(rows),failed_calls=sum(r['status']=='failed' for r in rows),
        input_tokens=sum(r['input_tokens'] or 0 for r in rows),
        output_tokens=sum(r['output_tokens'] or 0 for r in rows),
        total_tokens=sum(r['total_tokens'] or 0 for r in rows),
        unreported_calls=sum(any(r[k] is None for k in ('input_tokens','output_tokens','total_tokens')) for r in rows))


def tracked(method):
    @wraps(method)
    def run(self,*args,**kwargs):
        collected=[]; token=events.set(collected); request_id=uuid.uuid4().hex
        result=None
        try:
            result=method(self,*args,**kwargs)
            return result
        except BaseException:
            self.session.rollback()
            raise
        finally:
            events.reset(token)
            if collected:
                try:
                    # Agent operations commit before returning; use a separate short
                    # transaction so later request rollback cannot erase usage.
                    with Session(bind=self.session.get_bind()) as session:
                        session.add_all(ModelUsage(request_id=request_id,
                            conversation_id=getattr(result,'conversation_id',None),**row) for row in collected)
                        session.commit()
                except Exception:
                    log.error('Could not persist model token usage.')
            if result is not None:
                result.usage=dict(request_id=request_id,**totals(collected))
    return run


def summary(session):
    rows=list(session.scalars(select(ModelUsage).order_by(ModelUsage.id)))
    data=[dict(provider=r.provider,model=r.model,status=r.status,input_tokens=r.input_tokens,
        output_tokens=r.output_tokens,total_tokens=r.total_tokens) for r in rows]
    today=datetime.now(timezone.utc).date()
    day=[d for r,d in zip(rows,data) if r.created_at.date()==today]
    grouped={}
    for row in data: grouped.setdefault((row['provider'],row['model']),[]).append(row)
    recent=[]
    for row in reversed(rows):
        if not recent or recent[-1]['request_id']!=row.request_id:
            if len(recent)==20: break
            recent.append(dict(request_id=row.request_id,created_at=row.created_at.replace(tzinfo=timezone.utc).isoformat(),rows=[]))
        recent[-1]['rows'].append(dict(status=row.status,input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,total_tokens=row.total_tokens))
    return dict(all_time=totals(data),today_utc=totals(day),
        first_recorded_at=rows[0].created_at.replace(tzinfo=timezone.utc).isoformat() if rows else None,
        by_model=[dict(provider=p,model=m,**totals(values)) for (p,m),values in grouped.items()],
        recent_requests=[dict(request_id=r['request_id'],created_at=r['created_at'],**totals(r['rows'])) for r in recent])
