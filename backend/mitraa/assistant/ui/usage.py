"""Read-only local usage ledger viewer."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QTreeWidget,QTreeWidgetItem
from mitraa.assistant.ui.responsibilities import STYLE,display_time


class UsageDialog(QDialog):
    def __init__(self,runtime):
        super().__init__(runtime.desk)
        self.runtime=runtime; self.setWindowTitle('Mitraa · Token usage'); self.setStyleSheet(STYLE)
        self.resize(760,560)
        layout=QVBoxLayout(self)
        self.notice=QLabel(); self.notice.setWordWrap(True); self.notice.setTextFormat(Qt.PlainText); layout.addWidget(self.notice)
        self.totals=QLabel(); self.totals.setWordWrap(True); layout.addWidget(self.totals)
        self.models=QTreeWidget(); self.models.setHeaderLabels(['Provider / model','Calls','Input','Output','Total','Unknown'])
        self.models.setColumnWidth(0,300); layout.addWidget(self.models)
        layout.addWidget(QLabel('Recent API-backed requests · each row includes all model calls in that turn'))
        self.requests=QTreeWidget(); self.requests.setHeaderLabels(['Time (local)','Calls','Input','Output','Total','Unknown'])
        self.requests.setColumnWidth(0,230); layout.addWidget(self.requests)
        for widget in (self.models,self.requests):
            widget.setRootIsDecorated(False)
            for index in range(1,6): widget.setColumnWidth(index,80)
        self.refresh=QPushButton('Refresh'); self.refresh.clicked.connect(self.load); layout.addWidget(self.refresh)

    def load(self):
        self.show(); self.raise_(); self.activateWindow()
        self.refresh.setEnabled(False); self.notice.setText('Loading recorded API usage…')
        self.runtime.worker.submit('usage')

    def result(self,payload,error):
        self.refresh.setEnabled(True)
        if error: self.notice.setText(error); return
        first=payload['first_recorded_at']
        self.notice.setText(('Recorded since '+display_time(first,self.runtime.timezone)+'. ' if first else 'No API usage recorded yet. ')+
            'Earlier usage is unavailable. Known provider-reported tokens only; unknown is not zero. '
            'SDK-internal retries may consume unreported tokens. This is not a bill or remaining free quota. '
            'Local greetings, voice processing and offline actions are excluded.')
        def line(label,row):
            return f'{label}: {row["total_tokens"]:,} known tokens · input {row["input_tokens"]:,} · output {row["output_tokens"]:,} · {row["calls"]} calls · {row["unreported_calls"]} unreported · {row["failed_calls"]} failed'
        self.totals.setText(line('All time',payload['all_time'])+'\n'+line('Today (UTC)',payload['today_utc']))
        for widget,rows in ((self.models,payload['by_model']),(self.requests,payload['recent_requests'])):
            widget.clear()
            for row in rows:
                label=(row['provider']+' / '+row['model']) if widget is self.models else display_time(row['created_at'],self.runtime.timezone)
                item=QTreeWidgetItem([label]+[f'{row[k]:,}' for k in ('calls','input_tokens','output_tokens','total_tokens','unreported_calls')])
                widget.addTopLevelItem(item)
