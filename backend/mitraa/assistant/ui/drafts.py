"""Local revision editor and explicit user review; no model calls on the UI thread."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QLineEdit,QPlainTextEdit,QComboBox,QTabWidget,QMessageBox)
from mitraa.assistant.ui.responsibilities import STYLE


class DraftDesk(QDialog):
    def __init__(self,runtime):
        super().__init__(runtime.desk)
        self.runtime=runtime; self.rid=None; self.current=None; self.records={}
        self.dirty=False; self.loading=False; self.pending=False
        self.setWindowTitle('Mitraa · Drafts & review'); self.setStyleSheet(STYLE)
        self.resize(820,700)
        layout=QVBoxLayout(self)
        self.heading=QLabel(); self.heading.setTextFormat(Qt.PlainText); layout.addWidget(self.heading)
        hint=QLabel('Local preparation only. References do not read files. Acceptance is not completion or submission.')
        hint.setWordWrap(True); layout.addWidget(hint)
        row=QHBoxLayout(); layout.addLayout(row)
        self.choose=QComboBox(); self.choose.currentIndexChanged.connect(self.select); row.addWidget(self.choose,1)
        self.new_button=QPushButton('New draft'); self.new_button.clicked.connect(self.new); row.addWidget(self.new_button)
        self.checklist=QPushButton('Prepare checklist'); self.checklist.clicked.connect(self.prepare_checklist); row.addWidget(self.checklist)
        self.reload=QPushButton('Reload'); self.reload.clicked.connect(self.refresh); row.addWidget(self.reload)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs,1)
        editor=QDialog(); box=QVBoxLayout(editor)
        self.title=QLineEdit(); self.title.setPlaceholderText('Draft title'); box.addWidget(self.title)
        self.content=QPlainTextEdit(); self.content.setPlaceholderText('Plain text or Markdown. Use [Needs information] for unknown facts.'); box.addWidget(self.content,1)
        box.addWidget(QLabel('Source references · one per line, already saved on the responsibility'))
        self.sources=QPlainTextEdit(); self.sources.setMaximumHeight(65); box.addWidget(self.sources)
        box.addWidget(QLabel('Missing facts / questions · one per line'))
        self.missing=QPlainTextEdit(); self.missing.setMaximumHeight(65); box.addWidget(self.missing)
        self.tabs.addTab(editor,'Edit')
        self.preview=QPlainTextEdit(); self.preview.setReadOnly(True); self.tabs.addTab(self.preview,'Preview')
        self.diff=QPlainTextEdit(); self.diff.setReadOnly(True); self.tabs.addTab(self.diff,'Changes')
        self.versions=QComboBox(); self.versions.currentIndexChanged.connect(self.show_revision)
        self.saved_preview=QPlainTextEdit(); self.saved_preview.setReadOnly(True)
        history=QDialog(); history_box=QVBoxLayout(history); history_box.addWidget(self.versions); history_box.addWidget(self.saved_preview)
        self.tabs.addTab(history,'Saved revisions')
        self.review_note=QLineEdit(); self.review_note.setPlaceholderText('Review note: what did you check or what must change?'); layout.addWidget(self.review_note)
        buttons=QHBoxLayout(); layout.addLayout(buttons)
        self.save=QPushButton('Save revision'); self.save.clicked.connect(self.save_draft); buttons.addWidget(self.save)
        self.accept=QPushButton('Accept reviewed draft'); self.accept.clicked.connect(lambda:self.review('accepted')); buttons.addWidget(self.accept)
        self.changes=QPushButton('Request changes'); self.changes.clicked.connect(lambda:self.review('changes_requested')); buttons.addWidget(self.changes)
        self.notice=QLabel(); self.notice.setWordWrap(True); self.notice.setTextFormat(Qt.PlainText); layout.addWidget(self.notice)
        for field in (self.title,self.content,self.sources,self.missing): field.textChanged.connect(self.edited)
        self.action_buttons=[self.new_button,self.checklist,self.reload,self.save,self.accept,self.changes]

    def edited(self):
        if not self.loading: self.dirty=True
        self.preview.setPlainText(self.content.toPlainText())

    def discard(self):
        return not self.dirty or QMessageBox.question(self,'Unsaved draft','Discard unsaved draft changes?',
            QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)==QMessageBox.Discard

    def open_for(self,item):
        if self.pending or not self.discard(): return
        self.rid=item['id']; self.heading.setText(item['title'])
        self.new(force=True); self.show(); self.raise_(); self.activateWindow()
        self.send('draft_list',rid=self.rid)

    def send(self,operation,**args):
        if self.pending: return
        self.pending=True
        self.choose.setEnabled(False); self.tabs.setEnabled(False)
        for button in self.action_buttons: button.setEnabled(False)
        self.notice.setText('Working locally…')
        self.runtime.worker.submit(operation,**args)

    def new(self,checked=False,force=False):
        if not force and not self.discard(): return
        self.loading=True; self.current=None
        for field in (self.title,self.content,self.sources,self.missing): field.clear()
        self.diff.clear(); self.versions.clear(); self.saved_preview.clear(); self.review_note.clear()
        self.loading=False; self.dirty=False; self.notice.setText('New draft · not saved')

    def refresh(self):
        if self.discard():
            self.dirty=False; self.send('draft_list',rid=self.rid)

    def prepare_checklist(self):
        if self.discard(): self.send('draft_checklist',rid=self.rid)

    def select(self,index):
        if self.loading or index<0: return
        if not self.discard():
            self.choose.blockSignals(True)
            self.choose.setCurrentIndex(self.choose.findData(self.current['id']) if self.current else -1)
            self.choose.blockSignals(False); return
        self.send('draft_detail',id=self.choose.itemData(index))

    def save_draft(self):
        data=dict(title=self.title.text(),content=self.content.toPlainText(),
            sources=[v.strip() for v in self.sources.toPlainText().splitlines() if v.strip()],
            missing_facts=[v.strip() for v in self.missing.toPlainText().splitlines() if v.strip()])
        if self.current:
            self.send('draft_save',id=self.current['id'],data={**data,'expected_version':self.current['version']})
        else: self.send('draft_create',rid=self.rid,data=data)

    def review(self,decision):
        if not self.current or self.dirty:
            self.notice.setText('Save your changes before reviewing the saved revision.'); return
        if not self.review_note.text().strip():
            self.notice.setText('Enter a review note first.'); return
        if decision=='accepted' and self.current['missing_facts']:
            self.notice.setText('Resolve missing facts and save a revision before accepting.'); return
        if QMessageBox.question(self,'Confirm review',
            f'Record {decision.replace("_"," ")} for revision {self.current["version"]}? This does not complete or submit the responsibility.',
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        self.send('draft_review',id=self.current['id'],data=dict(expected_version=self.current['version'],
            decision=decision,note=self.review_note.text(),confirmed=True))

    def load(self,data):
        self.current=data; self.loading=True
        self.title.setText(data['title']); self.content.setPlainText(data['content'])
        self.sources.setPlainText('\n'.join(data['sources'])); self.missing.setPlainText('\n'.join(data['missing_facts']))
        self.diff.setPlainText(data.get('diff',''))
        self.versions.clear()
        for rev in data.get('revisions',[]):
            self.versions.addItem(f'v{rev["version"]} · {rev["review_status"]}',rev)
        self.versions.setCurrentIndex(self.versions.count()-1)
        self.review_note.setText(data.get('review_note',''))
        self.loading=False; self.dirty=False
        self.notice.setText(f'Revision {data["version"]} · {data["review_status"]} · Missing facts: {len(data["missing_facts"])}. Nothing submitted.')

    def show_revision(self,index):
        rev=self.versions.itemData(index)
        if rev:
            self.saved_preview.setPlainText(rev['content']+'\n\nSources:\n'+'\n'.join(rev['sources'])+
                '\n\nMissing facts:\n'+'\n'.join(rev['missing_facts'])+
                '\n\nReview: '+rev['review_status']+'\n'+rev['review_note']+'\nHash: '+rev['content_hash'])

    def result(self,operation,payload,error):
        self.pending=False; self.choose.setEnabled(True); self.tabs.setEnabled(True)
        for button in self.action_buttons: button.setEnabled(True)
        if error: self.notice.setText(error+' Your unsaved text is preserved. Reload to resolve stale revisions.'); return
        if operation=='draft_list':
            if payload['responsibility_id']!=self.rid: return
            self.loading=True; self.choose.clear()
            for row in payload['drafts']: self.choose.addItem(row['title']+f' · v{row["version"]}',row['id'])
            self.loading=False
            if self.choose.count(): self.select(0)
            else: self.new(force=True)
        else:
            if payload['responsibility_id']!=self.rid: return
            self.load(payload)
            self.choose.blockSignals(True)
            index=self.choose.findData(payload['id'])
            if index<0: self.choose.addItem(payload['title'],payload['id']); index=self.choose.count()-1
            self.choose.setItemText(index,payload['title']+f' · v{payload["version"]}')
            self.choose.setCurrentIndex(index); self.choose.blockSignals(False)

    def closeEvent(self,event):
        if self.pending or not self.discard(): event.ignore()
        else: event.accept()
