"""MCP contracts use metadata-only synthetic staging receipts and File documents."""
import copy
import hashlib
import unittest

import audio_files as audio
from importer import Review,Stop


def receipt():
    raw=b'ID3-synthetic-audio-bytes'
    return {'basename':'avo-mastervision-audio-stage-'+'1'*64+'.mp3','url_sha256':'1'*64,
            'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'md5':hashlib.md5(raw,usedforsecurity=False).hexdigest()}


def file_doc(row=None):
    row=receipt() if row is None else row
    filename='avo-mastervision-audio-'+row['sha256']+'.mp3'
    return {'doctype':'File','name':'audio-file-1','file_name':filename,'file_url':'/private/files/'+filename,
            'is_private':1,'owner':'Administrator','file_size':row['size'],'content_hash':row['md5'],
            'attached_to_doctype':None,'attached_to_name':None,'attached_to_field':None}


class Client:
    account='mastervision';site='my-lk.mastervision.su'
    def __init__(self):
        self.files=[];self.calls=[];self.mutations=[];self.row=receipt();self.corrupt_create={}
        self.fail_create=False;self.fail_get_after_create=False;self.fail_update=False;self.race_update=False
        self.change_settings_read=False;self.change_settings_after=False;self.settings_reads=0;self.next_page=False
        self.duplicate_after_create=False
        self.settings={'doctype':'System Settings','name':'System Settings','max_file_size':0,
                       'modified':'2026-11-13 10:00:00.000000','language':'ru','unrelated':{'keep':True}}
    def call(self,tool,args):
        self.calls.append((tool,copy.deepcopy(args)))
        if tool=='list_documents':
            assert args['doctype']=='File'
            rows=[row for row in self.files if all(row.get(key)==value for key,op,value in args['filters'] if op=='=')]
            return {'documents':copy.deepcopy(rows),'has_next_page':self.next_page}
        assert tool=='get_document'
        if args['doctype']=='System Settings':
            assert args['name']=='System Settings';self.settings_reads+=1
            if self.change_settings_read and self.settings_reads==2:self.settings['language']='en'
            return copy.deepcopy(self.settings)
        assert args['doctype']=='File'
        if self.fail_get_after_create and self.mutations:raise RuntimeError('PRIVATE TRANSPORT RESPONSE')
        return copy.deepcopy(next(row for row in self.files if row['name']==args['name']))
    def rpc(self,method,params):
        assert method=='tools/call';tool,args=params['name'],params['arguments']
        self.mutations.append((tool,copy.deepcopy(args)))
        if tool=='create_document':
            assert args['doctype']=='File'
            assert args['data']=={'file_name':file_doc(self.row)['file_name'],
                                 'file_url':'/private/files/'+self.row['basename'],'is_private':1}
            row=file_doc(self.row);row.update(self.corrupt_create);self.files.append(row)
            if self.duplicate_after_create:self.files.append(dict(row,name='concurrent-duplicate'))
            if self.fail_create:raise RuntimeError('PRIVATE AUTH after possible commit')
            return {'structuredContent':copy.deepcopy(row)}
        assert tool=='update_document' and args['doctype']=='System Settings' and args['name']=='System Settings'
        assert set(args['data'])=={'max_file_size','modified'};assert args['data']['max_file_size']==50
        if self.race_update:self.settings['modified']='2026-11-13 10:00:01.000000'
        if args['data']['modified']!=self.settings['modified']:return {'isError':True}
        self.settings['max_file_size']=50;self.settings['modified']='2026-11-13 10:00:02.000000'
        if self.change_settings_after:self.settings['language']='en'
        if self.fail_update:raise RuntimeError('PRIVATE settings response after possible commit')
        return {'structuredContent':copy.deepcopy(self.settings)}


class AudioFileTests(unittest.TestCase):
    def test_wrong_site_account_receipt_and_apply_type_never_touch_target(self):
        for field,value in [('site','my-lk.mv-centr.ru'),('account','mv-centr')]:
            client=Client();setattr(client,field,value)
            with self.assertRaisesRegex(Stop,'wrong_frappe_site'):audio.register_audio(client,receipt(),True)
            self.assertEqual(client.calls+client.mutations,[])
        invalid=[None,{},dict(receipt(),basename='../bad.mp3'),dict(receipt(),basename='avo-mastervision-audio-stage-'+'2'*64+'.mp3'),
                 dict(receipt(),size=True),dict(receipt(),size=0),dict(receipt(),size=50*1024*1024+1),
                 dict(receipt(),md5='invalid'),dict(receipt(),sha256='A'*64),dict(receipt(),extra='unknown')]
        for row in invalid:
            client=Client()
            with self.assertRaises(Review):audio.register_audio(client,row,True)
            self.assertEqual(client.calls+client.mutations,[])
        client=Client()
        with self.assertRaises(Review):audio.register_audio(client,receipt(),1)
        self.assertEqual(client.calls+client.mutations,[])

    def test_dry_run_only_returns_planned_metadata_and_never_registers(self):
        client=Client();row=receipt();before=copy.deepcopy(row)
        out=audio.register_audio(client,row)
        self.assertEqual(set(out),{'file_url','sha256','md5','size'})
        self.assertEqual(out['file_url'],file_doc()['file_url']);self.assertEqual(row,before)
        self.assertEqual(client.mutations,[]);self.assertNotIn('stage-',repr(out))

    def test_create_uses_private_staging_url_without_content_and_verifies_readback(self):
        client=Client();out=audio.register_audio(client,receipt(),True)
        self.assertEqual(out,{'file_url':file_doc()['file_url'],'sha256':receipt()['sha256'],
                              'md5':receipt()['md5'],'size':receipt()['size']})
        self.assertEqual(len(client.mutations),1);self.assertEqual(client.mutations[0][0],'create_document')
        self.assertNotIn('content',client.mutations[0][1]['data']);self.assertNotIn('decode',client.mutations[0][1]['data'])
        self.assertTrue(any(tool=='get_document' and args['doctype']=='File' for tool,args in client.calls))
        self.assertTrue(all(client.files[0].get(key) is None for key in ('attached_to_doctype','attached_to_name','attached_to_field')))

    def test_existing_exact_owned_file_is_idempotent_without_any_mutation(self):
        client=Client();client.files=[file_doc()]
        self.assertEqual(audio.register_audio(client,receipt(),True)['file_url'],file_doc()['file_url'])
        self.assertEqual(client.mutations,[])

    def test_foreign_public_attached_or_corrupt_existing_files_never_change(self):
        for key,value in [('owner','other@example.test'),('is_private',0),('file_size',999),('content_hash','0'*32),
                          ('file_url','/files/public.mp3'),('attached_to_doctype','Course Lesson'),
                          ('attached_to_name','other-lesson'),('attached_to_field','content')]:
            client=Client();doc=file_doc();doc[key]=value;client.files=[doc];before=copy.deepcopy(client.files)
            with self.subTest(field=key),self.assertRaises(Review):audio.register_audio(client,receipt(),True)
            self.assertEqual(client.files,before);self.assertEqual(client.mutations,[])

    def test_duplicate_name_or_content_alias_is_ambiguous_and_never_adopted(self):
        for mode in ('name','hash','pagination'):
            client=Client()
            if mode=='name':client.files=[file_doc(),dict(file_doc(),name='duplicate')]
            elif mode=='hash':client.files=[dict(file_doc(),name='foreign',file_name='other.mp3',file_url='/private/files/other.mp3')]
            else:client.next_page=True
            with self.subTest(mode=mode),self.assertRaises(Review):audio.register_audio(client,receipt(),True)
            self.assertEqual(client.mutations,[])

    def test_unknown_mutation_is_not_retried_or_deleted_and_never_leaks_remote_text(self):
        client=Client();client.fail_create=True
        with self.assertRaises(Stop) as caught:audio.register_audio(client,receipt(),True)
        self.assertNotIn('PRIVATE',str(caught.exception));self.assertEqual(len(client.mutations),1)
        self.assertEqual(len(client.files),1)
        client=Client();client.fail_get_after_create=True
        with self.assertRaises(Stop):audio.register_audio(client,receipt(),True)
        self.assertEqual(len(client.mutations),1)

    def test_corrupt_create_readback_stops_instead_of_returning_false_success(self):
        for update in ({'file_size':0},{'content_hash':'0'*32},{'owner':'foreign'},
                       {'file_url':'/private/files/staged.mp3'},{'is_private':0}):
            client=Client();client.corrupt_create=update
            with self.subTest(fields=list(update)),self.assertRaises(Stop):audio.register_audio(client,receipt(),True)
            self.assertEqual(len(client.mutations),1)

    def test_duplicate_appearing_during_registration_is_uncertain_not_success(self):
        client=Client();client.duplicate_after_create=True
        with self.assertRaises(Stop):audio.register_audio(client,receipt(),True)
        self.assertEqual(len(client.mutations),1);self.assertEqual(len(client.files),2)

    def test_mutation_guard_cannot_publish_attach_change_owners_or_other_settings(self):
        filename=file_doc()['file_name'];url='/private/files/'+receipt()['basename']
        bad=[('create_document',{'doctype':'File','data':{'file_name':filename,'file_url':url,'is_private':0}}),
             ('create_document',{'doctype':'File','data':{'file_name':filename,'file_url':url,'is_private':1,'owner':'Administrator'}}),
             ('create_document',{'doctype':'File','data':{'file_name':filename,'file_url':'https://example.test/a.mp3','is_private':1}}),
             ('update_document',{'doctype':'System Settings','name':'System Settings','data':{'max_file_size':100,'modified':'x'}}),
             ('delete_document',{'doctype':'File','name':'file'})]
        for tool,args in bad:
            client=Client()
            with self.subTest(tool=tool),self.assertRaises(Stop):audio._write(client,tool,args)
            self.assertEqual(client.mutations,[])


class AudioLimitTests(unittest.TestCase):
    def test_account_binding_and_boolean_apply_are_checked_before_any_read(self):
        client=Client();client.site='my-lk.iomp.ru'
        with self.assertRaises(Stop):audio.ensure_audio_limit(client,True)
        self.assertEqual(client.calls+client.mutations,[])
        client=Client()
        with self.assertRaises(Review):audio.ensure_audio_limit(client,1)
        self.assertEqual(client.calls+client.mutations,[])

    def test_default_25_and_small_explicit_limits_are_only_planned_on_dry_run(self):
        for value in (0,10,25,49):
            client=Client();client.settings['max_file_size']=value
            result=audio.ensure_audio_limit(client)
            self.assertEqual(result['status'],'would_update');self.assertEqual(result['required_max_file_size'],50)
            self.assertEqual(client.mutations,[])

    def test_larger_limits_are_kept_and_weird_values_are_rejected(self):
        for value in (50,100):
            client=Client();client.settings['max_file_size']=value
            self.assertEqual(audio.ensure_audio_limit(client,True)['status'],'already_sufficient')
            self.assertEqual(client.mutations,[])
        for value in (None,'50',False,-1):
            client=Client();client.settings['max_file_size']=value
            with self.assertRaises(Review):audio.ensure_audio_limit(client,True)
            self.assertEqual(client.mutations,[])

    def test_updates_only_limit_with_optimistic_timestamp_and_protects_other_settings(self):
        client=Client();before=copy.deepcopy(client.settings)
        result=audio.ensure_audio_limit(client,True)
        self.assertEqual(result,{'status':'updated','max_file_size':50})
        self.assertEqual(len(client.mutations),1);self.assertEqual(client.mutations[0][1]['data'],
            {'max_file_size':50,'modified':before['modified']})
        for key in ('language','unrelated'):self.assertEqual(client.settings[key],before[key])

    def test_prewrite_change_race_unknown_write_and_readback_change_all_stop_safely(self):
        client=Client();client.change_settings_read=True
        with self.assertRaises(Review):audio.ensure_audio_limit(client,True)
        self.assertEqual(client.mutations,[])
        for option in ('race_update','fail_update','change_settings_after'):
            client=Client();setattr(client,option,True)
            with self.subTest(option=option),self.assertRaises(Stop) as caught:audio.ensure_audio_limit(client,True)
            self.assertNotIn('PRIVATE',str(caught.exception));self.assertEqual(len(client.mutations),1)


if __name__=='__main__':unittest.main()
