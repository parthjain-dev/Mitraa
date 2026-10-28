from pathlib import Path
import pytest
from mitraa.tools.text_files import OpenFolder,OpenFolderArgs,WriteTextFile,WriteTextArgs
from mitraa.tools.files import ReadFile,ReadFileArgs
from mitraa.security.permissions import evaluate
from mitraa.tools.base import RiskLevel

def test_create_read_append_replace(roots,make_ctx,trash):
    path=roots['Documents']/'notes.txt'; tool=WriteTextFile()
    for mode,content,expected in [('create','Hello मित्रा\n','Hello मित्रा\n'),('append','Second line','Hello मित्रा\nSecond line'),('replace','Replacement','Replacement')]:
        args=WriteTextArgs(path=str(path),mode=mode,content=content)
        assert evaluate(tool,args,make_ctx()).needs_approval
        assert not tool.run(args,make_ctx()).ok
        assert tool.run(args,make_ctx(approved=True)).ok
        assert path.read_text(encoding='utf-8')==expected
        result=ReadFile().run(ReadFileArgs(path=str(path)),make_ctx())
        assert result.data['content']==expected
    assert len(trash)==2

def test_create_does_not_overwrite(roots,make_ctx):
    path=roots['Documents']/'notes.txt'; path.write_text('keep')
    assert not WriteTextFile().run(WriteTextArgs(path=str(path),content='replace'),make_ctx(approved=True)).ok
    assert path.read_text()=='keep'

def test_outside_and_scripts_blocked(tmp_path,roots,make_ctx):
    tool=WriteTextFile()
    for path in [tmp_path/'outside.txt',roots['Documents']/'run.ps1']:
        assert evaluate(tool,WriteTextArgs(path=str(path),content='text'),make_ctx()).level==RiskLevel.BLOCKED
    assert not tool.run(WriteTextArgs(path=str(roots['Documents']/'run.py'),content='text'),make_ctx(approved=True)).ok

@pytest.mark.parametrize('content',[b'\xff\xfe\x00',b'hello\x00world'])
def test_binary_or_invalid_encoding_is_not_changed(content,roots,make_ctx):
    path=roots['Documents']/'notes.txt'; path.write_bytes(content)
    assert not WriteTextFile().run(WriteTextArgs(path=str(path),mode='append',content='extra'),make_ctx(approved=True)).ok
    assert path.read_bytes()==content

def test_open_folder_uses_explorer_without_shell(monkeypatch,roots,make_ctx):
    from mitraa.tools import text_files
    calls=[]; monkeypatch.setattr(text_files.sys,'platform','win32')
    monkeypatch.setattr(text_files.os,'startfile',lambda *args:calls.append(args),raising=False)
    result=OpenFolder().run(OpenFolderArgs(path=str(roots['Documents'])),make_ctx())
    assert result.ok and calls==[(str(roots['Documents']),'explore')]
    assert not OpenFolder().run(OpenFolderArgs(path=str(roots['Documents']/'missing')),make_ctx()).ok

def test_registry_exposes_tools(registry):
    assert all(registry.get(name) for name in ('open_folder','read_file','write_text_file'))

@pytest.mark.parametrize('approved',[False,True])
def test_agent_write_waits_for_explicit_decision(approved,roots,settings,session,sandbox,registry):
    from mitraa.agent.orchestrator import Orchestrator,ApprovalError
    from tests.fakes import FakeLLM,act,call,say
    path=roots['Documents']/'agent-note.txt'
    agent=Orchestrator(FakeLLM([act(call('write_text_file',{'path':str(path),'content':'Hello Mitraa','mode':'create'})),say('Decision handled.')]),session,settings,registry=registry,sandbox=sandbox)
    pending=agent.run(None,'Create a text note saying Hello Mitraa')
    assert pending.type=='approval_required' and not path.exists()
    decision=pending.pending_approval.approval_id
    agent.resume(decision,approved)
    assert path.exists()==approved
    if approved: assert path.read_text()=='Hello Mitraa'
    with pytest.raises(ApprovalError): agent.resume(decision,approved)
