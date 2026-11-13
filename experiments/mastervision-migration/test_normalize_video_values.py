"""Synthetic URL/slot repairs; no real URLs, network or course data."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from importer import Review
from normalize_video_values import normalize_video_values, CODE

spec = importlib.util.spec_from_file_location('video_value_test_static',
    Path(__file__).resolve().parents[2] / 'lms/lms/avo_html_fragment.py')
static = importlib.util.module_from_spec(spec); spec.loader.exec_module(static)
VALIDATE = static.make_html_block
YT = 'https://youtu.be/abcdefghijk'
RT = 'https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/?p=synthetic_key'


def video(primary=YT, provider='youtube', **fields):
    return {'id':'synthetic-video','name':'video','fields':{
        'anchor':'','videoSrc':primary,'videoProvider':provider,'html':'Видео',**fields},'children':[]}


def page(*nodes): return {'name':'page','children':list(nodes)}


class VideoValueTests(unittest.TestCase):
    def normalize(self, ape): return normalize_video_values(ape, VALIDATE)

    def test_outer_ascii_only_trim_preserves_caption_and_all_other_settings(self):
        node=video(' \t'+YT+'\r\n',html='<p>Keep &amp; caption</p>',nativePlayer=False,isFloating=True)
        ape=page(node);before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        expected=copy.deepcopy(node);expected['fields']['videoSrc']=YT
        self.assertEqual(out,page(expected));self.assertEqual(ape,before)
        self.assertEqual(changes,[{'path':[0],'code':CODE,'trimmed_slots':[1]}])

    def test_real_pair_is_never_promoted_or_reordered_and_secondary_can_be_trimmed(self):
        node=video(videoSrc2=' '+RT+' ',videoProvider2='rutube',nativePlayer2=False)
        ape=page(node);out,changes=self.normalize(ape)
        self.assertEqual(out['children'][0]['fields']['videoSrc'],YT)
        self.assertEqual(out['children'][0]['fields']['videoSrc2'],RT)
        self.assertEqual(changes,[{'path':[0],'code':CODE,'trimmed_slots':[2]}])
        second,again=self.normalize(out);self.assertEqual(second,out);self.assertEqual(again,[])

    def test_sole_secondary_promoted_with_exact_false_and_string_flags_preserved(self):
        node=video('',videoSrc2=RT,videoProvider2='rutube',nativePlayer=True,nativePlayer2=False,
                   isShowProgressControl=True,isShowProgressControl2='0',isShowFastRewindButtons=False,
                   isShowFastRewindButtons2=True,isFloating=None,posterSrc='',posterSrc2='',embeddedHtml='')
        ape=page(node);before=copy.deepcopy(ape);out,changes=self.normalize(ape);f=out['children'][0]['fields']
        self.assertEqual((f['videoSrc'],f['videoProvider'],f['videoSrc2']),(RT,'rutube',''))
        self.assertIs(f['nativePlayer'],False);self.assertEqual(f['isShowProgressControl'],'0')
        self.assertIs(f['isShowFastRewindButtons'],True)
        for key in ('nativePlayer2','isShowProgressControl2','isShowFastRewindButtons2','videoProvider2','html','isFloating'):
            self.assertEqual(f[key],node['fields'][key])
        self.assertEqual(changes[0]['promoted_flags'],['nativePlayer','isShowProgressControl','isShowFastRewindButtons'])
        self.assertTrue(changes[0]['secondary_promoted']);self.assertEqual(ape,before)
        second,again=self.normalize(out);self.assertEqual(second,out);self.assertEqual(again,[])
        self.assertNotIn('https',json.dumps(changes));self.assertNotIn('synthetic_key',json.dumps(changes))

    def test_none_or_missing_primary_and_trimmed_secondary_keep_original_paths(self):
        first=video(None,videoSrc2='\t'+RT+' ',videoProvider2='rutube')
        second=video('',videoSrc2=YT,videoProvider2='youtube');second['fields'].pop('videoSrc')
        ape=page({'name':'column','children':[first]},second)
        out,changes=self.normalize(ape)
        self.assertEqual([row['path'] for row in changes],[[0,0],[1]])
        self.assertEqual(changes[0]['trimmed_slots'],[2]);self.assertTrue(changes[0]['secondary_promoted'])
        self.assertEqual(out['children'][0]['children'][0]['fields']['videoSrc'],RT)
        self.assertEqual(out['children'][1]['fields']['videoSrc'],YT)

    def test_good_primary_bad_primary_and_unknown_video_urls_are_never_replaced(self):
        values=[video(YT,videoSrc2=RT,videoProvider2='rutube'),
                video('invalid',videoSrc2=RT,videoProvider2='rutube'),
                video('   ',videoSrc2=RT,videoProvider2='rutube'),
                video('h'+YT,videoSrc2=RT,videoProvider2='rutube'),
                video(YT+RT,videoSrc2=RT,videoProvider2='rutube'),
                video('',videoSrc2=RT,videoProvider2='youtube'),
                video('',videoSrc2='https://vk.com/video123',videoProvider2='embedded')]
        for node in values:
            ape=page(node);out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_internal_unicode_invalid_and_relative_whitespace_is_never_repaired(self):
        values=[' '+YT[:15]+' '+YT[15:]+' ', '\u00a0'+YT+'\u00a0', ' '+YT+'\u00a0',
                ' hhttps://youtu.be/abcdefghijk ', ' /video/abcdefghijk ',
                ' https://youtu.be/abcdefghijk https://youtu.be/zyxwvutsrqp ',
                ' https://vimeo.com/123456789 ']
        for source in values:
            ape=page(video(source));out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_meaningful_metadata_unknown_flags_and_fields_protect_whole_video(self):
        for key,value in [('anchor','keep'),('embeddedHtml','<iframe></iframe>'),('posterSrc','https://example.test/poster.png'),
                          ('posterSrc2','https://example.test/poster.png'),('nativePlayer2','unknown'),
                          ('isShowProgressControl',2),('extra',None),('videoSrc2',{}),('html',False),
                          ('videoProvider2','vimeo'),('html','<script>keepUnknown()</script>')]:
            ape=page(video(' '+YT+' ',**{key:value}));before=copy.deepcopy(ape)
            out,changes=self.normalize(ape);self.assertEqual(out,before);self.assertEqual(changes,[]);self.assertEqual(ape,before)
        for key,value in [('style',{'caption':'Keep'}),('extra',None),
                          ('style',{'lists':{'video':{'backgroundImage':'url(https://example.test/poster.png)'}}}),
                          ('children',[{'name':'video','fields':{'videoSrc':' '+YT+' ','videoProvider':'youtube'}}])]:
            node=video(' '+YT+' ');node[key]=value;ape=page(node)
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_ancestor_visibility_and_delay_preserve_entire_subtree(self):
        for key,value in [('visibleConditions',{'type':'protected'}),('displayDelay',3)]:
            ape=page({'name':'section','fields':{key:value},'children':[video(' '+YT+' ')]})
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_exact_source_flags_with_known_types_are_not_truthiness_filtered(self):
        for value in (None,'',False,True,0,1,'0','1'):
            ape=page(video('',videoSrc2=RT,videoProvider2='rutube',nativePlayer2=value))
            out,changes=self.normalize(ape)
            self.assertTrue(changes);self.assertEqual(out['children'][0]['fields']['nativePlayer'],value)
            self.assertIs(type(out['children'][0]['fields']['nativePlayer']),type(value))

    def test_malformed_data_has_fixed_review_without_mutating_source(self):
        for ape in ([],{'name':'page'},page(None),page({'name':'video','fields':[]}),page({'name':'video','children':{}})):
            before=copy.deepcopy(ape)
            with self.assertRaisesRegex(Review,'^video_values_source_invalid$'):self.normalize(ape)
            self.assertEqual(ape,before)
        with self.assertRaises(Review):normalize_video_values(page(video()),None)


if __name__=='__main__':
    unittest.main()
