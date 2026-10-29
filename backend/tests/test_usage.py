from types import SimpleNamespace as NS
import pytest
from sqlalchemy import select
from mitraa.agent.llm import NemotronClient,LLMError
from mitraa.agent.orchestrator import Orchestrator,AgentResponse
from mitraa.db.models import ModelUsage
from mitraa.usage import summary,tracked


def client(settings,monkeypatch,responses):
    settings.nebius_api_key='test-secret'; settings.nebius_base_url='https://provider.example/v1'
    settings.nemotron_model='free-router'
    result=NemotronClient(settings)
    def create(**kwargs):
        response=responses.pop(0)
        if isinstance(response,Exception): raise response
        return response
    monkeypatch.setattr(result._client.chat.completions,'create',create)
    return result


def response(input_tokens=20,output_tokens=5,tools=None):
    return NS(model='resolved-model',usage=NS(prompt_tokens=input_tokens,completion_tokens=output_tokens,total_tokens=None),
        choices=[NS(message=NS(content='Done',tool_calls=tools or []))])


def test_tool_loop_usage_persisted_and_returned(session,settings,sandbox,monkeypatch):
    tool=NS(id='call-1',function=NS(name='list_memories',arguments='{}'))
    llm=client(settings,monkeypatch,[response(tools=[tool]),response(40,10)])
    result=Orchestrator(llm,session,settings,sandbox=sandbox).run(None,'List my memories')
    assert result.usage['calls']==2 and result.usage['total_tokens']==75
    assert result.usage['input_tokens']==60 and result.usage['output_tokens']==15
    data=summary(session)
    assert data['all_time']['total_tokens']==75
    assert data['by_model'][0]['provider']=='provider.example'
    assert data['by_model'][0]['model']=='resolved-model'
    assert data['recent_requests'][0]['calls']==2
    assert data['first_recorded_at']
    # Reloading the summary must not increment or duplicate anything.
    assert summary(session)==data
    stored=list(session.scalars(select(ModelUsage)))
    assert all(r.conversation_id==result.conversation_id for r in stored)


def test_plan_unknown_and_error_counts_survive_rollback(session,settings,monkeypatch):
    from openai import APIConnectionError
    unknown=response(None,None)
    llm=client(settings,monkeypatch,[response(8,2),unknown,APIConnectionError(request=None)])
    class Request:
        def __init__(self): self.session=session
        @tracked
        def run(self):
            llm.plan_json('Plan a project')
            llm.chat([],[])
            llm.chat([],[])
    with pytest.raises(LLMError): Request().run()
    data=summary(session)
    assert data['all_time']['calls']==3
    assert data['all_time']['failed_calls']==1
    assert data['all_time']['unreported_calls']==2
    assert data['all_time']['total_tokens']==10
    assert len(data['recent_requests'])==1
    assert session.scalar(select(ModelUsage.operation))=='plan'


def test_usage_recorded_even_if_provider_returns_no_choices(session,settings,sandbox,monkeypatch):
    empty=response(9,1); empty.choices=[]
    llm=client(settings,monkeypatch,[empty])
    result=Orchestrator(llm,session,settings,sandbox=sandbox).run(None,'Test')
    assert result.usage['total_tokens']==10
    assert summary(session)['all_time']['calls']==1


def test_unreported_usage_is_not_fabricated(session,settings,sandbox,monkeypatch):
    item=response(); del item.usage
    llm=client(settings,monkeypatch,[item])
    result=Orchestrator(llm,session,settings,sandbox=sandbox).run(None,'Test')
    assert result.usage['unreported_calls']==1
    row=session.scalar(select(ModelUsage))
    assert row.input_tokens is None and row.output_tokens is None and row.total_tokens is None


def test_local_fake_calls_do_not_claim_api_tokens(session,settings,sandbox):
    from tests.fakes import FakeLLM,say
    result=Orchestrator(FakeLLM([say('Hi')]),session,settings,sandbox=sandbox).run(None,'Test')
    assert result.usage['calls']==0 and not summary(session)['by_model']


def test_provider_breakdown_and_utc_day_filter(session):
    from datetime import datetime,timedelta,timezone
    now=datetime.now(timezone.utc)
    for provider,when,count in [('groq.example',now-timedelta(days=2),30),('openrouter.example',now,50)]:
        session.add(ModelUsage(request_id=provider,provider=provider,model='model',operation='chat',
            status='received',input_tokens=count,output_tokens=0,total_tokens=count,created_at=when))
    session.commit()
    data=summary(session)
    assert data['all_time']['total_tokens']==80 and data['today_utc']['total_tokens']==50
    assert {r['provider']:r['total_tokens'] for r in data['by_model']}=={'groq.example':30,'openrouter.example':50}
