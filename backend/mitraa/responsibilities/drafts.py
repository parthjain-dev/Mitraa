"""Versioned text preparation. No filesystem access or external submissions."""
import difflib
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update, delete
from mitraa.db.models import PreparedDraft, DraftRevision, utcnow
from mitraa.responsibilities import service


class DraftContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)
    sources: list[str] = Field(default_factory=list, max_length=50)
    missing_facts: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('title', 'content')
    @classmethod
    def text(cls, value):
        if not value.strip() or '\x00' in value: raise ValueError('Enter non-empty plain text without null characters.')
        return value

    @field_validator('sources', 'missing_facts')
    @classmethod
    def lines(cls, values):
        if any(not v.strip() or len(v)>2000 for v in values):
            raise ValueError('References and questions must contain 1–2000 characters.')
        return list(dict.fromkeys(v.strip() for v in values))


class DraftUpdate(DraftContent):
    expected_version: int = Field(ge=1)


class DraftReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    decision: Literal['accepted', 'changes_requested']
    note: str = Field(min_length=1, max_length=5000)
    confirmed: bool = False


def owner_open(session, rid):
    owner=service.get(session,rid)
    if owner.status in service.TERMINAL: raise ValueError('Reopen the responsibility before preparing or reviewing work.')
    return owner


def get_draft(session, draft_id):
    row=session.get(PreparedDraft,draft_id)
    if row is None: raise service.NotFound('Draft not found.')
    session.refresh(row)
    return row


def revision(session, row, version=None):
    result=session.scalar(select(DraftRevision).where(DraftRevision.draft_id==row.id,
        DraftRevision.version==(version or row.version)))
    if result is None: raise service.NotFound('Draft revision not found.')
    return result


def as_dict(row, rev):
    return dict(id=row.id,responsibility_id=row.responsibility_id,version=rev.version,
        title=rev.title,content=rev.content,**json.loads(rev.context_json),
        content_hash=rev.content_hash,review_status=rev.review_status,review_note=rev.review_note,
        reviewed_at=service.stamp(rev.reviewed_at),created_at=service.stamp(rev.created_at))


def detail(session, draft_id):
    row=get_draft(session,draft_id)
    versions=list(session.scalars(select(DraftRevision).where(DraftRevision.draft_id==row.id).order_by(DraftRevision.version)))
    current=as_dict(row,revision(session,row))
    before=versions[-2].content if len(versions)>1 else ''
    current['diff']='\n'.join(difflib.unified_diff(before.splitlines(),current['content'].splitlines(),
        fromfile='Previous revision',tofile='Current revision',lineterm=''))
    current['revisions']=[as_dict(row,r) for r in versions]
    return current


def list_drafts(session, rid):
    service.get(session,rid)
    return [as_dict(row,revision(session,row)) for row in session.scalars(select(PreparedDraft)
        .where(PreparedDraft.responsibility_id==rid).order_by(PreparedDraft.created_at.desc()))]


def add_revision(session, row, data, owner):
    unknown=set(data.sources)-set(json.loads(owner.sources_json))
    if unknown: raise ValueError('Add source references to the responsibility first. References are not proof their contents were read.')
    # Snapshot context so subsequent responsibility edits cannot rewrite provenance.
    context=dict(sources=data.sources,missing_facts=data.missing_facts,
        responsibility_version=owner.version,outcome=owner.outcome,notes=owner.notes)
    canonical=json.dumps(dict(title=data.title,content=data.content,context=context),sort_keys=True)
    rev=DraftRevision(draft_id=row.id,version=row.version,title=data.title,content=data.content,
        context_json=json.dumps(context),content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        review_status='pending')
    session.add(rev); session.flush()
    service.event(session,owner.id,'draft_prepared',draft_id=row.id,version=row.version,content_hash=rev.content_hash)
    return detail(session,row.id)


def create(session, rid, data):
    owner=owner_open(session,rid)
    if set(data.sources)-set(json.loads(owner.sources_json)):
        raise ValueError('Add source references to the responsibility first.')
    row=PreparedDraft(responsibility_id=rid); session.add(row); session.flush()
    return add_revision(session,row,data,owner)


def revise(session, draft_id, data):
    row=get_draft(session,draft_id); owner=owner_open(session,row.responsibility_id)
    if set(data.sources)-set(json.loads(owner.sources_json)): raise ValueError('Add source references to the responsibility first.')
    result=session.execute(update(PreparedDraft).where(PreparedDraft.id==row.id,
        PreparedDraft.version==data.expected_version).values(version=data.expected_version+1),
        execution_options={'synchronize_session':False})
    if result.rowcount!=1: raise service.Conflict('Draft changed. Reload before saving.')
    session.expire(row); session.refresh(row)
    return add_revision(session,row,data,owner)


def review(session, draft_id, data):
    row=get_draft(session,draft_id); owner_open(session,row.responsibility_id)
    if not data.confirmed or not data.note.strip(): raise ValueError('Explicit confirmation and a review note are required.')
    # Conditional no-op update locks/claims this exact artifact version.
    result=session.execute(update(PreparedDraft).where(PreparedDraft.id==row.id,
        PreparedDraft.version==data.expected_version).values(version=data.expected_version),
        execution_options={'synchronize_session':False})
    if result.rowcount!=1: raise service.Conflict('Draft changed. Review the latest revision.')
    rev=revision(session,row)
    if data.decision=='accepted' and json.loads(rev.context_json)['missing_facts']:
        raise ValueError('Resolve the missing facts and save a new revision before accepting.')
    if rev.review_status!='pending': raise service.Conflict('This revision is already reviewed. Save a new revision for further changes.')
    changed=session.execute(update(DraftRevision).where(DraftRevision.id==rev.id,
        DraftRevision.review_status=='pending').values(review_status=data.decision,
        review_note=data.note.strip(),reviewed_at=utcnow()),execution_options={'synchronize_session':False})
    if changed.rowcount!=1: raise service.Conflict('This revision has already been reviewed. Reload it.')
    session.expire(rev)
    service.event(session,row.responsibility_id,'draft_reviewed',draft_id=row.id,
        version=row.version,decision=data.decision,content_hash=rev.content_hash,note=data.note.strip())
    session.flush()
    return detail(session,row.id)


def checklist(session, rid):
    owner=owner_open(session,rid)
    content=f'# {owner.title}\n\nDesired outcome: {owner.outcome or "[Needs clarification]"}\n\n'
    content+='- [ ] Confirm requirements and source material\n'
    content+=f'- [ ] {owner.next_action or "Choose the next action"}\n'
    content+='- [ ] Prepare a draft\n- [ ] Review facts and resolve missing information\n- [ ] Confirm the actual outcome separately\n'
    return create(session,rid,DraftContent(title=owner.title+' checklist' if len(owner.title)<190 else owner.title,
        content=content,sources=json.loads(owner.sources_json),
        missing_facts=[] if owner.outcome else ['What is the desired outcome?']))


def forget_for_responsibility(session,rid):
    ids=select(PreparedDraft.id).where(PreparedDraft.responsibility_id==rid)
    session.execute(delete(DraftRevision).where(DraftRevision.draft_id.in_(ids)))
    session.execute(delete(PreparedDraft).where(PreparedDraft.responsibility_id==rid))
