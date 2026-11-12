import importlib.util
from contextlib import ExitStack
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('archive',Path(__file__).with_name('archive_verified_passwords.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Response:
    def __init__(self, data):self.data=io.BytesIO(json.dumps(data).encode())
    def __enter__(self):return self.data
    def __exit__(self,*args):return False


class ReadOnlyDatabase:
    def __init__(self, rows):
        self.rows=dict(rows);self.calls=[];self.closed=False
    def execute(self,sql,params):
        if not sql.startswith('SELECT id,record_json FROM contacts WHERE id IN ('):
            raise AssertionError('unexpected_database_operation')
        self.calls.append((sql,list(params)))
        return [(ident,json.dumps(self.rows[ident])) for ident in sorted(params) if ident in self.rows]
    def close(self):self.closed=True


def record(ident):
    return ident,{'credentials':{'password':f'dummy-password-{ident}'}}


class ArchiveTest(unittest.TestCase):
    def run_archive(self, rows, selected=None, journal=(), responses=None, lookup=None, extra_args=()):
        """Exercise main without reading private files, authenticating or networking."""
        root=Path.cwd()/'__password_archive_test__'
        journal_path=root/'journal.jsonl'
        selection_path=root/'selection.json'
        db=ReadOnlyDatabase(rows)
        posts=[];events=[];lookups=[]
        outcomes=iter(responses) if responses is not None else None
        helper=types.SimpleNamespace(authenticated_headers=Mock(return_value={'X-Test':'fixture'}))
        loader=types.SimpleNamespace(exec_module=Mock())
        output=io.StringIO()
        def read(path,*args,**kwargs):
            if path.name=='report.json':return json.dumps({'origin':'https://mvcentr.autoweboffice.ru'})
            if path==selection_path:return json.dumps(selected)
            if path==journal_path:return '\n'.join(json.dumps(row) for row in journal)
            raise AssertionError('unexpected_file_read')
        def users(ids,headers):
            lookups.append(list(ids))
            return lookup(ids) if lookup else {i:f'user-{i}@example.invalid' for i in ids}
        def post(request,timeout):
            posts.append(request)
            value=next(outcomes) if outcomes is not None else {'stored':True}
            if isinstance(value,BaseException):raise value
            return Response({'message':value})
        argv=['archive','--apply','--limit','999']
        if selected is not None:argv += ['--ids-file',str(selection_path)]
        argv += list(extra_args)
        with ExitStack() as stack:
            stack.enter_context(patch.object(module.source,'ROOT',root))
            stack.enter_context(patch.object(module,'JOURNAL',journal_path))
            stack.enter_context(patch.object(Path,'read_text',read))
            stack.enter_context(patch.object(Path,'exists',lambda path:path==journal_path and bool(journal)))
            load=stack.enter_context(patch.object(module.source,'load',return_value=iter(rows)))
            connect=stack.enter_context(patch.object(module.sqlite3,'connect',return_value=db))
            spec_mock=stack.enter_context(patch.object(module.importlib.util,'spec_from_file_location',return_value=types.SimpleNamespace(loader=loader)))
            stack.enter_context(patch.object(module.importlib.util,'module_from_spec',return_value=helper))
            stack.enter_context(patch.object(module,'users_for_ids',side_effect=users))
            stack.enter_context(patch.object(module.source.DIRECT_OPENER,'open',side_effect=post))
            stack.enter_context(patch.object(module,'event',side_effect=lambda i,s:events.append((i,s))))
            sleep=stack.enter_context(patch.object(module.time,'sleep'))
            stack.enter_context(patch.object(sys,'argv',argv))
            stack.enter_context(patch.object(sys,'stdout',output))
            module.main()
        return types.SimpleNamespace(counts=json.loads(output.getvalue().splitlines()[-1]),
            posts=posts,events=events,lookups=lookups,sleeps=[call.args[0] for call in sleep.call_args_list],
            helper=helper,loader=loader,spec=spec_mock,db=db,connect=connect,load=load,output=output.getvalue())

    def test_lookup_requires_unique_selected_source_ids(self):
        with patch.object(module.source.DIRECT_OPENER,'open',return_value=Response({'data':[
            {'name':'one@example.invalid','custom_avo_contact_id':'10'}]})):
            self.assertEqual(module.users_for_ids([10,11],{}),{10:'one@example.invalid'})
        with patch.object(module.source.DIRECT_OPENER,'open',return_value=Response({'data':[
            {'name':'one@example.invalid','custom_avo_contact_id':'10'},
            {'name':'two@example.invalid','custom_avo_contact_id':'10'}]})):
            with self.assertRaises(ValueError):module.users_for_ids([10],{})

    def test_lookup_rejects_unrequested_or_nonstring_identity(self):
        for row in [
            {'name':'other@example.invalid','custom_avo_contact_id':'99'},
            {'name':'other@example.invalid','custom_avo_contact_id':11},
        ]:
            with self.subTest(row=row),patch.object(module.source.DIRECT_OPENER,'open',return_value=Response({'data':[row]})):
                with self.assertRaises(ValueError):module.users_for_ids([11],{})

    def test_selection_none_and_empty_have_different_meanings(self):
        read=Mock()
        with patch.object(Path,'read_text',read):
            self.assertIsNone(module.load_selection(None))
            read.assert_not_called()
        with patch.object(Path,'read_text',return_value='[]'):
            self.assertEqual(module.load_selection(Path('selected.json')),set())

    def test_invalid_selection_rejects_duplicates_bools_and_excluded_contact(self):
        for value in ({'ids':[11]},[11,11],[True],[0],[-1],['11'],[10]):
            with self.subTest(value=value),patch.object(Path,'read_text',return_value=json.dumps(value)):
                with self.assertRaises(ValueError):module.load_selection(Path('selected.json'))

    def test_selected_missing_copy_overrides_old_journal_and_never_posts_other_ids(self):
        result=self.run_archive([record(11),record(12),record(13)],selected=[11],journal=[
            {'account':'mv-centr','contact_id':11,'status':'stored'},
            {'account':'mv-centr','contact_id':12,'status':'stored'},
        ])
        self.assertEqual(result.counts['stored'],1)
        self.assertEqual(result.lookups,[[11]])
        self.assertEqual(result.events,[(11,'stored')])
        self.assertEqual(len(result.posts),1)
        request=result.posts[0]
        self.assertTrue(request.full_url.endswith('/api/method/lms.lms.support_credentials.import_verified'))
        self.assertEqual(request.get_method(),'POST')
        self.assertEqual(json.loads(request.data),{'name':'user-11@example.invalid','source_id':'11','password':'dummy-password-11'})
        self.assertEqual(result.sleeps,[0.1])
        self.assertNotIn('dummy-password',result.output)
        result.load.assert_not_called()

    def test_empty_selection_never_authenticates_or_looks_up_users(self):
        result=self.run_archive([record(11)],selected=[])
        self.assertEqual(result.counts['selected'],0)
        self.assertEqual(result.counts['checked'],0)
        self.assertEqual(result.posts,[])
        self.assertEqual(result.lookups,[])
        result.helper.authenticated_headers.assert_not_called()
        result.spec.assert_not_called()
        result.connect.assert_not_called()
        result.load.assert_not_called()

    def test_unfiltered_mode_preserves_journal_and_excluded_contact_skip(self):
        result=self.run_archive([record(10),record(11),record(12)],journal=[
            {'account':'mv-centr','contact_id':11,'status':'stored'},
        ])
        self.assertEqual(result.lookups,[[12]])
        self.assertEqual(result.events,[(12,'stored')])
        self.assertNotIn('selected',result.counts)
        result.connect.assert_not_called()
        result.load.assert_called_once_with()

    def test_selected_sql_reads_only_requested_chunks_and_closes_database(self):
        selected=set(range(1000,2201))
        db=ReadOnlyDatabase([record(i) for i in selected|{9999}])
        with patch.object(module.sqlite3,'connect',return_value=db) as connect,patch.object(module.source,'load') as load:
            actual=list(module.records_for_selection(selected))
        self.assertEqual([i for i,_ in actual],sorted(selected))
        self.assertEqual([len(params) for _,params in db.calls],[500,500,201])
        self.assertTrue(all(sql.count('?')==len(params) for sql,params in db.calls))
        self.assertTrue(connect.call_args.args[0].endswith('?mode=ro'))
        self.assertTrue(connect.call_args.kwargs['uri'])
        self.assertTrue(db.closed)
        load.assert_not_called()

    def test_selected_source_missing_is_reported_without_writing(self):
        result=self.run_archive([],selected=[11])
        self.assertEqual(result.counts['selected_missing_source'],1)
        self.assertEqual(result.counts['stopped'],'selected_ids_missing_source')
        self.assertEqual(result.posts,[])

    def test_selected_deleted_target_is_not_claimed_stored(self):
        result=self.run_archive([record(11)],selected=[11],lookup=lambda ids:{})
        self.assertEqual(result.counts['not_yet_imported'],1)
        self.assertEqual(result.counts['stored'],0)
        self.assertEqual(result.posts,[])

    def test_ten_consecutive_mismatches_stop_without_password_reset(self):
        ids=list(range(101,116))
        result=self.run_archive([record(i) for i in ids],selected=ids,
            responses=[{'stored':False,'reason':'password_mismatch'} for _ in ids])
        self.assertEqual(result.counts['checked'],10)
        self.assertEqual(result.counts['mismatch'],10)
        self.assertEqual(result.counts['stored'],0)
        self.assertEqual(result.counts['stopped'],'consecutive_issues')
        self.assertEqual(len(result.posts),10)
        self.assertTrue(all(status=='mismatch' for _,status in result.events))

    def test_success_resets_consecutive_mismatch_counter(self):
        ids=list(range(101,121))
        responses=[{'stored':False}]*9+[{'stored':True}]+[{'stored':False}]*9+[{'stored':True}]
        result=self.run_archive([record(i) for i in ids],selected=ids,responses=responses)
        self.assertEqual(result.counts['checked'],20)
        self.assertEqual(result.counts['stored'],2)
        self.assertEqual(result.counts['mismatch'],18)
        self.assertNotIn('stopped',result.counts)

    def test_ten_transient_failures_keep_bounded_backoff_and_stop_uncertain(self):
        for code in (429,503):
            with self.subTest(code=code):
                failures=[module.urllib.error.HTTPError('https://example.invalid',code,'busy',None,None) for _ in range(10)]
                result=self.run_archive([record(11)],selected=[11],responses=failures)
                self.assertEqual(len(result.posts),10)
                self.assertEqual(result.counts['stopped'],'write_uncertain')
                self.assertEqual(result.counts['stored'],0)
                self.assertEqual(result.events,[(11,'write_uncertain')])
                self.assertEqual(len(result.sleeps),9)
                self.assertEqual(result.sleeps,sorted(result.sleeps))
                self.assertLessEqual(max(result.sleeps),30)

    def test_retry_uses_same_idempotent_request_and_counts_one_success(self):
        failures=[OSError('temporary'),OSError('temporary'),{'stored':True}]
        result=self.run_archive([record(11)],selected=[11],responses=failures)
        self.assertEqual(len(result.posts),3)
        self.assertEqual(len({request.data for request in result.posts}),1)
        self.assertEqual(result.counts['checked'],1)
        self.assertEqual(result.counts['stored'],1)
        self.assertEqual(result.events,[(11,'stored')])


if __name__=='__main__':unittest.main()
