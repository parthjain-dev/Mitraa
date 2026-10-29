"""Explicit selected-context approval and inspection for bounded coding jobs."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPlainTextEdit,
    QPushButton,QComboBox,QFileDialog,QMessageBox,QSpinBox,QTabWidget,QApplication)
from mitraa.assistant.ui.responsibilities import STYLE


class JobDesk(QDialog):
    def __init__(self,runtime):
        super().__init__(runtime.desk)
        self.runtime=runtime; self.rid=None; self.current=None; self.pending=False; self.dirty=False
        self.loaded_id=None
        self.setWindowTitle('Mitraa · Coding jobs'); self.setStyleSheet(STYLE); self.resize(880,780)
        area=QApplication.primaryScreen().availableGeometry()
        self.resize(min(880,area.width()-40),min(780,area.height()-60))
        layout=QVBoxLayout(self)
        info=QLabel('Bounded coding proposals · one provider call · selected text only · no commands or generated code execution. Original files stay unchanged.')
        info.setWordWrap(True); layout.addWidget(info)
        self.choose=QComboBox(); self.choose.currentIndexChanged.connect(self.selected); layout.addWidget(self.choose)
        row=QHBoxLayout(); layout.addLayout(row)
        self.workspace=QLineEdit(); self.workspace.setPlaceholderText('Existing project folder inside MITRAA_ALLOWED_ROOTS'); row.addWidget(self.workspace)
        browse=QPushButton('Choose folder'); browse.clicked.connect(self.browse); row.addWidget(browse)
        self.objective=QLineEdit(); self.objective.setPlaceholderText('Small coding objective'); layout.addWidget(self.objective)
        self.criteria=QLineEdit(); self.criteria.setPlaceholderText('Acceptance criteria you will check'); layout.addWidget(self.criteria)
        row=QHBoxLayout(); layout.addLayout(row)
        self.inputs=QPlainTextEdit(); self.inputs.setPlaceholderText('Input files, one relative path per line\nexample.py'); self.inputs.setMaximumHeight(85); row.addWidget(self.inputs)
        self.outputs=QPlainTextEdit(); self.outputs.setPlaceholderText('Allowed output files, one relative path per line\nexample.py'); self.outputs.setMaximumHeight(85); row.addWidget(self.outputs)
        row=QHBoxLayout(); layout.addLayout(row)
        row.addWidget(QLabel('Output token cap'))
        self.tokens=QSpinBox(); self.tokens.setRange(256,4096); self.tokens.setValue(2048); row.addWidget(self.tokens)
        row.addWidget(QLabel('Request timeout (seconds)'))
        self.timeout=QSpinBox(); self.timeout.setRange(10,120); self.timeout.setValue(60); row.addWidget(self.timeout)
        tabs=QTabWidget();layout.addWidget(tabs,1)
        self.details=QPlainTextEdit(); self.details.setReadOnly(True);tabs.addTab(self.details,'Contract / selected context')
        self.proposal=QPlainTextEdit();self.proposal.setReadOnly(True);tabs.addTab(self.proposal,'Proposal / checks')
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);tabs.addTab(self.diff,'Diffs')
        self.note=QLineEdit(); self.note.setPlaceholderText('Review note: what did you inspect and verify?'); layout.addWidget(self.note)
        row=QHBoxLayout(); layout.addLayout(row)
        for text,action in [('Prepare contract',self.prepare),('Start approved job',self.start),('Refresh',self.refresh),
                            ('Cancel job',self.cancel),('Accept review',self.accept)]:
            button=QPushButton(text); button.clicked.connect(action); row.addWidget(button)
        self.notice=QLabel(); self.notice.setWordWrap(True); self.notice.setTextFormat(Qt.PlainText); layout.addWidget(self.notice)

    def browse(self):
        folder=QFileDialog.getExistingDirectory(self,'Choose a permitted project folder')
        if folder:self.workspace.setText(folder)

    def open_for(self,item):
        if self.pending:return
        if self.rid!=item['id']:
            self.current=None;self.choose.blockSignals(True);self.choose.clear();self.choose.blockSignals(False)
        self.rid=item['id']; self.show(); self.raise_(); self.activateWindow(); self.refresh()

    def send(self,op,**args):
        if self.pending:return
        self.pending=True; self.notice.setText('Loading/saving locally…')
        self.runtime.worker.submit(op,**args)

    def prepare(self):
        if self.rid:
            self.send('job_create',data=dict(responsibility_id=self.rid,workspace=self.workspace.text(),
                objective=self.objective.text(),acceptance_criteria=self.criteria.text(),
                source_files=[x.strip() for x in self.inputs.toPlainText().splitlines() if x.strip()],
                output_files=[x.strip() for x in self.outputs.toPlainText().splitlines() if x.strip()],
                max_output_tokens=self.tokens.value(),timeout_seconds=self.timeout.value()))

    def selected(self,index):
        jid=self.choose.itemData(index)
        if jid:self.send('job_detail',id=jid)

    def refresh(self):
        if self.current:self.send('job_detail',id=self.current['id'])
        elif self.rid:self.send('job_list',rid=self.rid)

    def start(self):
        if self.pending or not self.current:return
        if self.current['status']!='prepared':self.notice.setText('Prepare a new contract before starting.');return
        c=self.current['contract']
        changed=(self.workspace.text()!=c['workspace'] or self.objective.text()!=self.current['objective']
            or self.criteria.text()!=self.current['acceptance_criteria']
            or [x.strip() for x in self.inputs.toPlainText().splitlines() if x.strip()]!=c['source_files']
            or [x.strip() for x in self.outputs.toPlainText().splitlines() if x.strip()]!=c['output_files']
            or self.tokens.value()!=c['max_output_tokens'] or self.timeout.value()!=c['timeout_seconds'])
        if changed:
            self.notice.setText('Form changed. Prepare a new contract before approving it.');return
        text=(f'Send the displayed selected file contents and objective to {c["provider"]}, model {c["model"]}?\n'
            f'One request, at most {c["max_output_tokens"]} output tokens; input is bounded to 24 KB plus instructions. '
            'This is not a currency spending cap. No automatic retries.\n'
            'Review the contract and snapshot below before confirming. Only the isolated job folder is written.')
        if QMessageBox.question(self,'Approve coding job',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        try:
            self.runtime.coder.start(self.current['id'],self.current['version'],confirmed=True)
            self.notice.setText('Job started. Refresh for progress. Cancellation discards late results but cannot undo provider usage already incurred.')
        except ValueError as exc:self.notice.setText(str(exc))

    def cancel(self):
        if self.current:self.send('job_cancel',id=self.current['id'],version=self.current['version'])

    def accept(self):
        if not self.current:return
        if not self.note.text().strip():self.notice.setText('Enter a review note first.');return
        if QMessageBox.question(self,'Accept isolated proposal','Accept the displayed proposal? No original file is replaced and the responsibility stays open.',
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.send('job_accept',id=self.current['id'],version=self.current['version'],note=self.note.text(),confirmed=True)

    def result(self,op,payload,error):
        self.pending=False
        if error:self.notice.setText(error);return
        if op=='job_list':
            if payload['responsibility_id']!=self.rid:return
            self.choose.blockSignals(True);self.choose.clear()
            for item in payload['jobs']:self.choose.addItem(item['objective'][:70]+' · '+item['status'],item['id'])
            self.choose.blockSignals(False)
            if self.choose.count():self.selected(0)
            return
        if payload.get('responsibility_id')!=self.rid:return
        self.current=payload
        contract=payload['contract']; result=payload['result']
        if self.loaded_id!=payload['id']:
            self.workspace.setText(contract['workspace']);self.objective.setText(payload['objective'])
            self.criteria.setText(payload['acceptance_criteria'])
            self.inputs.setPlainText('\n'.join(contract.get('source_files',[])))
            self.outputs.setPlainText('\n'.join(contract['output_files']))
            self.tokens.setValue(contract['max_output_tokens']);self.timeout.setValue(contract['timeout_seconds'])
            self.loaded_id=payload['id']
        self.details.setPlainText(payload['objective']+'\n\nAcceptance criteria:\n'+payload['acceptance_criteria']+'\n\n'+
            '\n'.join(k.replace('_',' ').capitalize()+': '+str(v) for k,v in contract.items() if k!='snapshot')+
            '\n\nSelected context:\n'+'\n\n'.join(name+'\n'+(text if text is not None else '[New output file]') for name,text in contract['snapshot'].items()))
        self.proposal.setPlainText(json.dumps({k:v for k,v in result.items() if k not in {'files','diffs'}},indent=2,ensure_ascii=False)+
            '\n\n'+'\n\n'.join(name+'\n'+text for name,text in result.get('files',{}).items()))
        self.diff.setPlainText('\n\n'.join(result.get('diffs',{}).values()))
        self.notice.setText('Status: '+payload['status']+' · Review static checks and diffs. Tests are not run; original files are unchanged.')
        self.choose.blockSignals(True)
        index=self.choose.findData(payload['id'])
        if index<0:self.choose.addItem(payload['objective'][:70],payload['id']);index=self.choose.count()-1
        self.choose.setCurrentIndex(index);self.choose.setItemText(index,payload['objective'][:70]+' · '+payload['status'])
        self.choose.blockSignals(False)
