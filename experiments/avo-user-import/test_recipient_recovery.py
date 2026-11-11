import unittest
import recipient_recovery as r


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.row={'name':'synthetic@example.invalid','email':'synthetic@example.invalid',
                  'custom_avo_account':'mv-centr','custom_avo_contact_id':'42',
                  'first_name':'Example','custom_no_marketing_email':0}
    def test_absent_and_verified_existing(self):
        self.assertEqual(r.classify([],[],self.row),'absent')
        self.assertEqual(r.classify([self.row],[self.row],self.row),'present')
    def test_conflicts_never_become_present(self):
        other={**self.row,'name':'different@example.invalid'}
        self.assertEqual(r.classify([self.row],[other],self.row),'conflict')
        self.assertEqual(r.classify([self.row],[],self.row),'conflict')
        self.assertEqual(r.classify([self.row,self.row],[self.row],self.row),'conflict')
    def test_newer_optout_is_not_cleared(self):
        actual={**self.row,'custom_no_marketing_email':1}
        self.assertEqual(r.classify([actual],[actual],self.row),'present')
        expected={**self.row,'custom_no_marketing_email':1}
        self.assertEqual(r.classify([self.row],[self.row],expected),'conflict')


if __name__=='__main__':unittest.main()
