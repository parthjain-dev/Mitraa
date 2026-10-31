"""Dedicated local data worker, independent of cloud requests and voice loading."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class FollowUpWorker:
    def __init__(self, post, timezone='UTC', factory=None):
        self.post = post
        self.timezone = timezone
        self.factory = factory
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mitraa-follow-up')
        self.closing = False
        self._poll_lock = threading.Lock()
        self._poll_pending = False

    def submit(self, operation, **arguments):
        if self.closing:
            return
        if operation == 'snapshot':
            with self._poll_lock:
                if self._poll_pending:
                    return
                self._poll_pending = True
        self.pool.submit(self._run, operation, arguments)

    def _run(self, operation, arguments):
        try:
            from mitraa.responsibilities import service
            from mitraa.responsibilities.schemas import ResponsibilityCreate, ResponsibilityPatch, ReminderCreate, Preferences
            if operation == 'provider_status':
                from mitraa.assistant.provider_config import status
                result = status()
            elif operation == 'provider_save':
                from mitraa.assistant.provider_config import save
                result = save(**arguments)
            elif operation == 'usage':
                from mitraa.usage import summary
                if self.factory is None:
                    from mitraa.db.session import default_session_factory
                    self.factory=default_session_factory()
                with self.factory() as session: result=summary(session)
            else:
                if self.factory is None:
                    from mitraa.db.session import default_session_factory
                    self.factory = default_session_factory()
                with self.factory() as session:
                    # Establish machine timezone before other operations can create preferences.
                    service.preferences(session, self.timezone)
                    if operation.startswith('job_'):
                        from mitraa.responsibilities import jobs
                        if operation=='job_create':
                            from mitraa.config import get_settings
                            result=jobs.create(session,jobs.JobCreate.model_validate(arguments['data']),get_settings())
                        elif operation=='job_list': result={'responsibility_id':arguments['rid'],'jobs':jobs.list_jobs(session,arguments['rid'])}
                        elif operation=='job_detail': result=jobs.as_dict(jobs.row(session,arguments['id']))
                        elif operation=='job_cancel': result=jobs.cancel(session,arguments['id'],arguments['version'])
                        elif operation=='job_accept': result=jobs.accept(session,arguments['id'],arguments['version'],arguments['note'],arguments['confirmed'])
                        elif operation=='job_apply':
                            from mitraa.config import get_settings
                            result=jobs.apply_to_workspace(session,arguments['id'],arguments['version'],arguments['confirmed'],get_settings())
                        elif operation=='job_recover': jobs.recover(session); result={}
                        else: raise ValueError('Unknown coding job operation.')
                        session.commit()
                        if not self.closing: self.post(operation,result,'')
                        return
                    if operation.startswith('draft_'):
                        from mitraa.responsibilities import drafts
                        if operation=='draft_list':
                            result={'responsibility_id':arguments['rid'],'drafts':drafts.list_drafts(session,arguments['rid'])}
                        elif operation=='draft_detail': result=drafts.detail(session,arguments['id'])
                        elif operation=='draft_create': result=drafts.create(session,arguments['rid'],drafts.DraftContent.model_validate(arguments['data']))
                        elif operation=='draft_checklist': result=drafts.checklist(session,arguments['rid'])
                        elif operation=='draft_save': result=drafts.revise(session,arguments['id'],drafts.DraftUpdate.model_validate(arguments['data']))
                        elif operation=='draft_review': result=drafts.review(session,arguments['id'],drafts.DraftReview.model_validate(arguments['data']))
                        else: raise ValueError('Unknown draft operation.')
                        session.commit()
                        if not self.closing: self.post(operation,result,'')
                        return
                    if operation == 'create':
                        item = service.create(session, ResponsibilityCreate.model_validate(arguments['data']))
                        if arguments.get('reminder'):
                            service.add_reminder(session, ReminderCreate(responsibility_id=item['id'],
                                **arguments['reminder']))
                    elif operation == 'patch':
                        service.patch(session, arguments['id'], ResponsibilityPatch.model_validate(arguments['data']))
                    elif operation == 'forget':
                        service.forget(session, arguments['id'], arguments['expected_version'])
                    elif operation == 'add_reminder':
                        service.add_reminder(session, ReminderCreate.model_validate(arguments))
                    elif operation == 'reminder_action':
                        service.change_reminder(session, **arguments)
                    elif operation == 'preferences':
                        service.save_preferences(session, Preferences.model_validate(arguments))
                    elif operation == 'notified':
                        service.mark_notified(session, arguments['ids'])
                    elif operation == 'detail':
                        result = {'id': arguments['id'], 'history': service.history(session, arguments['id'])}
                        session.commit()
                        if not self.closing:
                            self.post(operation, result, '')
                        return
                    elif operation != 'snapshot':
                        raise ValueError('Unknown local operation.')
                    result = {**service.poll(session, default_timezone=self.timezone),
                              'responsibilities': service.list_items(session),
                              'reminders': service.list_reminders(session)}
                    session.commit()
            if not self.closing:
                self.post(operation, result, '')
        except ValueError as exc:
            if not self.closing:
                self.post(operation, None, str(exc))
        except Exception:
            # Do not include task contents or credentials in logs or UI exceptions.
            logger.error('Local operation %s failed (%s).', operation, 'storage/configuration')
            if not self.closing:
                self.post(operation, None, 'Could not save or load local data. Check disk access and retry.')
        finally:
            if operation == 'snapshot':
                with self._poll_lock:
                    self._poll_pending = False

    def shutdown(self):
        self.closing = True
        self.pool.shutdown(wait=False, cancel_futures=False)
