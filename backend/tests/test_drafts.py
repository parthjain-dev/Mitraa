import pytest
from sqlalchemy import select
from mitraa.db.models import PreparedDraft,DraftRevision
from mitraa.responsibilities import service,drafts
from mitraa.responsibilities.schemas import ResponsibilityCreate,ResponsibilityPatch


def owner(session):
    return service.create(session,ResponsibilityCreate(title='Application',outcome='Prepare factual application',
        next_action='Read requirements',sources=['User supplied listing']))


def data(**changes):
    return dict(title='Application draft',content='Dear team,\n[Qualification needed]',
        sources=['User supplied listing'],missing_facts=['What qualifications may we include?'],**changes)


def test_draft_provenance_revision_review_and_completion_are_separate(session_factory):
    with session_factory() as session:
        item=owner(session)
        first=drafts.create(session,item['id'],drafts.DraftContent(**data()))
        session.commit(); draft_id=first['id']
    with session_factory() as session:
        saved=drafts.detail(session,draft_id)
        assert saved['missing_facts'] and saved['responsibility_version']==1
        with pytest.raises(ValueError,match='missing facts'):
            drafts.review(session,draft_id,drafts.DraftReview(expected_version=1,decision='accepted',note='Checked',confirmed=True))
        session.rollback()
        revised=drafts.revise(session,draft_id,drafts.DraftUpdate(**{**data(),'content':'Dear team,\nPlease find my application.',
            'missing_facts':[]},expected_version=1))
        assert revised['version']==2 and revised['review_status']=='pending'
        assert revised['content_hash']!=saved['content_hash'] and '-[Qualification needed]' in revised['diff']
        accepted=drafts.review(session,draft_id,drafts.DraftReview(expected_version=2,decision='accepted',note='Checked wording against my supplied facts',confirmed=True))
        assert accepted['review_status']=='accepted'
        assert service.get(session,item['id']).status=='captured'
        session.commit()
    with session_factory() as session:
        updated=drafts.revise(session,draft_id,drafts.DraftUpdate(**{**data(),'missing_facts':[]},expected_version=2))
        assert updated['review_status']=='pending'
        assert updated['revisions'][1]['review_status']=='accepted'
        assert updated['revisions'][1]['review_note']


def test_unknown_sources_stale_writes_and_unconfirmed_review_rejected(session):
    item=owner(session)
    with pytest.raises(ValueError): drafts.create(session,item['id'],drafts.DraftContent(**{**data(),'sources':['Invented source']}))
    row=drafts.create(session,item['id'],drafts.DraftContent(**data()))
    with pytest.raises(service.Conflict):
        drafts.revise(session,row['id'],drafts.DraftUpdate(**data(),expected_version=99))
    with pytest.raises(ValueError,match='confirmation'):
        drafts.review(session,row['id'],drafts.DraftReview(expected_version=1,decision='changes_requested',note='Need facts'))
    result=drafts.review(session,row['id'],drafts.DraftReview(expected_version=1,decision='changes_requested',note='Need facts',confirmed=True))
    assert result['review_status']=='changes_requested'
    with pytest.raises(service.Conflict):
        drafts.review(session,row['id'],drafts.DraftReview(expected_version=1,decision='changes_requested',note='Again',confirmed=True))


def test_forget_removes_artifacts_and_revisions_with_foreign_keys(session):
    session.connection().exec_driver_sql('PRAGMA foreign_keys=ON')
    item=owner(session); drafts.checklist(session,item['id'])
    service.forget(session,item['id'],1); session.commit()
    assert not list(session.scalars(select(PreparedDraft)))
    assert not list(session.scalars(select(DraftRevision)))


def test_checklist_is_local_and_does_not_invent_personal_facts(session):
    item=owner(session); result=drafts.checklist(session,item['id'])
    assert '- [ ] Read requirements' in result['content']
    assert result['sources']==item['sources'] and result['review_status']=='pending'
    service.patch(session,item['id'],ResponsibilityPatch(expected_version=1,status='cancelled'))
    with pytest.raises(ValueError,match='Reopen'): drafts.checklist(session,item['id'])


def test_agent_can_prepare_but_has_no_acceptance_tool(session,settings,sandbox):
    from mitraa.agent.orchestrator import Orchestrator
    from mitraa.tools.registry import build_default_registry
    from tests.fakes import FakeLLM,act,call,say
    item=owner(session); session.commit()
    llm=FakeLLM([act(call('prepare_responsibility_draft',dict(responsibility_id=item['id'],**data()))),say('Draft ready for review.')])
    result=Orchestrator(llm,session,settings,sandbox=sandbox).run(None,'Prepare my application')
    assert result.steps[0].status=='success'
    assert drafts.list_drafts(session,item['id'])[0]['review_status']=='pending'
    assert not any('review_draft' in name or 'accept_draft' in name for name in build_default_registry().names())


def test_draft_routes_validate_stale_version_without_http_client(session):
    from mitraa.responsibilities.api import prepare_draft,revise_draft,review_draft,draft_detail
    from fastapi import HTTPException
    item=owner(session)
    result=prepare_draft(item['id'],drafts.DraftContent(**data()),session)
    with pytest.raises(HTTPException) as error:
        revise_draft(result['id'],drafts.DraftUpdate(**data(),expected_version=20),session)
    assert error.value.status_code==409
    accepted=review_draft(result['id'],drafts.DraftReview(expected_version=1,decision='changes_requested',note='Need facts',confirmed=True),session)
    assert draft_detail(result['id'],session)['review_note']==accepted['review_note']
