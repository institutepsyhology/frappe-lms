import unittest
import import_recipient_selection as importer


class RecipientSelectionTest(unittest.TestCase):
    def test_complaint_sets_optout_but_never_clears_existing_flag(self):
        self.assertEqual(importer.merge_complaint({'custom_no_marketing_email':0}, 1, {1})['custom_no_marketing_email'],1)
        self.assertEqual(importer.merge_complaint({'custom_no_marketing_email':1}, 2, {1})['custom_no_marketing_email'],1)
        self.assertIsNone(importer.merge_complaint(None, 1, {1}))

    def test_newer_csv_values_are_limited_to_profile_fields(self):
        result=importer.merge_complaint({'first_name':'old'},1,set(),{'1':{'first_name':'new'}})
        self.assertEqual(result['first_name'],'new')
        with self.assertRaises(ValueError):
            importer.merge_complaint({'first_name':'old'},1,set(),{'1':{'new_password':'unsafe'}})


if __name__=='__main__':unittest.main()
