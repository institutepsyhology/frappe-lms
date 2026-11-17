import copy
import unittest
from mvcentr_contact_plan import plan,matches,PlanError


def row(**changes):
    return dict({'id_contact':'123','name':'Имя','middle_name':'','last_name':'Фамилия',
        'email':'person@example.invalid','password':'SYNTHETIC_PASSWORD','phone_number':'999999999',
        'not_to_write':'0','spam_clicked':'0','ban':'0','telegram_user_id':'17','telegram_user':'name',
        'vk_user_id':'','vk_user':''},**changes)


class ContactPolicyTests(unittest.TestCase):
    def test_each_destination_keeps_its_own_account_and_unknown_accounts_fail(self):
        for account in ('mv-centr','mastervision','iomp'):
            self.assertEqual(plan(row(),email_frequency=1,account=account)['data']['custom_avo_account'],account)
        with self.assertRaisesRegex(PlanError,'^invalid_account$'):
            plan(row(),account='unknown')

    def test_existing_profiles_never_receive_profile_or_password_updates(self):
        for kind in ('User','Contact'):
            result=plan(row(name='',password='DIFFERENT',email='different@example.invalid'),existing_kind=kind)
            self.assertEqual(result,{'action':'existing','optout':0})

    def test_optout_or_combination_and_no_extra_message_sending_fields(self):
        for flags in [('0','1'),('1','0'),('1','1')]:
            result=plan(row(not_to_write=flags[0],spam_clicked=flags[1]),email_frequency=1)
            self.assertEqual(result['data']['custom_no_marketing_email'],1)
            self.assertNotIn('send_welcome_email',result['data'])

    def test_unique_source_email_creates_only_website_import_payload(self):
        original=row(email=' Person@Example.Invalid ')
        before=copy.deepcopy(original)
        result=plan(original,email_frequency=1)
        self.assertEqual(result['action'],'create_user')
        self.assertEqual(result['data']['email'],'person@example.invalid')
        self.assertEqual(result['data']['mobile_no'],'999999999')
        self.assertNotIn('roles',result['data'])
        self.assertEqual(before,original)

    def test_duplicate_email_never_merges_or_autolinks(self):
        for options in ({'email_frequency':2},{'email_frequency':1,'email_taken':True}):
            result=plan(row(),**options)
            self.assertEqual(result['action'],'create_contact')
            self.assertEqual(result['data']['custom_avo_contact_id'],'123')
            self.assertEqual(result['data']['custom_avo_source_email'],'person@example.invalid')
            self.assertEqual(result['data']['email_ids'],[{'email_id':'person@example.invalid','is_primary':1}])
            self.assertNotIn('user',result['data']);self.assertNotIn('new_password',result['data'])

    def test_source_without_password_is_preserved_as_contact_with_original_email(self):
        result=plan(row(password=''),email_frequency=1,account='mastervision')
        self.assertEqual(result['action'],'create_contact')
        self.assertEqual(result['data']['custom_avo_account'],'mastervision')
        self.assertEqual(result['data']['email_ids'][0]['email_id'],'person@example.invalid')

    def test_duplicate_email_readback_checks_native_email_and_rejects_foreign_user(self):
        data=plan(row(),email_frequency=2)['data']
        saved=dict(data,email_id='person@example.invalid',mobile_no='999999999')
        self.assertTrue(matches(saved,data))
        saved['email_ids']=[];self.assertFalse(matches(saved,data))
        saved['email_ids']=data['email_ids'];saved['user']='foreign@example.invalid'
        self.assertFalse(matches(saved,data))

    def test_password_keeps_literal_whitespace_and_new_source_ban_is_explicit(self):
        result=plan(row(password='  SYNTHETIC_PASSWORD  ',ban='1'),email_frequency=1)
        self.assertEqual(result['data']['new_password'],'  SYNTHETIC_PASSWORD  ')
        self.assertTrue(result['source_banned'])
        self.assertNotIn('enabled',result['data'])

    def test_no_email_social_only_keeps_source_id_without_fake_person_name(self):
        result=plan(row(email='',name='',last_name='',phone_number=''))
        self.assertEqual(result['action'],'create_contact')
        self.assertEqual(result['data']['first_name'],'')
        self.assertEqual(result['data']['custom_avo_telegram_id'],'17')
        self.assertNotIn('email_ids',result['data'])
        self.assertNotIn('user',result['data'])

    def test_protected_and_excluded_precede_any_field_processing(self):
        bad={'id_contact':'123','password':['SYNTHETIC_PRIVATE']}
        self.assertEqual(plan(bad,protected=True),{'action':'protected'})
        self.assertEqual(plan(bad,excluded=True),{'action':'excluded'})

    def test_strange_types_do_not_become_stringified_contact_data(self):
        for changes in ({'name':['private']},{'not_to_write':None},{'phone_number':False}):
            with self.assertRaises(PlanError):plan(row(**changes),email_frequency=1)

    def test_user_readback_rejects_changed_identity_and_accepts_name_escaping(self):
        data=plan(row(name='A&B'),email_frequency=1)['data']
        saved=dict(data,first_name='A&amp;B');saved.pop('new_password')
        self.assertTrue(matches(saved,data))
        saved['custom_avo_contact_id']='999'
        self.assertFalse(matches(saved,data))

    def test_contact_readback_rejects_foreign_user_link(self):
        data=plan(row(email='',phone_number='0000000000'))['data']
        saved=dict(data,mobile_no='0000000000')
        self.assertTrue(matches(saved,data))
        saved['user']='someone@example.invalid'
        self.assertFalse(matches(saved,data))


if __name__=='__main__':unittest.main()
