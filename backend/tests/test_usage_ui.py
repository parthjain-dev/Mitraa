from mitraa.db.models import ModelUsage
from tests.test_responsibilities_ui import runtime,until


def test_usage_window_reads_saved_counts_without_provider(runtime,session_factory):
    with session_factory() as session:
        session.add(ModelUsage(request_id='test',provider='example.test',model='model',
            operation='chat',status='received',input_tokens=100,output_tokens=20,total_tokens=120))
        session.commit()
    runtime.open_usage()
    until(lambda:runtime.usage_dialog.models.topLevelItemCount()==1)
    dialog=runtime.usage_dialog
    assert '120' in dialog.totals.text()
    assert dialog.models.topLevelItem(0).text(0)=='example.test / model'
    assert dialog.requests.topLevelItem(0).text(4)=='120'
    assert 'Earlier usage is unavailable' in dialog.notice.text()
