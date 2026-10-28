from types import SimpleNamespace as NS
from tests.test_orb_ui import ui
from mitraa.assistant.ui.controller import State


class Speaker:
    enabled=True
    def __init__(self): self.queued=[]
    def say(self,text): self.queued.append(text)
    def stop(self): pass
    def close(self): pass


def reply(c):
    c.handle('response',NS(type='message',pending_approval=None,text='Saved your preference.'),c.request_id)


def test_answer_is_immediate_even_before_real_playback_start(ui):
    _,o,c,w=ui
    c.speaker=Speaker(); c.submit('Remember this')
    reply(c)
    assert c.state==State.PREPARING_SPEECH and not c.busy
    assert c.result_text=='Saved your preference.' and o.card.isVisible()
    assert c.speaker.queued==['Saved your preference.']
    c.handle('speech_started',None,c.epoch)
    assert c.result_text=='Saved your preference.' and o.card.isVisible()
    assert c.state==State.SPEAKING and not c.busy
    assert len(c.history_records)==2


def test_muted_answer_is_immediate(ui):
    _,o,c,w=ui
    c.speaker=Speaker(); c.muted=True; c.submit('Remember this'); reply(c)
    assert c.result_text and not c.speaker.queued and not c.busy


def test_speech_failure_preserves_answer(ui):
    _,o,c,w=ui
    c.speaker=Speaker(); c.submit('Remember this'); reply(c)
    c.handle('speech_error','Unavailable',c.epoch)
    assert c.result_text=='Saved your preference.' and not c.busy


def test_dismiss_preserves_reply_and_ignores_late_audio(ui):
    _,o,c,w=ui
    c.speaker=Speaker(); c.submit('Remember this'); reply(c)
    epoch=c.epoch; c.dismiss()
    c.handle('speech_started',None,epoch)
    assert not o.isVisible() and c.pending_reply is None
    assert c.result_text=='Saved your preference.' and not c.busy


def test_missing_start_event_cannot_delay_text(ui):
    _,o,c,w=ui
    c.speaker=Speaker(); c.submit('Remember this'); reply(c)
    assert c.result_text and not c.busy and c.pending_reply is None

def test_next_request_is_accepted_while_voice_is_preparing(ui):
    _,o,c,w=ui
    c.speaker=Speaker(); c.submit('First'); reply(c)
    assert c.submit('Second')
    assert w.sent==[('First',1),('Second',2)]
