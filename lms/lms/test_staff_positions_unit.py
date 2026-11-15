"""Delegation checks use a bounded in-memory policy store, never real people."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Doc(Row):
    def is_new(self): return self.get('_new', False)
    def get_doc_before_save(self): return self.get('_before')


def position(name, parent=None, rights=(), roles=('LMS Student',), scope='Owned', active=1, **kw):
    return Doc(name=name, title=name, parent_position=parent, active=active, course_scope=scope,
               permissions=[Row(resource=r,action=a) for r,a in rights],
               native_roles=[Row(role=role) for role in roles], **kw)


class StaffPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=types.ModuleType('frappe');self.f._=lambda text:text
        self.f.PermissionError=PermissionError;self.f.ValidationError=ValueError
        self.f.throw=lambda text,error=ValueError: (_ for _ in ()).throw(error(text))
        self.f.whitelist=lambda *args,**kwargs: lambda function:function
        self.f.session=Row(user='manager@example.test');self.f.flags=Row();self.f.local=Row(site='fixture.local')
        self.schema=True;self.assignments={};self.positions={};self.roles={'manager@example.test':['Moderator']}
        self.course_owner='owner@example.test';self.query_count=0
        self.f.get_roles=lambda user=None:self.roles.get(user or self.f.session.user,[])
        self.f.get_meta=lambda _:Row(has_field=lambda _:False)
        self.f.get_all=self.get_all;self.f.get_doc=lambda doctype,name:self.positions[name]
        self.f.db=Row(table_exists=lambda _:self.schema, get_value=self.get_value,
                      exists=self.exists, sql=lambda *args,**kwargs:[[1]],
                      after_commit=Row(add=lambda _:None),after_rollback=Row(add=lambda _:None))
        utils=types.ModuleType('frappe.utils');utils.cint=lambda v:int(v or 0);utils.now_datetime=lambda:'fixture-time'
        self.modules=patch.dict(sys.modules,{'frappe':self.f,'frappe.utils':utils})
        self.modules.start();self.addCleanup(self.modules.stop)
        self.policy=self.load('lms.lms.staff_policy','staff_policy.py')
        self.api=self.load('staff_positions_under_test','staff_positions.py')
        full=[(r,a) for r,actions in self.policy.RESOURCES.items() for a in actions]
        manager_rights=[(r,a) for r in ('contacts','staff','positions','course_access') for a in self.policy.RESOURCES[r]]
        self.positions={
            'root':position('root',rights=full,roles=self.policy.NATIVE_ROLES,scope='All'),
            'manager':position('manager','root',manager_rights,('LMS Student','Moderator')),
            'assistant':position('assistant','manager',[('contacts','read')]),
            'outsider':position('outsider','root',[('contacts','read')]),
        }
        self.assignments['manager@example.test']=Row(name='a1',position='manager',active=1)

    def load(self,name,filename):
        spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module
        self.addCleanup(lambda:sys.modules.pop(name,None));spec.loader.exec_module(module)
        return module

    def get_all(self,doctype,filters=None,fields=None,pluck=None,**kwargs):
        self.query_count+=1
        if doctype=='LMS Staff Assignment':
            if filters and 'user' in filters:
                row=self.assignments.get(filters['user']);rows=[row] if row else []
            else: rows=[]
        elif doctype=='LMS Staff Position':
            rows=list(self.positions.values())
            if filters:rows=[row for row in rows if all(row.get(key)==value for key,value in filters.items())]
        else:rows=[]
        return [row[pluck] for row in rows] if pluck else rows

    def get_value(self,doctype,name,field,**kwargs):
        if doctype=='LMS Course':return self.course_owner
        if doctype=='LMS Staff Position':
            row=self.positions.get(name)
            if row is None:return None
            return Row({key:row.get(key) for key in field}) if isinstance(field,list) else row.get(field)
        return None

    def exists(self,doctype,filters):
        if doctype=='Course Instructor':return False
        if doctype=='User':return filters in self.roles
        if doctype=='LMS Staff Assignment':return any(row.position==filters.get('position') for row in self.assignments.values())
        if doctype=='LMS Staff Position':return any(row.parent_position==filters.get('parent_position') for row in self.positions.values())
        return False

    def test_explicit_position_replaces_legacy_roles_and_credentials(self):
        self.roles['manager@example.test']=['Moderator','System Manager']
        self.assertTrue(self.policy.has_capability('contacts','read'))
        self.assertFalse(self.policy.has_capability('credentials','read'))
        self.assertFalse(self.policy.has_capability('credentials','send'))

    def test_inactive_assignment_never_returns_to_legacy_fallback(self):
        self.assignments['manager@example.test'].active=0
        self.assertFalse(self.policy.has_capability('contacts','read'))

    def test_disabled_ancestor_denies_child_permissions(self):
        self.positions['root'].active=0
        self.assertFalse(self.policy.has_capability('staff','create'))

    def test_legacy_moderator_keeps_contact_and_course_operations_only(self):
        self.assignments.clear()
        self.assertTrue(self.policy.has_capability('contacts','write'))
        self.assertTrue(self.policy.has_capability('course_access','remove',course='course'))
        self.assertFalse(self.policy.has_capability('contacts','delete'))
        self.assertFalse(self.policy.has_capability('staff','create'))
        self.assertFalse(self.policy.has_capability('positions','write'))

    def test_course_creator_fallback_requires_owned_course(self):
        self.assignments.clear();self.roles['manager@example.test']=['Course Creator']
        self.assertFalse(self.policy.has_capability('course_access','read'))
        self.assertFalse(self.policy.has_capability('course_access','write',course='course'))
        self.course_owner='manager@example.test'
        self.policy.clear_policy_cache()
        self.assertTrue(self.policy.has_capability('course_access','write',course='course'))

    def test_actor_policy_is_cached_only_for_current_request_and_invalidated(self):
        self.policy.has_capability('contacts','read');count=self.query_count
        self.policy.has_capability('contacts','write');self.assertEqual(count,self.query_count)
        self.assignments['manager@example.test'].active=0;self.policy.clear_policy_cache()
        self.assertFalse(self.policy.has_capability('contacts','read'))

    def test_read_dependencies_unknown_actions_and_duplicates_are_rejected(self):
        for matrix in ([{'resource':'contacts','action':'write'}],
                       [{'resource':'unknown','action':'read'}],
                       [{'resource':['contacts'],'action':'read'}],
                       [{'resource':'contacts','action':'read'}]*2):
            with self.assertRaises(ValueError):self.policy.permission_pairs(matrix)
        self.assertEqual(self.policy.permission_pairs([{'resource':'credentials','action':'send'}]),{('credentials','send')})

    def test_subordinate_ceiling_is_enforced_against_actor(self):
        doc=position('new','manager',[('credentials','read')],_new=True)
        with self.assertRaises(PermissionError):self.api.validate_position_document(doc)

    def test_native_technical_role_cannot_enter_a_position(self):
        doc=position('new','manager',roles=('LMS Student','System Manager'),_new=True)
        with self.assertRaises(ValueError):self.api.validate_position_document(doc)

    def test_own_and_ancestor_positions_cannot_be_changed(self):
        for name in ('manager','root'):
            with self.subTest(name=name),self.assertRaises(PermissionError):self.api.validate_position_document(self.positions[name])

    def test_reparent_outside_actor_subtree_is_rejected(self):
        doc=position('assistant','outsider',[('contacts','read')])
        with self.assertRaises(PermissionError):self.api.validate_position_document(doc)

    def test_cycles_and_scope_escalation_are_rejected(self):
        doc=position('new','manager',scope='All',_new=True)
        with self.assertRaises(PermissionError):self.api.validate_position_document(doc)
        self.f.session.user='Administrator'
        self.positions['assistant'].parent_position='manager'
        doc=position('manager','assistant',[('contacts','read')])
        with self.assertRaises(ValueError):self.api.validate_position_document(doc)

    def test_parent_cannot_be_lowered_below_existing_child(self):
        self.f.session.user='Administrator'
        self.positions['assistant'].permissions=[Row(resource='contacts',action='read'),Row(resource='contacts',action='write')]
        doc=position('manager','root',[('contacts','read')])
        with self.assertRaises(ValueError):self.api.validate_position_document(doc)

    def test_subordinate_cannot_exceed_parent_even_if_actor_has_more_rights(self):
        doc=position('new','assistant',[('contacts','read'),('contacts','write')],_new=True)
        with self.assertRaises(ValueError):self.api.validate_position_document(doc)

    def test_valid_subordinate_can_be_created(self):
        doc=position('new','manager',[('contacts','read')],_new=True)
        self.api.validate_position_document(doc)
        self.assertEqual(doc.changed_by,self.f.session.user)

    def test_generic_assignment_api_and_forged_doc_flags_cannot_assign_roles(self):
        doc=Doc(name='new-assignment',user='assistant@example.test',position='assistant',active=1,_new=True,
                flags={'_lms_staff_assignment_write':True})
        with self.assertRaises(PermissionError):self.api.validate_assignment_document(doc)

    def test_server_assignment_scope_still_rejects_self_and_ancestor(self):
        for target in ('manager@example.test','assistant@example.test'):
            doc=Doc(name='new-assignment',user=target,position='manager',active=1,_new=True)
            with self.api._assignment_write(target,'manager',1),self.assertRaises(PermissionError):
                self.api.validate_assignment_document(doc)

    def test_valid_controlled_assignment_does_not_grant_a_technical_role(self):
        doc=Doc(name='new-assignment',user='assistant@example.test',position='assistant',active=1,_new=True)
        with self.api._assignment_write(doc.user,'assistant',1):self.api.validate_assignment_document(doc)
        self.assertEqual(doc.assigned_by,self.f.session.user)

    def test_delete_only_actor_can_deactivate_without_general_staff_write(self):
        self.positions['manager'].permissions=[Row(resource='staff',action='read'),Row(resource='staff',action='delete')]
        before=Doc(name='a2',user='assistant@example.test',position='assistant',active=1)
        self.assignments[before.user]=before
        doc=Doc(name='a2',user=before.user,position='assistant',active=0,_before=before)
        with self.api._assignment_write(doc.user,'assistant',0):self.api.validate_assignment_document(doc)

    def test_create_without_delete_cannot_disable_an_existing_learner(self):
        self.positions['manager'].permissions=[Row(resource='staff',action='read'),Row(resource='staff',action='create')]
        doc=Doc(name='new',user='assistant@example.test',position='assistant',active=0,_new=True)
        with self.api._assignment_write(doc.user,'assistant',0),self.assertRaises(PermissionError):
            self.api.validate_assignment_document(doc)

    def test_controlled_user_scope_is_typed_and_cannot_be_forged(self):
        doc=Doc(name='assistant@example.test',roles=[Row(role='LMS Student')],role_profiles=[],enabled=1,user_type='Website User')
        self.f.flags._lms_staff_user_write=Row(actor=self.f.session.user,target=doc.name,roles={'LMS Student'},enabled=1)
        self.assertFalse(self.policy.is_controlled_user_change(doc))
        with self.policy._controlled_user_write(doc.name,{'LMS Student'},1):
            self.assertTrue(self.policy.is_controlled_user_change(doc))
            doc.roles.append(Row(role='System Manager'))
            self.assertFalse(self.policy.is_controlled_user_change(doc))

    def test_disabled_ancestor_removes_native_staff_roles_without_deleting_learner(self):
        self.positions['root'].active=0
        doc=Doc(name='assistant@example.test',roles=[Row(role='Moderator')],enabled=1)
        doc.set=lambda key,value:doc.__setitem__(key,value)
        saved=[];doc.save=lambda **kwargs:saved.append(True)
        original=self.f.get_doc
        self.f.get_doc=lambda doctype,name:doc if doctype=='User' else original(doctype,name)
        self.f.clear_cache=lambda **kwargs:None
        self.api._sync_user(Row(user=doc.name,position='assistant',active=1))
        self.assertEqual(doc.roles,[{'role':'LMS Student'}])
        self.assertEqual(doc.enabled,1);self.assertEqual(saved,[True])
        self.assertIsNone(self.f.flags.get('_lms_staff_user_write'))

    def _sync_document(self, roles):
        doc=Doc(name='legacy@example.test',roles=[Row(role=role) for role in roles],enabled=1)
        doc.set=lambda key,value:doc.__setitem__(key,value)
        doc.save=lambda **kwargs:None
        original=self.f.get_doc
        self.f.get_doc=lambda doctype,name:doc if doctype=='User' else original(doctype,name)
        self.f.clear_cache=lambda **kwargs:None
        return doc

    def test_administrator_replaces_retired_password_role_with_only_selected_position_roles(self):
        self.f.session.user='Administrator'
        doc=self._sync_document(('LMS Student','Moderator','Course Creator','LMS Credential Manager'))
        self.api._sync_user(Row(user=doc.name,position='assistant',active=1))
        self.assertEqual(doc.roles,[{'role':'LMS Student'}])
        self.assertEqual(doc.enabled,1)

    def test_retired_password_role_is_not_a_nonadmin_delegation_exception(self):
        doc=self._sync_document(('LMS Student','LMS Credential Manager'))
        with self.assertRaises(ValueError):self.api._sync_user(Row(user=doc.name,position='assistant',active=1))
        self.assertIn('LMS Credential Manager',[row.role for row in doc.roles])

    def test_administrator_still_cannot_silently_remove_real_technical_roles(self):
        self.f.session.user='Administrator'
        roles=('LMS Student','Moderator','Script Manager','System Manager')
        doc=self._sync_document(roles)
        doc.role_profiles=[Row(role_profile='Existing System Profile')]
        doc.user_type='System User'
        doc.save=lambda **kw: self.fail('unchanged system account must not be rewritten')
        self.api._sync_user(Row(user=doc.name,position='assistant',active=1))
        self.assertEqual([row.role for row in doc.roles],list(roles))
        self.assertEqual(doc.role_profiles,[Row(role_profile='Existing System Profile')])
        self.assertEqual(doc.user_type,'System User')

    def test_nonadmin_cannot_edit_a_technical_account_even_inside_valid_subtree(self):
        member='system@example.test'
        self.roles[member]=['System Manager','LMS Student']
        original=self.f.db.exists
        self.f.db.exists=lambda doctype,*a,**kw:True if doctype=='User' else original(doctype,*a,**kw)
        with self.assertRaises(PermissionError):
            self.api._can_target_user(member,'assistant',current=Row(position='assistant'))

    def test_nonadmin_user_projection_cannot_use_system_preservation_branch(self):
        doc=self._sync_document(('LMS Student','System Manager'))
        with self.assertRaises(ValueError):self.api._sync_user(Row(user=doc.name,position='assistant',active=1))
        self.assertIn('System Manager',[row.role for row in doc.roles])

    def test_administrator_can_disable_system_login_without_removing_roles(self):
        self.f.session.user='Administrator'
        doc=self._sync_document(('LMS Student','System Manager'))
        saved=[];doc.save=lambda **kw:saved.append(True)
        self.api._sync_user(Row(user=doc.name,position='assistant',active=0))
        self.assertEqual(doc.enabled,0)
        self.assertEqual(saved,[True])
        self.assertEqual([row.role for row in doc.roles],['LMS Student','System Manager'])


if __name__=='__main__':unittest.main()
