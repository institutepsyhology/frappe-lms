"""Native mirror optimization without dropping callbacks or weakening auth."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import apply_server_contacts as worker
from test_apply_server_contacts import Doc,WorkerTests

METHOD='frappe.core.doctype.user.user.create_contact'


class InlineTests(unittest.TestCase):
    def setup_case(self):
        user=Doc(doctype='User',user_type='Website User',custom_avo_account='mastervision',
            name='test@example.invalid',email='test@example.invalid')
        original=Mock();native=Mock()
        lookup=Mock(return_value=None)
        fake=SimpleNamespace(local=SimpleNamespace(site=worker.destination('mastervision')),
            session=SimpleNamespace(user='Administrator'),enqueue=original,
            get_attr=Mock(side_effect=lambda method:native if method==METHOD else lookup),
            get_all=Mock(return_value=[{'name':'synthetic-contact','user':user.name,'email_id':user.email}]))
        return user,fake,original,native

    def enqueue(self,fake,user,**changes):
        options={'user':user,'ignore_mandatory':True,'now':None,'enqueue_after_commit':True};options.update(changes)
        return fake.enqueue(METHOD,**options)

    def test_native_hook_inline_exactly_once_and_other_jobs_delegate(self):
        user,fake,original,native=self.setup_case();previous=object();fake.local.job=previous
        def check(**kwargs):
            self.assertIs(fake.local.job.kwargs['user'],user)
            self.assertEqual(fake.local.job.method,METHOD)
        native.side_effect=check
        with worker.inline_contact_creation(fake,user,'mastervision'):
            self.enqueue(fake,user)
            fake.enqueue('synthetic.other_job',value=1,enqueue_after_commit=True)
            self.assertIs(fake.local.job,previous)
        self.assertIs(fake.enqueue,original)
        native.assert_called_once_with(user=user,ignore_mandatory=True)
        original.assert_called_once_with('synthetic.other_job',value=1,enqueue_after_commit=True)

    def test_missing_changed_or_duplicate_hook_fails_closed_and_restores(self):
        for case in ('missing','changed','duplicate'):
            user,fake,original,native=self.setup_case()
            with self.subTest(case=case),self.assertRaises(worker.ApplyError):
                with worker.inline_contact_creation(fake,user,'mastervision'):
                    if case=='changed':self.enqueue(fake,user,now=True)
                    if case=='duplicate':self.enqueue(fake,user);self.enqueue(fake,user)
            self.assertIs(fake.enqueue,original);self.assertFalse(hasattr(fake.local,'job'))

    def test_wrong_mirror_or_native_error_restores_context_and_propagates(self):
        for mismatch in (True,False):
            user,fake,original,native=self.setup_case()
            if mismatch:fake.get_all.return_value=[{'user':'foreign@example.invalid','email_id':user.email}]
            else:native.side_effect=ValueError('synthetic native failure')
            with self.assertRaises((worker.ApplyError,ValueError)):
                with worker.inline_contact_creation(fake,user,'mastervision'):self.enqueue(fake,user)
            self.assertIs(fake.enqueue,original);self.assertFalse(hasattr(fake.local,'job'))

    def test_existing_contact_and_duplicate_mirror_fail_before_commit(self):
        for case in ('existing','duplicate'):
            user,fake,original,native=self.setup_case()
            if case=='existing':fake.get_attr.side_effect=lambda method:native if method==METHOD else lambda _: 'existing-manual-contact'
            else:fake.get_all.return_value*=2
            with self.assertRaises(worker.ApplyError):
                with worker.inline_contact_creation(fake,user,'mastervision'):self.enqueue(fake,user)
            if case=='existing':native.assert_not_called()
            self.assertIs(fake.enqueue,original)

    def test_only_private_single_thread_mv_website_creation_can_opt_in(self):
        for case in ('account','site','actor','thread','user_type'):
            user,fake,original,native=self.setup_case();account='mastervision'
            if case=='account':account='iomp'
            if case=='site':fake.local.site='my-lk.mv-centr.ru'
            if case=='actor':fake.session.user='not-admin@example.invalid'
            if case=='user_type':user['user_type']='System User'
            with patch.object(worker.threading,'active_count',return_value=2 if case=='thread' else 1),self.assertRaises(worker.ApplyError):
                with worker.inline_contact_creation(fake,user,account):pass
            self.assertIs(fake.enqueue,original);native.assert_not_called()

    def test_foreign_user_enqueue_is_never_intercepted(self):
        user,fake,original,native=self.setup_case();foreign=object()
        with self.assertRaisesRegex(worker.ApplyError,'^native_contact_hook_missing$'):
            with worker.inline_contact_creation(fake,user,'mastervision'):self.enqueue(fake,foreign)
        native.assert_not_called();self.assertIs(original.call_args.kwargs['user'],foreign)

    def test_native_mirror_and_password_failure_rollback_same_transaction(self):
        helper=WorkerTests()
        for fail in ('mirror','password'):
            decision,db,fake,modules,calls=helper.setup_user()
            original=Mock();fake.enqueue=original
            fake.get_attr=lambda method:(lambda **kwargs:None) if method==METHOD else lambda _:None
            fake.get_all=lambda *args,**kwargs:[{'name':'mirror','user':db.doc.name,'email_id':db.doc.email}]
            def insert(doc):
                if fail=='mirror':fake.get_all=lambda *args,**kwargs:[]
                self.enqueue(fake,doc)
            modules['lms.lms.avo_user_import']._insert_imported_user=insert
            if fail=='password':modules['lms.lms.support_credentials'].store_new_user_password=lambda *_:(_ for _ in ()).throw(ValueError('synthetic'))
            with patch.dict(worker.sys.modules,modules),self.assertRaises((worker.ApplyError,ValueError)):
                worker.insert_one(fake,decision,'mastervision',inline_contacts=True)
            self.assertEqual(db.events,['begin','rollback']);self.assertIs(fake.enqueue,original)


if __name__=='__main__':unittest.main()
