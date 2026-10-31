"""Explicit selected-context approval and inspection for bounded coding jobs."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPlainTextEdit,
    QPushButton,QComboBox,QFileDialog,QMessageBox,QSpinBox,QTabWidget,QApplication,QCheckBox)
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
        info=QLabel('Review the proposal, optionally run an approved Python check, then accept and save beside the original as <name>_byMitraa.')
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
        self.exact_names=QCheckBox('Use output filenames exactly as entered (only for a user-specified name)');layout.addWidget(self.exact_names)
        row=QHBoxLayout(); layout.addLayout(row)
        row.addWidget(QLabel('Output token cap'))
        self.tokens=QSpinBox(); self.tokens.setRange(256,4096); self.tokens.setValue(2048); row.addWidget(self.tokens)
        row.addWidget(QLabel('Request timeout (seconds)'))
        self.timeout=QSpinBox(); self.timeout.setRange(10,120); self.timeout.setValue(60); row.addWidget(self.timeout)
        tabs=QTabWidget();layout.addWidget(tabs,1)
        self.details=QPlainTextEdit(); self.details.setReadOnly(True);tabs.addTab(self.details,'Contract / selected context')
        self.proposal=QPlainTextEdit();self.proposal.setReadOnly(True);tabs.addTab(self.proposal,'Proposal / checks')
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);tabs.addTab(self.diff,'Diffs')
        from PySide6.QtWidgets import QWidget
        check_tab=QWidget();checks_layout=QVBoxLayout(check_tab);tabs.addTab(check_tab,'Run checks')
        description=QLabel('Runs selected Python files in a temporary copy, with a 1–30 second timeout and Windows process limits. '
            'This is not a security sandbox: code retains your Windows account’s file and network access. Approve only code you trust. '
            'Uses Python standard library only; no package installation or arbitrary shell commands.')
        description.setWordWrap(True);checks_layout.addWidget(description)
        row=QHBoxLayout();checks_layout.addLayout(row)
        self.check_kind=QComboBox();self.check_kind.addItem('Python unit tests (unittest)','unittest');self.check_kind.addItem('Compare program output','output');row.addWidget(self.check_kind)
        self.check_file=QComboBox();row.addWidget(self.check_file,1)
        self.check_timeout=QSpinBox();self.check_timeout.setRange(1,30);self.check_timeout.setValue(10);self.check_timeout.setSuffix(' sec');row.addWidget(self.check_timeout)
        self.expected=QPlainTextEdit();self.expected.setPlaceholderText('Expected printed output (for Compare program output)');self.expected.setMaximumHeight(90);checks_layout.addWidget(self.expected)
        self.check_kind.currentIndexChanged.connect(lambda _:self.expected.setEnabled(self.check_kind.currentData()=='output'))
        self.expected.setEnabled(False)
        row=QHBoxLayout();checks_layout.addLayout(row)
        run_button=QPushButton('Run approved check');run_button.clicked.connect(self.run_check);row.addWidget(run_button)
        stop_button=QPushButton('Stop check');stop_button.clicked.connect(self.stop_check);row.addWidget(stop_button)
        self.check_results=QPlainTextEdit();self.check_results.setReadOnly(True);checks_layout.addWidget(self.check_results,1)
        self.note=QLineEdit(); self.note.setPlaceholderText('Review note: what did you inspect and verify?'); layout.addWidget(self.note)
        row=QHBoxLayout(); layout.addLayout(row)
        for text,action in [('Prepare contract',self.prepare),('Start approved job',self.start),('Refresh',self.refresh),
                            ('Cancel job',self.cancel),('Accept review',self.accept)]:
            button=QPushButton(text); button.clicked.connect(action); row.addWidget(button)
        apply_button=QPushButton('Apply to original folder');apply_button.clicked.connect(self.apply_files);layout.addWidget(apply_button)
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
                output_names_explicit=self.exact_names.isChecked(),
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
        changed=changed or self.exact_names.isChecked()!=c.get('output_names_explicit',False)
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
        if self.current:
            self.runtime.checker.cancel(self.current['id'])
            self.send('job_cancel',id=self.current['id'],version=self.current['version'])

    def run_check(self):
        if self.pending or not self.current:return
        if self.current['status'] not in {'ready_for_review','accepted'}:
            self.notice.setText('Generate and reload a ready proposal first.');return
        if not self.check_file.currentText():self.notice.setText('No selected Python file is available.');return
        recipe=dict(kind=self.check_kind.currentData(),file=self.check_file.currentText(),
            timeout_seconds=self.check_timeout.value(),expected_output=self.expected.toPlainText())
        text=(f'Execute {recipe["file"]} using {self.check_kind.currentText()} for at most {recipe["timeout_seconds"]} seconds?\n\n'
            'The temporary copy contains only the contract snapshot with proposed files overlaid. '
            'No API request, shell command or package install is used.\n\n'
            'This is local code execution, not a security sandbox. Code can access your Windows account’s files and network. '
            'Only run code you trust. Review the selected source, proposed changes and expected output first. '
            'Running a check clears prior review acceptance; failed or stopped checks block acceptance until rerun successfully.')
        if QMessageBox.question(self,'Approve local Python execution',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        try:
            self.runtime.checker.start(self.current['id'],self.current['version'],recipe,confirmed=True)
            self.notice.setText('Check starting. Results will appear in Run checks; Stop check ends the process.')
        except ValueError as exc:self.notice.setText(str(exc))

    def stop_check(self):
        if self.current:
            self.runtime.checker.cancel(self.current['id'])
            self.notice.setText('Stopping check…')

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
        selected=self.check_file.currentText();self.check_file.clear()
        names={name for name,text in contract['snapshot'].items() if text is not None}|set(result.get('files',{}))
        self.check_file.addItems(sorted(name for name in names if name.lower().endswith('.py')))
        if selected in names:self.check_file.setCurrentText(selected)
        runs=result.get('test_runs',[])
        self.check_results.setPlainText(json.dumps(runs,indent=2,ensure_ascii=False) if runs else 'No approved tests have been run. Syntax checks alone do not verify program behavior.')
        if self.loaded_id!=payload['id']:
            self.workspace.setText(contract['workspace']);self.objective.setText(payload['objective'])
            self.criteria.setText(payload['acceptance_criteria'])
            self.inputs.setPlainText('\n'.join(contract.get('source_files',[])))
            self.outputs.setPlainText('\n'.join(contract['output_files']))
            self.tokens.setValue(contract['max_output_tokens']);self.timeout.setValue(contract['timeout_seconds'])
            self.exact_names.setChecked(contract.get('output_names_explicit',False))
            self.loaded_id=payload['id']
        self.details.setPlainText(payload['objective']+'\n\nAcceptance criteria:\n'+payload['acceptance_criteria']+'\n\n'+
            '\n'.join(k.replace('_',' ').capitalize()+': '+str(v) for k,v in contract.items() if k!='snapshot')+
            '\n\nSelected context:\n'+'\n\n'.join(name+'\n'+(text if text is not None else '[New output file]') for name,text in contract['snapshot'].items()))
        self.proposal.setPlainText(json.dumps({k:v for k,v in result.items() if k not in {'files','diffs'}},indent=2,ensure_ascii=False)+
            '\n\n'+'\n\n'.join(name+'\n'+text for name,text in result.get('files',{}).items()))
        self.diff.setPlainText('\n\n'.join(result.get('diffs',{}).values()))
        self.notice.setText('Status: '+payload['status']+' · '+('Files saved. Backup paths are listed in Proposal / checks.' if payload['status']=='applied' else
            'Inspect Run checks for test results, then accept review and apply.' if runs else 'No tests run. Optional Python checks are available in Run checks.'))
        self.choose.blockSignals(True)
        index=self.choose.findData(payload['id'])
        if index<0:self.choose.addItem(payload['objective'][:70],payload['id']);index=self.choose.count()-1
        self.choose.setCurrentIndex(index);self.choose.setItemText(index,payload['objective'][:70]+' · '+payload['status'])
        self.choose.blockSignals(False)

    def apply_files(self):
        if self.pending or not self.current:return
        if self.current['status']!='accepted':
            self.notice.setText('Accept the reviewed proposal first.');return
        names='\n'.join(self.current['contract'].get('apply_targets',{}).get(name,name) for name in self.current['result'].get('files',{}))
        text=('Save reviewed changes to these files in '+self.current['contract']['workspace']+'?\n\n'+names+
            '\n\nExisting files receive a .mitraa-<job-id>.bak backup beside them. Changed source files block the update. '
            'New output files are created in this folder. Multiple files are applied one at a time; if interrupted, refresh and retry Apply. No code is executed.')
        if QMessageBox.question(self,'Apply reviewed changes',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.send('job_apply',id=self.current['id'],version=self.current['version'],confirmed=True)
