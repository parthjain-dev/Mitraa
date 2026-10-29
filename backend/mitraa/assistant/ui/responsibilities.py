"""Local responsibility desk and reminder inbox; no provider required."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from PySide6.QtCore import QObject, Signal, Qt, QTimer, QDateTime, QTimeZone
from PySide6.QtWidgets import (QApplication, QDialog, QWidget, QLabel, QPushButton, QLineEdit, QPlainTextEdit,
    QComboBox, QCheckBox, QDateTimeEdit, QTimeEdit, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QSplitter, QMessageBox, QDialogButtonBox, QScrollArea, QFrame)

STATES = ['captured', 'planned', 'active', 'waiting_for_user', 'waiting_external',
          'ready_for_review', 'completed', 'paused', 'cancelled']
STYLE = '''
QDialog, QWidget { background:#101e25; color:#dce9ec; font-family:"Segoe UI"; font-size:12px; }
QLineEdit, QPlainTextEdit, QComboBox, QDateTimeEdit, QTimeEdit, QTreeWidget {
 background:#172b34; border:1px solid #35515c; border-radius:5px; padding:5px; selection-background-color:#245e68; }
QPushButton { background:#1e414c; border:1px solid #3b6571; border-radius:6px; padding:7px 12px; }
QPushButton:hover { background:#285560; } QPushButton:disabled { color:#71858b; }
QHeaderView::section { background:#1e353f; color:#c3dadd; padding:6px; border:0; }
QTabBar::tab { padding:8px 12px; background:#172b34; } QTabBar::tab:selected { background:#265361; }
QLabel#notice { color:#efc58b; } QSplitter::handle { background:#29414b; }
QScrollBar:vertical { background:#142831; width:8px; margin:0; }
QScrollBar:horizontal { background:#142831; height:8px; margin:0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background:#41636d; border-radius:4px; min-height:24px; min-width:24px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
'''


def display_time(value, zone):
    if not value:
        return '—'
    return datetime.fromisoformat(value).astimezone(ZoneInfo(zone)).strftime('%d %b %Y, %H:%M')


def wall_instant(editor, zone):
    """Reject ambiguous/nonexistent DST wall times rather than guess an instant."""
    z = ZoneInfo(zone)
    date, time = editor.date(), editor.time()
    naive = datetime(date.year(), date.month(), date.day(), time.hour(), time.minute())
    candidates = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=z, fold=fold)
        back = aware.astimezone(timezone.utc).astimezone(z)
        if back.replace(tzinfo=None) == naive:
            candidates.append(aware)
    if not candidates:
        raise ValueError('This time does not exist because the clocks change. Choose another time.')
    if len({item.utcoffset() for item in candidates}) > 1:
        raise ValueError('This time occurs twice because the clocks change. Use UTC or choose another time.')
    return candidates[0].astimezone(timezone.utc).isoformat()


def date_editor():
    editor = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
    editor.setDisplayFormat('dd MMM yyyy, HH:mm'); editor.setCalendarPopup(True)
    return editor


class ProviderDialog(QDialog):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime; self.setWindowTitle('Mitraa · AI connection'); self.setStyleSheet(STYLE)
        self.resize(560, 340)
        layout = QVBoxLayout(self)
        label = QLabel('Responsibilities and reminders work locally without an AI connection.\n'
            'Chat uses the selected provider and sends it task context.\n'
            'Credentials are saved in this installation’s local .env file.'); label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout(); layout.addLayout(form)
        self.endpoint = QLineEdit(); self.endpoint.setPlaceholderText('https://…/v1/')
        self.model = QLineEdit(); self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText('API key; leave blank to keep a saved key')
        form.addRow('Provider endpoint', self.endpoint); form.addRow('Model ID', self.model); form.addRow('API key', self.key)
        self.notice = QLabel('Loading connection status…'); self.notice.setWordWrap(True); self.notice.setObjectName('notice')
        layout.addWidget(self.notice)
        self.save_button = QPushButton('Save connection'); self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)

    def open_settings(self):
        self.show(); self.raise_(); self.activateWindow(); self.runtime.worker.submit('provider_status')

    def save(self):
        self.save_button.setEnabled(False)
        self.runtime.worker.submit('provider_save', base_url=self.endpoint.text(),
            model=self.model.text(), api_key=self.key.text())

    def result(self, operation, payload, error):
        self.save_button.setEnabled(True)
        if error:
            self.notice.setText(error); return
        self.key.clear()
        if operation == 'provider_status':
            self.endpoint.setText(payload['base_url']); self.model.setText(payload['model'])
        self.notice.setText(('Settings saved. ' if operation == 'provider_save' else '') +
            ('AI connection configured; it has not been tested with a live request.' if payload['configured']
             else 'AI not configured. Missing: ' + ', '.join(payload['missing'])) +
            (' Environment settings override values saved here.' if payload['environment_override'] else ''))


class ReminderDialog(QDialog):
    def __init__(self, runtime, item, reminder_id=None):
        super().__init__(runtime.desk)
        self.runtime = runtime; self.item = item; self.reminder_id = reminder_id
        self.setWindowTitle('Snooze reminder' if reminder_id else 'Add follow-up')
        layout = QFormLayout(self)
        self.message = QLineEdit(item.get('next_action') or item['title'])
        self.message.setMaxLength(500)
        self.zone = QLineEdit(item.get('timezone') or runtime.timezone)
        self.when = date_editor()
        local = datetime.now(ZoneInfo(self.zone.text())) + timedelta(hours=1)
        self.when.setDateTime(QDateTime.fromString(local.strftime('%Y-%m-%dT%H:%M:%S'),'yyyy-MM-ddTHH:mm:ss'))
        layout.addRow('Follow-up', self.message); layout.addRow('Timezone', self.zone); layout.addRow('Remind at', self.when)
        self.notice = QLabel('Reminders appear while Mitraa runs; missed times catch up on restart.')
        self.notice.setWordWrap(True); layout.addRow(self.notice)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addRow(buttons)

    def save(self):
        try:
            instant = wall_instant(self.when, self.zone.text().strip())
            if datetime.fromisoformat(instant) <= datetime.now(timezone.utc):
                raise ValueError('Choose a future reminder time.')
            if not self.message.text().strip():
                raise ValueError('Enter a reminder message.')
        except (ValueError, KeyError) as exc:
            self.notice.setText(str(exc)); return
        if self.reminder_id:
            self.runtime.worker.submit('reminder_action', reminder_id=self.reminder_id,
                                       action='snooze', due_at=datetime.fromisoformat(instant))
        else:
            self.runtime.worker.submit('add_reminder', responsibility_id=self.item['id'],
                                       message=self.message.text().strip(), due_at=instant)
        self.accept()


class ResponsibilityDesk(QDialog):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime; self.items = {}; self.selected_id = None; self.version = None
        self.loading = False; self.dirty = False; self.pending_save = False
        self.setWindowTitle('Mitraa · My responsibilities'); self.setStyleSheet(STYLE)
        self.resize(1060, 760); self.setMinimumSize(800, 620)
        layout = QVBoxLayout(self)
        header = QHBoxLayout(); title = QLabel('My responsibilities'); title.setStyleSheet('font-size:20px;font-weight:600;')
        header.addWidget(title); header.addStretch()
        for label, callback in [('New responsibility', self.new), ('Refresh', self.refresh_view),
                                ('AI connection', runtime.open_provider), ('Token usage',runtime.open_usage)]:
            button = QPushButton(label); button.clicked.connect(callback); header.addWidget(button)
        layout.addLayout(header)
        self.notice = QLabel('Saved on this PC. Reminders need Mitraa running; missed times catch up when it resumes.')
        self.notice.setObjectName('notice'); self.notice.setWordWrap(True); layout.addWidget(self.notice)
        self.connection_label=QLabel('Local tracking is available. Checking AI configuration…')
        self.connection_label.setWordWrap(True); layout.addWidget(self.connection_label)
        splitter = QSplitter(); layout.addWidget(splitter, 1)
        left = QWidget(); column = QVBoxLayout(left); column.setContentsMargins(0,0,6,0)
        self.tabs = QTabWidget(); self.trees = []
        for label in ['Needs you', 'Ready for review', 'Coming up', 'All']:
            tree = QTreeWidget(); tree.setHeaderLabels(['Responsibility', 'Status', 'Deadline'])
            tree.setRootIsDecorated(False); tree.setColumnWidth(0,210); tree.setColumnWidth(1,130)
            tree.itemClicked.connect(self.select_item); self.tabs.addTab(tree, label); self.trees.append(tree)
        column.addWidget(self.tabs); splitter.addWidget(left)
        right = QWidget(); self.editor=right; form_column = QVBoxLayout(right); form_column.setContentsMargins(6,0,0,0)
        form = QFormLayout(); form_column.addLayout(form)
        self.title = QLineEdit(); self.title.setMaxLength(200)
        self.outcome = QPlainTextEdit(); self.outcome.setMaximumHeight(65)
        self.next_action = QLineEdit(); self.notes = QPlainTextEdit(); self.notes.setMaximumHeight(65)
        self.sources = QPlainTextEdit(); self.sources.setMaximumHeight(55)
        self.sources.setPlaceholderText('One reference per line; text only, no automatic file access')
        self.state = QComboBox(); self.state.addItems(STATES)
        self.priority = QComboBox(); self.priority.addItems(['low','medium','high','critical']); self.priority.setCurrentText('medium')
        self.zone = QLineEdit(runtime.timezone)
        self.has_deadline = QCheckBox('Set deadline'); self.deadline = date_editor(); self.deadline.setEnabled(False)
        deadline_row = QHBoxLayout(); deadline_row.addWidget(self.has_deadline); deadline_row.addWidget(self.deadline)
        self.has_deadline.toggled.connect(self.deadline.setEnabled)
        self.confirmation = QLineEdit(); self.confirmation.setPlaceholderText('How did you confirm the desired outcome is complete?')
        for label, field in [('Title',self.title), ('Desired outcome',self.outcome), ('Next action',self.next_action),
                             ('Status',self.state), ('Priority',self.priority), ('Timezone',self.zone)]:
            form.addRow(label,field)
        form.addRow(deadline_row)
        form.addRow('Notes',self.notes); form.addRow('Sources',self.sources); form.addRow('Completion confirmation',self.confirmation)
        row = QHBoxLayout(); self.save_button = QPushButton('Save responsibility'); self.save_button.clicked.connect(self.save)
        self.follow_button = QPushButton('Add follow-up'); self.follow_button.clicked.connect(self.add_follow_up)
        self.forget_button = QPushButton('Forget…'); self.forget_button.clicked.connect(self.forget)
        self.drafts_button = QPushButton('Drafts & review'); self.drafts_button.clicked.connect(self.open_drafts)
        for button in [self.save_button,self.follow_button,self.forget_button]: row.addWidget(button)
        form_column.addLayout(row)
        form_column.addWidget(self.drafts_button)
        self.jobs_button=QPushButton('Coding jobs'); self.jobs_button.clicked.connect(self.open_jobs)
        form_column.addWidget(self.jobs_button)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); self.history.setMaximumHeight(95)
        form_column.addWidget(QLabel('Activity')); form_column.addWidget(self.history)
        editor_scroll=QScrollArea(); editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.NoFrame); editor_scroll.setWidget(right)
        splitter.addWidget(editor_scroll); splitter.setSizes([480,560])
        reminder_header = QHBoxLayout()
        reminder_label=QLabel('Follow-up inbox · acknowledgement closes the reminder, not the responsibility')
        reminder_label.setWordWrap(True); reminder_header.addWidget(reminder_label)
        reminder_header.addStretch()
        for label, callback in [('Acknowledge',lambda:self.reminder_action('acknowledge')),
                                ('Snooze…',self.snooze), ('Cancel reminder',lambda:self.reminder_action('cancel')),
                                ('Quiet hours',self.quiet_hours)]:
            button = QPushButton(label); button.clicked.connect(callback); reminder_header.addWidget(button)
        layout.addLayout(reminder_header)
        self.reminders = QTreeWidget(); self.reminders.setRootIsDecorated(False)
        self.reminders.setHeaderLabels(['Responsibility','Follow-up','Time','Status'])
        self.reminders.setMinimumHeight(105); self.reminders.setMaximumHeight(155)
        self.reminders.setColumnWidth(0,220); self.reminders.setColumnWidth(1,350); self.reminders.setColumnWidth(2,180)
        layout.addWidget(self.reminders)
        for field in [self.title,self.next_action,self.zone,self.confirmation]: field.textChanged.connect(self.edited)
        for field in [self.outcome,self.notes,self.sources]: field.textChanged.connect(self.edited)
        self.state.currentTextChanged.connect(self.edited); self.priority.currentTextChanged.connect(self.edited)
        self.deadline.dateTimeChanged.connect(self.edited); self.has_deadline.toggled.connect(self.edited)
        self.new()

    def edited(self, *_):
        if not self.loading: self.dirty = True

    def open_drafts(self):
        if not self.selected_id or self.dirty:
            self.notice.setText('Save or refresh the responsibility before opening drafts.'); return
        item=self.items[self.selected_id]
        if item['status'] in {'completed','cancelled'}:
            self.notice.setText('Reopen this responsibility before preparing work.'); return
        self.runtime.open_drafts(item)

    def open_jobs(self):
        if not self.selected_id or self.dirty:
            self.notice.setText('Save the responsibility before opening coding jobs.');return
        self.runtime.open_jobs(self.items[self.selected_id])

    def refresh_view(self):
        if self.pending_save or not self.can_discard(): return
        self.dirty=False
        self.runtime.refresh()
        if self.selected_id: self.runtime.worker.submit('detail',id=self.selected_id)

    def can_discard(self):
        return not self.dirty or QMessageBox.question(self, 'Unsaved changes', 'Discard your unsaved changes?',
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel) == QMessageBox.Discard

    def new(self):
        if self.pending_save: return
        if not self.can_discard(): return
        self.loading=True; self.selected_id=None; self.version=None
        for field in [self.title,self.next_action,self.confirmation]: field.clear()
        for field in [self.outcome,self.notes,self.sources,self.history]: field.clear()
        self.state.setCurrentText('captured'); self.state.setEnabled(False)
        self.priority.setCurrentText('medium'); self.zone.setText(self.runtime.timezone)
        self.has_deadline.setChecked(False)
        self.follow_button.setEnabled(False); self.forget_button.setEnabled(False)
        self.loading=False; self.dirty=False

    def select_item(self, tree_item, _column):
        if self.pending_save: return
        rid = tree_item.data(0,Qt.UserRole)
        if rid == self.selected_id or not self.can_discard(): return
        self.load_item(self.items[rid]); self.runtime.worker.submit('detail',id=rid)

    def load_item(self,item):
        self.loading=True; self.selected_id=item['id']; self.version=item['version']
        self.title.setText(item['title']); self.outcome.setPlainText(item['outcome']); self.next_action.setText(item['next_action'])
        self.notes.setPlainText(item['notes']); self.sources.setPlainText('\n'.join(item['sources']))
        self.state.setEnabled(True); self.state.setCurrentText(item['status']); self.priority.setCurrentText(item['priority'])
        self.zone.setText(item['timezone']); self.confirmation.setText(item['completion_note'])
        self.has_deadline.setChecked(bool(item['deadline']))
        if item['deadline']:
            local=datetime.fromisoformat(item['deadline']).astimezone(ZoneInfo(item['timezone']))
            self.deadline.setDateTime(QDateTime.fromString(local.strftime('%Y-%m-%dT%H:%M:%S'),'yyyy-MM-ddTHH:mm:ss'))
        self.follow_button.setEnabled(item['status'] not in {'completed','cancelled'})
        self.forget_button.setEnabled(True); self.loading=False; self.dirty=False

    def save(self):
        try:
            from mitraa.responsibilities.schemas import ResponsibilityCreate, ResponsibilityPatch
            data = dict(title=self.title.text(),outcome=self.outcome.toPlainText(),next_action=self.next_action.text(),
                notes=self.notes.toPlainText(),sources=self.sources.toPlainText().splitlines(),priority=self.priority.currentText(),
                timezone=self.zone.text().strip(),deadline=wall_instant(self.deadline,self.zone.text().strip()) if self.has_deadline.isChecked() else None)
            ResponsibilityCreate.model_validate(data)
            if self.selected_id:
                data.update(expected_version=self.version,status=self.state.currentText(),completion_note=self.confirmation.text())
                ResponsibilityPatch.model_validate(data)
                if data['status']=='completed' and not data['completion_note'].strip():
                    raise ValueError('Explain how you confirmed completion before saving.')
                operation='patch'; arguments={'id':self.selected_id,'data':data}
            else:
                operation='create'; arguments={'data':data}
        except (ValueError,KeyError) as exc:
            self.notice.setText(str(exc)); return
        self.pending_save=True; self.editor.setEnabled(False)
        self.runtime.worker.submit(operation,**arguments)

    def apply_snapshot(self,payload):
        self.items={item['id']:item for item in payload['responsibilities']}
        for tree in self.trees: tree.clear()
        for item in self.items.values():
            groups=[3]
            if item['status']=='waiting_for_user' or (item['status']=='captured' and not item['next_action']): groups.append(0)
            if item['status']=='ready_for_review': groups.append(1)
            if item['status'] not in {'completed','cancelled','paused'}: groups.append(2)
            for group in groups:
                leaf=QTreeWidgetItem([item['title'],item['status'].replace('_',' '),display_time(item['deadline'],item['timezone'])])
                leaf.setData(0,Qt.UserRole,item['id']); self.trees[group].addTopLevelItem(leaf)
                if item['id']==self.selected_id: leaf.setSelected(True)
        self.reminders.clear()
        for reminder in payload['reminders']:
            if reminder['status'] not in {'scheduled','due'}: continue
            item=self.items.get(reminder['responsibility_id'])
            if not item: continue
            leaf=QTreeWidgetItem([item['title'],reminder['message'],display_time(reminder['due_at'],payload['preferences']['timezone']),
                'Paused' if item['status']=='paused' else reminder['status']])
            leaf.setData(0,Qt.UserRole,reminder); self.reminders.addTopLevelItem(leaf)
        if self.selected_id in self.items and not self.dirty:
            self.load_item(self.items[self.selected_id])
        elif self.selected_id and self.selected_id not in self.items and not self.dirty:
            self.new()

    def add_follow_up(self):
        if self.selected_id in self.items:
            ReminderDialog(self.runtime,self.items[self.selected_id]).exec()

    def chosen_reminder(self):
        leaf=self.reminders.currentItem()
        if not leaf:
            self.notice.setText('Select a follow-up in the inbox first.'); return None
        return leaf.data(0,Qt.UserRole)

    def reminder_action(self,action):
        reminder=self.chosen_reminder()
        if reminder:
            self.runtime.worker.submit('reminder_action',reminder_id=reminder['id'],action=action)

    def snooze(self):
        reminder=self.chosen_reminder()
        if reminder:
            ReminderDialog(self.runtime,self.items[reminder['responsibility_id']],reminder['id']).exec()

    def forget(self):
        if self.selected_id and QMessageBox.warning(self,'Forget responsibility',
            'Permanently remove this responsibility, drafts, coding-job records, reminders and activity? '
            'Isolated coding output folders remain on disk; remove them manually when no longer needed. This cannot be undone.',
            QMessageBox.Yes | QMessageBox.Cancel,QMessageBox.Cancel)==QMessageBox.Yes:
            self.dirty=False
            self.runtime.worker.submit('forget',id=self.selected_id,expected_version=self.version)

    def quiet_hours(self):
        prefs=self.runtime.snapshot.get('preferences',{})
        dialog=QDialog(self); dialog.setWindowTitle('Follow-up preferences'); form=QFormLayout(dialog)
        zone=QLineEdit(prefs.get('timezone',self.runtime.timezone))
        enabled=QCheckBox('Enable quiet hours'); enabled.setChecked(prefs.get('quiet_enabled',True))
        notify=QCheckBox('Show desktop notification summaries'); notify.setChecked(prefs.get('notifications_enabled',True))
        start=QTimeEdit(); end=QTimeEdit()
        from PySide6.QtCore import QTime
        start.setDisplayFormat('HH:mm'); end.setDisplayFormat('HH:mm')
        start.setTime(QTime.fromString(prefs.get('quiet_start','22:00'),'HH:mm'))
        end.setTime(QTime.fromString(prefs.get('quiet_end','08:00'),'HH:mm'))
        form.addRow('Timezone',zone); form.addRow(enabled); form.addRow('Start',start); form.addRow('End',end); form.addRow(notify)
        notice=QLabel('Quiet hours suppress popups, not the inbox. Equal start/end disables quiet hours.'); notice.setWordWrap(True); form.addRow(notice)
        buttons=QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); form.addRow(buttons)
        def save():
            try:
                from mitraa.responsibilities.schemas import Preferences
                data=Preferences(timezone=zone.text().strip(),quiet_enabled=enabled.isChecked(),quiet_start=start.time().toString('HH:mm'),
                    quiet_end=end.time().toString('HH:mm'),notifications_enabled=notify.isChecked())
            except ValueError as exc:
                notice.setText(str(exc)); return
            self.runtime.worker.submit('preferences',**data.model_dump()); dialog.accept()
        buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject); dialog.exec()

    def closeEvent(self,event):
        if self.can_discard():
            self.dirty=False
            if self.selected_id in self.items:
                self.load_item(self.items[self.selected_id])
            elif self.selected_id is None:
                self.new()
            event.accept()
        else: event.ignore()


class ReminderAlert(QDialog):
    """Non-modal local alert; closing never acknowledges a reminder."""
    dismissed = Signal()

    def __init__(self, runtime):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.runtime = runtime
        self.reminder_id = None
        self.setWindowTitle('Mitraa · Reminder')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self.setFixedWidth(390)
        layout = QVBoxLayout(self)
        self.heading = QLabel('Follow-up due'); layout.addWidget(self.heading)
        self.message = QLabel(); self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText); layout.addWidget(self.message)
        self.notice = QLabel(); self.notice.setWordWrap(True); layout.addWidget(self.notice)
        row = QHBoxLayout(); layout.addLayout(row)
        self.ack = QPushButton('Acknowledge')
        self.snooze = QPushButton('Snooze 10 min')
        self.open_button = QPushButton('Open')
        for button in (self.ack, self.snooze, self.open_button): row.addWidget(button)
        self.ack.clicked.connect(lambda: self.act('acknowledge'))
        self.snooze.clicked.connect(lambda: self.act('snooze'))
        self.open_button.clicked.connect(runtime.open)

    def act(self, action):
        if not self.reminder_id or not self.ack.isEnabled(): return
        self.ack.setEnabled(False); self.snooze.setEnabled(False)
        args = dict(reminder_id=self.reminder_id, action=action)
        if action == 'snooze': args['due_at'] = datetime.now(timezone.utc)+timedelta(minutes=10)
        self.runtime.worker.submit('reminder_action', **args)

    def present(self, reminder, count):
        self.reminder_id = reminder['id']
        self.heading.setText(f'Follow-up due · {count} pending')
        self.message.setText(reminder['title']+'\n'+reminder['message'])
        self.notice.setText('Closing this alert leaves the reminder in your inbox.')
        self.ack.setEnabled(True); self.snooze.setEnabled(True)
        self.adjustSize()
        area = QApplication.primaryScreen().availableGeometry()
        self.move(max(area.left(), area.right()-self.width()-16),
                  max(area.top(), area.bottom()-self.height()-16))
        self.show()  # no activateWindow/focus stealing during voice or typing

    def reject(self):
        self.hide(); self.dismissed.emit()

    def closeEvent(self, event):
        self.dismissed.emit(); super().closeEvent(event)


class DeskRuntime(QObject):
    result = Signal(str,object,str)

    def __init__(self,tray,controller,worker=None,factory=None):
        super().__init__()
        from mitraa.assistant.follow_up import FollowUpWorker
        self.timezone=bytes(QTimeZone.systemTimeZoneId()).decode() or 'UTC'
        try: ZoneInfo(self.timezone)
        except (ValueError,KeyError): self.timezone='UTC'
        self.tray=tray; self.controller=controller; self.snapshot={}; self.closed=False
        self.notification_inflight=set()
        self.alert_seen=set()
        self.drafts=None
        self.usage_dialog=None
        self.jobs=None
        self.result.connect(self.handle,Qt.QueuedConnection)
        self.worker=worker or FollowUpWorker(lambda op,data,error:self.result.emit(op,data,error),self.timezone,factory)
        from mitraa.assistant.coding_worker import CodingWorker
        self.coder=CodingWorker(lambda op,data,error:self.result.emit(op,data,error),factory=factory)
        self.desk=ResponsibilityDesk(self); self.provider=ProviderDialog(self)
        self.alert=ReminderAlert(self)
        self.alert.dismissed.connect(self.dismiss_alert)
        self.timer=QTimer(self); self.timer.setInterval(15000); self.timer.timeout.connect(self.refresh); self.timer.start()
        tray.messageClicked.connect(self.open)
        self.refresh()
        self.worker.submit('provider_status')
        self.worker.submit('job_recover')

    def refresh(self):
        self.worker.submit('snapshot')

    def open(self):
        self.desk.show(); self.desk.raise_(); self.desk.activateWindow(); self.refresh()

    def open_provider(self):
        self.provider.open_settings()

    def open_usage(self):
        if self.usage_dialog is None:
            from mitraa.assistant.ui.usage import UsageDialog
            self.usage_dialog=UsageDialog(self)
        self.usage_dialog.load()

    def open_drafts(self,item):
        if self.drafts is None:
            from mitraa.assistant.ui.drafts import DraftDesk
            self.drafts=DraftDesk(self)
        self.drafts.open_for(item)

    def open_jobs(self,item):
        if self.jobs is None:
            from mitraa.assistant.ui.jobs import JobDesk
            self.jobs=JobDesk(self)
        self.jobs.open_for(item)

    def handle(self,operation,payload,error):
        if self.closed: return
        if operation=='job_changed':
            if self.jobs and self.jobs.current and self.jobs.current['id']==payload['id']:self.jobs.refresh()
            return
        if operation.startswith('job_'):
            if operation!='job_recover' and self.jobs:self.jobs.result(operation,payload,error)
            return
        if operation=='usage':
            if self.usage_dialog: self.usage_dialog.result(payload,error)
            return
        if operation.startswith('draft_'):
            if self.drafts: self.drafts.result(operation,payload,error)
            if not error:
                self.refresh()
                if self.desk.selected_id: self.worker.submit('detail',id=self.desk.selected_id)
            return
        if operation.startswith('provider_'):
            self.provider.result(operation,payload,error)
            if not error:
                self.desk.connection_label.setText('Local tracking available · AI settings configured (connection not tested)'
                    if payload['configured'] else 'Local tracking available · AI chat needs a provider. Open AI connection to configure it.')
            if operation=='provider_save' and not error and self.controller.worker:
                self.controller.worker.reload_configuration()
            return
        if error:
            if operation=='notified': self.notification_inflight.clear()
            self.desk.notice.setText(error)
            if operation=='reminder_action' and self.alert.isVisible():
                self.alert.notice.setText(error)
                self.alert.ack.setEnabled(True); self.alert.snooze.setEnabled(True)
            if operation in {'create','patch'}:
                self.desk.pending_save=False; self.desk.editor.setEnabled(True)
            return
        if operation=='detail':
            if payload['id']==self.desk.selected_id:
                self.desk.history.setPlainText('\n'.join(display_time(e['created_at'],self.timezone)+' · '+e['kind'].replace('_',' ')
                    + (' · '+e['details']['completion_note'] if e['details'].get('completion_note') else '') for e in payload['history']))
            return
        if operation in {'create','patch'}:
            self.desk.dirty=False; self.desk.pending_save=False; self.desk.editor.setEnabled(True)
            self.desk.notice.setText('Saved on this PC.')
            if operation=='create' and payload['responsibilities']:
                self.desk.load_item(payload['responsibilities'][0])
        self.snapshot=payload; self.desk.apply_snapshot(payload)
        self.update_alert(payload)
        # Successful delivery and snoozing release the in-flight guard so a
        # later snooze occurrence can notify again using the same reminder ID.
        self.notification_inflight.intersection_update(r['id'] for r in payload['notify'])
        if operation in {'create','patch'} and self.desk.selected_id:
            self.worker.submit('detail',id=self.desk.selected_id)
        candidates=[r for r in payload['notify'] if r['id'] not in self.notification_inflight]
        if candidates and self.tray.isSystemTrayAvailable() and self.tray.supportsMessages():
            # Keep personal titles/messages out of lock-screen-visible notifications.
            self.tray.showMessage('Mitraa · Follow-up',f'{len(candidates)} follow-up(s) need your attention. Open My responsibilities to review.')
            ids=[r['id'] for r in candidates]; self.notification_inflight.update(ids)
            self.worker.submit('notified',ids=ids)

    def dismiss_alert(self):
        for row in self.snapshot.get('due',[]):
            self.alert_seen.add((row['id'],row['due_at']))

    def update_alert(self, payload):
        from mitraa.responsibilities.service import is_quiet
        from mitraa.responsibilities.schemas import Preferences
        prefs=Preferences.model_validate(payload['preferences'])
        due=payload['due']
        keys={(row['id'],row['due_at']) for row in due}
        self.alert_seen.intersection_update(keys)
        if not prefs.notifications_enabled or is_quiet(prefs,datetime.now(timezone.utc)):
            self.alert.hide(); return
        candidates=[r for r in due if (r['id'],r['due_at']) not in self.alert_seen]
        if not candidates:
            self.alert.hide(); return
        # Deliberately independent of notified_at: an OS request is not delivery.
        # Retain the card across polls until acted on or dismissed this session.
        current=next((r for r in candidates if r['id']==self.alert.reminder_id),None)
        if current and self.alert.isVisible(): return
        self.alert.present(candidates[0],len(due))

    def shutdown(self):
        self.closed=True; self.timer.stop(); self.worker.shutdown()
        self.coder.shutdown()
        self.alert.close()
        if self.usage_dialog: self.usage_dialog.close()
        if self.jobs: self.jobs.close()
        if self.drafts:
            self.drafts.dirty=False; self.drafts.pending=False; self.drafts.close()
        # Application exit must not open a discard prompt.
        self.desk.dirty=False; self.desk.close(); self.provider.close()
