from types import SimpleNamespace as NS
from mitraa.agent.llm import NemotronClient
from mitraa.usage import events


def test_coding_adapter_uses_one_capped_request_without_tools(settings,monkeypatch):
    settings.nebius_api_key='test';settings.nebius_base_url='https://example.test/v1';settings.nemotron_model='model'
    client=NemotronClient(settings)
    captured=[];options=[]
    def create(**kwargs):
        captured.append(kwargs)
        return NS(model='model',usage=NS(prompt_tokens=10,completion_tokens=5,total_tokens=15),
            choices=[NS(finish_reason='stop',message=NS(content='{"files":{"hello.py":"print(1)"},"summary":"Done","missing_facts":[]}'))])
    monkeypatch.setattr(client._client,'with_options',lambda **kw:options.append(kw) or client._client)
    monkeypatch.setattr(client._client.chat.completions,'create',create)
    collected=[];token=events.set(collected)
    try:
        result=client.coding_proposal(dict(timeout_seconds=30,max_output_tokens=512,
            snapshot={'hello.py':None},output_files=['hello.py']),'Write hello','Print 1')
    finally:events.reset(token)
    assert result['files']['hello.py']=='print(1)'
    assert options==[dict(timeout=30,max_retries=0)]
    assert len(captured)==1 and captured[0]['max_tokens']==512 and 'tools' not in captured[0]
    assert collected[0]['operation']=='coding' and collected[0]['total_tokens']==15
