"""Synthetic image cache and HTTP stubs only; no network or real source data."""
import base64
import copy
from contextlib import closing
import hashlib
from pathlib import Path
import shutil
import sqlite3
import struct
import unittest
from unittest.mock import patch
import urllib.error
import uuid
import zlib

import assets
from importer import Review


URL='https://f1.autoweboffice.com/synthetic/image.png?key=test_only'


def png(width=1,height=1):
    def chunk(kind,body):
        return len(body).to_bytes(4,'big')+kind+body+(zlib.crc32(kind+body)&0xffffffff).to_bytes(4,'big')
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+ \
           chunk(b'IDAT',zlib.compress(b'\x00\x00\x00\x00\xff'))+chunk(b'IEND',b'')


def image(key='picture',url=URL):
    return {'name':'image','id':key,'fields':{'anchor':'','imageSrc':url},'children':[]}


def payload(*images):
    return {'account':'mastervision','source_origin':assets.ORIGIN,'course_id':618,'lesson_id':6887,
            'ape':{'name':'page','children':list(images)}}


class Response:
    def __init__(self,url,body=None,headers=None,status=200):
        self.url,self.body,self.status=url,png() if body is None else body,status
        self.headers={'Content-Type':'image/png','Content-Length':str(len(self.body))} if headers is None else headers
        self.reads=[]
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def geturl(self):return self.url
    def read(self,limit):self.reads.append(limit);return self.body[:limit]


class Opener:
    def __init__(self):self.calls=[];self.response=None;self.error=None
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        if self.error:raise self.error
        return self.response or Response(request.full_url)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.parent=Path(__file__).resolve().parents[3]/'.tmp-mastervision-assets-tests'
        self.parent.mkdir(exist_ok=True);self.folder=self.parent/('fixture-'+uuid.uuid4().hex);self.folder.mkdir()
        self.addCleanup(self.cleanup)
        self.opener=Opener()
        self.build=patch.object(assets.urllib.request,'build_opener',return_value=self.opener)
        self.build_mock=self.build.start();self.addCleanup(self.build.stop)
        self.cache=assets.AssetCache(self.folder/'private-assets');self.addCleanup(self.cache.close)

    def cleanup(self):
        if self.folder.parent.resolve()!=self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)

    def test_wrong_payload_account_rejected_before_fetch(self):
        for key,value in [('account','mv-centr'),('source_origin','https://shop.mv-centr.ru')]:
            data=payload(image());data[key]=value
            with self.assertRaisesRegex(Review,'asset_account_mismatch'):self.cache.lesson_images(data)
        self.assertEqual(self.opener.calls,[])

    def test_unknown_foreign_private_ip_credential_port_and_non_https_rejected(self):
        urls=['https://shop.mv-centr.ru/a.png','https://example.test/a.png','https://127.0.0.1/a.png',
              'https://[::1]/a.png','https://10.0.0.1/a.png','https://u:p@f1.autoweboffice.com/a.png',
              'https://f1.autoweboffice.com:443/a.png','http://f1.autoweboffice.com/a.png',
              'https://f1.autoweboffice.com.evil.test/a.png','https://f1.autoweboffice.com/a.png#secret']
        for url in urls:
            with self.assertRaises(Review):self.cache.fetch(url)
        self.assertEqual(self.opener.calls,[])

    def test_whole_lesson_preflight_occurs_before_first_download(self):
        with self.assertRaisesRegex(Review,'host_requires_review'):
            self.cache.lesson_images(payload(image(),image('other','https://example.test/image.png')))
        self.assertEqual(self.opener.calls,[])

    def test_reviewed_direct_google_images_are_bounded_anonymous_and_fully_verified(self):
        for number in (3,4,5,6):
            url='https://lh'+str(number)+'.googleusercontent.com/'+'S'*190
            self.assertEqual(assets._url(url),url)
            self.assertEqual(self.cache.fetch(url),(png(),'png'))
        for request,timeout in self.opener.calls:
            self.assertEqual(request.get_method(),'GET');self.assertIsNone(request.data)
            self.assertNotIn('cookie',{key.lower() for key in request.headers})
            self.assertNotIn('authorization',{key.lower() for key in request.headers})
        url='https://lh5.googleusercontent.com/'+'F'*188
        self.opener.response=Response(url,b'<html>Not an image</html>')
        with self.assertRaises(Review):self.cache.fetch(url)

    def test_google_image_rule_does_not_authorize_other_hosts_paths_queries_or_redirects(self):
        base='https://lh5.googleusercontent.com/'+'S'*190
        for url in (base+'?',base+'?size=large',base+'#x',base+'/',base+'/extra',
                    base.replace('lh5.','lh2.'),base.replace('lh5.','lh7.'),
                    base.replace('.com/','.com.evil.test/'),base.replace('https:','http:'),
                    base.replace('.com/','.com:443/'),base.replace('//lh5','//u@lh5'),
                    base[:-3],base+'A',base[:-1]+'%41'):
            with self.assertRaises(Review):self.cache.fetch(url)
        self.assertEqual(self.opener.calls,[])
        self.opener.error=urllib.error.HTTPError(base,302,'redirect',{'Location':base[:-1]+'T'},None)
        with self.assertRaisesRegex(Review,'asset_redirect_forbidden'):self.cache.fetch(base)
        self.assertEqual(len(self.opener.calls),1)

    def test_reviewed_short_google_sources_require_exact_url_hash_and_shape(self):
        plain='https://lh3.googleusercontent.com/'+'P'*135
        keyed='https://lh7-rt.googleusercontent.com/docsz/'+'K'*142+'?key='+'T'*24
        records={hashlib.sha256(plain.encode()).hexdigest():
                    ('lh3.googleusercontent.com',r'/[A-Za-z0-9_-]{135}',''),
                 hashlib.sha256(keyed.encode()).hexdigest():
                    ('lh7-rt.googleusercontent.com',r'/docsz/[A-Za-z0-9_-]{142}',r'key=[A-Za-z0-9_-]{24}')}
        with patch.object(assets,'REVIEWED_DIRECT_IMAGE_URLS',records):
            for url in (plain,keyed):
                self.assertEqual(assets._url(url),url)
                self.assertEqual(self.cache.fetch(url),(png(),'png'))
            for url in (plain+'A',plain+'?',plain+'?key=test',plain[:-1]+'Q',
                        keyed[:-1]+'Q',keyed+'&key='+'T'*24,keyed+'&other=1',
                        keyed.replace('/docsz/','/other/'),keyed.replace('lh7-rt.','lh7-us.')):
                with self.subTest(url=url),self.assertRaises(Review):assets._url(url)
        for request,_ in self.opener.calls:
            self.assertNotIn('cookie',{k.lower()for k in request.headers})
            self.assertNotIn('authorization',{k.lower()for k in request.headers})

    def test_exact_hash_does_not_override_source_host_path_query_or_global_url_guards(self):
        urls=('https://lh7-rt.googleusercontent.com/docsz/'+'K'*142+'?key='+'T'*24,
              'http://lh3.googleusercontent.com/'+'P'*135,
              'https://u:p@lh3.googleusercontent.com/'+'P'*135,
              'https://lh3.googleusercontent.com:443/'+'P'*135,
              'https://lh3.googleusercontent.com/'+'P'*135+'#fragment')
        for url in urls:
            wrong=(('lh3.googleusercontent.com',r'/[A-Za-z0-9_-]{135}',''))
            with patch.object(assets,'REVIEWED_DIRECT_IMAGE_URLS',
                    {hashlib.sha256(url.encode()).hexdigest():wrong}):
                with self.subTest(url=url),self.assertRaises(Review):assets._url(url)
        base='https://lh7-rt.googleusercontent.com/docsz/'+'K'*142+'?key='+'T'*24
        rule=('lh7-rt.googleusercontent.com',r'/docsz/[A-Za-z0-9_-]{142}',r'key=[A-Za-z0-9_-]{24}')
        for url in (base.replace('/docsz/','/other/'),base.replace('K'*142,'K'*143),
                    base+'&key='+'T'*24,base+'&extra=1',base.replace('?key=','?other=')):
            with patch.object(assets,'REVIEWED_DIRECT_IMAGE_URLS',
                    {hashlib.sha256(url.encode()).hexdigest():rule}):
                with self.subTest(url=url),self.assertRaises(Review):assets._url(url)

    def test_reviewed_email_background_requires_exact_hash_and_shape(self):
        url='https://mastervision.su/synthetic-bg/letters/fixture_bg.jpg'
        record=('mastervision.su',r'/[a-z][a-z0-9-]{11}/letters/[a-z_]{10}\.jpg','')
        with patch.object(assets,'REVIEWED_DIRECT_IMAGE_URLS',
                {hashlib.sha256(url.encode()).hexdigest():record}):
            self.assertEqual(assets._url(url),url)
            self.assertEqual(self.cache.fetch(url),(png(),'png'))
            for other in (url+'?version=2',url.replace('mastervision.su','www.mastervision.su'),
                          url.replace('/letters/','/other/'),url.replace('fixture_bg','another_bg')):
                with self.subTest(url=other),self.assertRaises(Review):assets._url(other)

    def test_six_reviewed_source_records_contain_only_hashes_and_shapes(self):
        self.assertEqual(len(assets.REVIEWED_DIRECT_IMAGE_URLS),6)
        self.assertTrue(all(len(key)==64 and not set(key)-set('0123456789abcdef')
                            for key in assets.REVIEWED_DIRECT_IMAGE_URLS))
        self.assertEqual({x[0]for x in assets.REVIEWED_DIRECT_IMAGE_URLS.values()},
                         {'lh3.googleusercontent.com','lh7-rt.googleusercontent.com','mastervision.su'})
        self.assertNotIn('https://',repr(assets.REVIEWED_DIRECT_IMAGE_URLS))

    def test_source_and_cdn_requests_are_anonymous_with_no_proxy_or_redirect(self):
        data=self.cache.lesson_images(payload(image()))
        self.assertEqual(base64.b64decode(data['picture']),png())
        self.cache.fetch('https://shop.mastervision.su/files/image.png')
        for request,timeout in self.opener.calls:
            self.assertEqual(request.get_method(),'GET');self.assertIsNone(request.data)
            self.assertNotIn('cookie',{key.lower() for key in request.headers})
            self.assertNotIn('authorization',{key.lower() for key in request.headers})
            self.assertEqual(timeout,25)
        handlers=self.build_mock.call_args.args
        self.assertEqual(handlers[0].proxies,{})
        self.assertIsInstance(handlers[1],assets.NoRedirect)
        self.assertIsNone(handlers[1].redirect_request(None,None,302,'',{},URL))
        self.assertEqual(self.opener.addheaders,[])

    def test_redirect_rejected_without_second_request(self):
        self.opener.error=urllib.error.HTTPError(URL,302,'synthetic redirect',{'Location':'https://example.test/private'},None)
        with self.assertRaisesRegex(Review,'asset_redirect_forbidden'):self.cache.fetch(URL)
        self.assertEqual(len(self.opener.calls),1)
        self.opener.error=None;self.opener.response=Response('https://f2.autoweboffice.com/redirected.png')
        with self.assertRaisesRegex(Review,'asset_redirect_forbidden'):self.cache.fetch(URL)
        self.assertEqual(self.opener.response.reads,[])

    def test_size_header_and_bounded_body_are_checked(self):
        self.opener.response=Response(URL,headers={'Content-Length':str(assets.MAX_IMAGE+1),'Content-Type':'image/png'})
        with self.assertRaisesRegex(Review,'size_invalid'):self.cache.fetch(URL)
        self.assertEqual(self.opener.response.reads,[])
        self.opener.response=Response(URL,headers={'Content-Type':'image/png'})
        with patch.object(assets,'MAX_IMAGE',32):
            with self.assertRaisesRegex(Review,'size_invalid'):self.cache.fetch(URL)
        self.assertEqual(self.opener.response.reads,[33])

    def test_nonimage_wrong_mime_crc_and_dimensions_are_rejected(self):
        for response in [Response(URL,b'<html>Login</html>'),Response(URL,headers={'Content-Type':'text/html'}),
                         Response(URL,png()[:-1]+b'!'),Response(URL,png(width=8193))]:
            self.opener.response=response
            with self.assertRaises(Review):self.cache.fetch(URL)
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],0)

    def test_long_images_keep_bytes_with_original_area_and_byte_caps(self):
        import io
        from PIL import Image
        for size in ((2,6099),(6099,2)):
            stream=io.BytesIO();Image.new('RGB',size,(10,20,30)).save(stream,format='PNG')
            raw=stream.getvalue();self.assertEqual(assets._inspect(raw,'image/png'),'png')
            url=URL+'&long='+str(size[0]);self.opener.response=Response(url,raw)
            self.assertEqual(self.cache.fetch(url),(raw,'png'))
        for size in ((8193,1),(1,8193),(8192,2049),(4097,4096)):
            with self.assertRaisesRegex(Review,'asset_image_dimensions_invalid'):
                assets._inspect(png(*size),'image/png')
        with self.assertRaisesRegex(Review,'asset_image_size_invalid'):
            assets._inspect(b'A'*(assets.MAX_IMAGE+1))

    def test_url_and_content_dedup_and_persistent_private_cache(self):
        result=self.cache.lesson_images(payload(image('one'),image('two')))
        self.assertEqual(result['one'],result['two']);self.assertEqual(len(self.opener.calls),1)
        self.cache.fetch('https://f2.autoweboffice.com/another-source.png')
        self.assertEqual(len(list(self.cache.directory.glob('*.png'))),1)
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],2)
        self.cache.close()
        with assets.AssetCache(self.folder/'private-assets') as reopened:
            raw,extension=reopened.fetch(URL)
        self.assertEqual((raw,extension),(png(),'png'));self.assertEqual(len(self.opener.calls),2)
        self.assertTrue(all('synthetic' not in file.name for file in (self.folder/'private-assets').iterdir()))

    def test_global_placeholder_is_exact_and_has_no_mvc_numeric_exception(self):
        digest=hashlib.sha256(URL.encode()).hexdigest()
        data=payload(image());data['course_id']=258;data['lesson_id']=1150
        with patch.object(assets,'PLACEHOLDER_IMAGE_SHA256',digest):
            self.assertEqual(self.cache.lesson_images(data),{})
            self.assertEqual(self.opener.calls,[])
            for mutate in ('field','child','metadata','anchor'):
                node=image()
                if mutate=='field':node['fields']['html']='Keep this image'
                if mutate=='child':node['children']=[{'name':'text','fields':{'html':'Real child'}}]
                if mutate=='metadata':node['future']='meaningful'
                if mutate=='anchor':node['fields']['anchor']='keep'
                self.assertIn('picture',self.cache.lesson_images(payload(node)))
        self.assertEqual(len(self.opener.calls),1)

    def test_real_images_not_excluded_by_mvc_lesson_or_course_ids(self):
        data=payload(image());data['course_id']=50;data['lesson_id']=17
        self.assertIn('picture',self.cache.lesson_images(data))

    def test_only_ape_child_tree_walked_and_duplicate_keys_and_image_count_fail(self):
        data=payload();data['source_snapshot']={'ape':{'name':'page','children':[image(url='https://127.0.0.1/private')]}}
        data['ape']['fields']={'arbitrary_metadata':image(url='https://127.0.0.1/private')}
        self.assertEqual(self.cache.lesson_images(data),{})
        for data in (payload(image(),image()),payload(*[image('id'+str(i)) for i in range(11)])):
            with self.assertRaises(Review):self.cache.lesson_images(data)
        self.assertEqual(self.opener.calls,[])

    def test_cache_corruption_stops_without_redownload(self):
        self.cache.fetch(URL)
        path=next(self.cache.directory.glob('*.png'));path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(Review,'asset_cache_invalid'):self.cache.fetch(URL)
        self.assertEqual(len(self.opener.calls),1)

    def test_other_account_cache_rejected_without_mutation(self):
        directory=self.folder/'foreign';directory.mkdir();path=directory/'assets.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE meta(account TEXT,origin TEXT)')
            db.execute('INSERT INTO meta VALUES(?,?)',('mv-centr','https://shop.mv-centr.ru'));db.commit()
        original=path.read_bytes()
        with self.assertRaisesRegex(Review,'asset_cache_account_mismatch'):assets.AssetCache(directory)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(self.opener.calls,[])

    def test_canonical_inline_png_is_preserved_and_uses_private_hashed_blob_cache(self):
        encoded=base64.b64encode(png()).decode('ascii');url='data:image/png;base64,'+encoded
        source=payload(image('inline',url));before=copy.deepcopy(source)
        result=self.cache.lesson_images(source)
        self.assertEqual(result,{'inline':encoded});self.assertEqual(source,before)
        self.assertEqual(self.cache.fetch(url),(png(),'png'))
        self.assertEqual(self.opener.calls,[])
        self.assertEqual(len(list(self.cache.directory.glob('*.png'))),1)
        rows=self.cache.db.execute('SELECT url_hash,url FROM assets').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['url_hash'],hashlib.sha256(url.encode()).hexdigest())
        self.assertTrue(rows[0]['url'].startswith('data:image/png;sha256,'))
        self.assertNotIn(encoded,rows[0]['url'])
        self.cache.close()
        with assets.AssetCache(self.folder/'private-assets') as reopened:
            self.assertEqual(reopened.fetch(url),(png(),'png'))
        self.assertEqual(self.opener.calls,[])

    def test_inline_type_must_agree_with_real_magic_and_no_svg_is_accepted(self):
        encoded=base64.b64encode(png()).decode('ascii')
        for mime in ('image/jpeg','image/jpg','image/webp','image/svg+xml','text/html'):
            with self.subTest(mime=mime),self.assertRaises(Review):
                self.cache.fetch('data:'+mime+';base64,'+encoded)
        self.assertEqual(self.opener.calls,[])
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],0)

    def test_explicit_jpeg_alias_is_forwarded_to_the_raster_validator(self):
        raw=b'synthetic JPEG bytes';encoded=base64.b64encode(raw).decode('ascii')
        for mime in ('image/jpeg','image/jpg'):
            with self.subTest(mime=mime),patch.object(assets,'_inspect',return_value='jpg') as inspect:
                self.assertEqual(self.cache.fetch('data:'+mime+';base64,'+encoded),(raw,'jpg'))
                self.assertIn((raw,mime),[call.args for call in inspect.call_args_list])
        self.assertEqual(self.opener.calls,[])

    def test_malformed_or_noncanonical_base64_is_rejected_before_decoding(self):
        encoded=base64.b64encode(png()).decode('ascii')
        alphabet=assets.BASE64_ALPHABET
        if encoded.endswith('=='):
            noncanonical=encoded[:-3]+alphabet[alphabet.index(encoded[-3])+1]+'=='
        else:
            noncanonical='AB=='
        invalid=[encoded.rstrip('='),encoded+'=',encoded[:4]+'\n'+encoded[4:],
                 encoded[:4]+'-'+encoded[5:],encoded+'é',noncanonical,'']
        with patch.object(assets.base64,'b64decode',side_effect=AssertionError('must reject before allocation')) as decoder:
            for value in invalid:
                with self.subTest(value=value[:8]),self.assertRaises(Review):
                    self.cache.fetch('data:image/png;base64,'+value)
            for prefix in ('data:image/png;charset=utf-8;base64,','data:image/PNG;base64,','data:image/png;base64url,'):
                with self.subTest(prefix=prefix),self.assertRaises(Review):self.cache.fetch(prefix+encoded)
            decoder.assert_not_called()
        self.assertEqual(self.opener.calls,[])

    def test_oversized_inline_image_is_rejected_before_decode_and_cache_write(self):
        encoded=base64.b64encode(b'x'*33).decode('ascii')
        with patch.object(assets,'MAX_IMAGE',32),patch.object(assets.base64,'b64decode',side_effect=AssertionError('oversize allocation')) as decoder:
            for value in (encoded,encoded+'AAAA'):
                with self.assertRaisesRegex(Review,'asset_image_size_invalid'):
                    self.cache.fetch('data:image/png;base64,'+value)
            decoder.assert_not_called()
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],0)
        self.assertEqual(self.opener.calls,[])

    def test_inline_images_share_network_blob_cache_and_keep_ten_image_limit(self):
        url='data:image/png;base64,'+base64.b64encode(png()).decode('ascii')
        self.cache.fetch(URL);self.cache.fetch(url)
        self.assertEqual(len(list(self.cache.directory.glob('*.png'))),1)
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],2)
        self.assertEqual(len(self.opener.calls),1)
        self.assertEqual(len(self.cache.lesson_images(payload(*[image('inline'+str(i),url) for i in range(10)]))),10)
        with patch.object(self.cache,'fetch',side_effect=AssertionError('all images must be preflighted')) as fetch:
            with self.assertRaisesRegex(Review,'asset_too_many_images'):
                self.cache.lesson_images(payload(*[image('inline'+str(i),url) for i in range(11)]))
            fetch.assert_not_called()

    def test_bad_inline_source_stops_whole_lesson_before_first_network_download(self):
        with self.assertRaises(Review):
            self.cache.lesson_images(payload(image(),image('inline','data:image/png;base64,AB==')))
        self.assertEqual(self.opener.calls,[])

    def test_verified_ru_cdn_allows_only_exact_host_safe_raster_paths_without_query(self):
        valid='https://f1.autoweboffice.ru/mastergroup/school/Abc12345-_.jpg'
        for url in (valid,'https://f1.autoweboffice.ru/other/test.jpg',
                    'https://f1.autoweboffice.ru/mastergroup/school/test.png',
                    'https://f1.autoweboffice.ru/mastergroup/school/dir/test.webp',
                    'https://f1.autoweboffice.ru/iomp/unnamed.jpeg'):
            self.assertEqual(assets._url(url),url)
        for url in ('https://f2.autoweboffice.ru/mastergroup/school/test.jpg',
                    'https://f1.autoweboffice.ru.evil.test/mastergroup/school/test.jpg',
                    'https://f1.autoweboffice.ru/mastergroup/school/%2e%2e.jpg',
                    valid+'?token=private',valid+'#fragment',
                    'https://user:password@f1.autoweboffice.ru/mastergroup/school/test.jpg'):
            with self.subTest(url=url),self.assertRaises(Review):assets._url(url)
        self.assertEqual(self.opener.calls,[])

    def test_verified_ru_unicode_raster_paths_keep_exact_encoded_request_and_cache_key(self):
        url='https://f1.autoweboffice.ru/%D1%83%D1%80%D0%BE%D0%BA%D0%B8/course%20one/%D1%84%D0%BE%D1%82%D0%BE.PNG'
        self.assertEqual(assets._url(url),url)
        self.opener.response=Response(url)
        self.assertEqual(self.cache.fetch(url),(png(),'png'))
        self.assertEqual(self.opener.calls[0][0].full_url,url)
        request,timeout=self.opener.calls[0]
        self.assertEqual(timeout,25)
        self.assertFalse({'cookie','authorization'} & {name.lower() for name in request.headers})
        row=self.cache.db.execute('SELECT url,url_hash FROM assets').fetchone()
        self.assertEqual(row['url'],url)
        self.assertEqual(row['url_hash'],hashlib.sha256(url.encode()).hexdigest())

    def test_verified_ru_rejects_traversal_malformed_encoding_non_rasters_and_other_hosts(self):
        origin='https://f1.autoweboffice.ru'
        paths=['/a/../image.jpg','/a/%2e%2e/image.jpg','/a/%252e%252e/image.jpg',
               '/a/%2Fprivate/image.jpg','/a/%5cimage.jpg','/a/%00image.jpg',
               '/a/%0aimage.jpg','/a/%7fimage.jpg','/a/%FFimage.jpg','/a/%G0image.jpg',
               '/a/image%.jpg','/a/image%2.jpg','/a//image.jpg','//a/image.jpg',
               '/a/.hidden.jpg','/a/image.svg','/a/script.html','/a/image.jpg/extra',
               '/a/image.jpg?','/a/image.jpg#','/a/%3fsecret/image.jpg']
        for path in paths:
            with self.subTest(path=path),self.assertRaises(Review):assets._url(origin+path)
        for url in ('http://f1.autoweboffice.ru/a/image.jpg','https://f1.autoweboffice.ru:443/a/image.jpg',
                    'https://u:p@f1.autoweboffice.ru/a/image.jpg','https://f1.autoweboffice.ru.evil.test/a/image.jpg',
                    'https://f2.autoweboffice.ru/a/image.jpg','https://getcourse.ru/public/img/default_profile_50.png',
                    'https://vk.com/emoji/e/synthetic.png','https://lh6.googleusercontent.com/image.png'):
            with self.subTest(url=url),self.assertRaises(Review):assets._url(url)
        self.assertEqual(self.opener.calls,[])

    def test_verified_ru_route_never_weakens_source_account_binding(self):
        url='https://f1.autoweboffice.ru/lessons/image.jpg'
        with patch.object(assets,'ACCOUNT','mv-centr'):
            with self.assertRaisesRegex(Review,'asset_account_mismatch'):assets._url(url)
        with patch.object(assets,'ORIGIN','https://shop.mv-centr.ru'):
            with self.assertRaisesRegex(Review,'asset_account_mismatch'):assets._url(url)
        self.assertEqual(self.opener.calls,[])

    def test_verified_getcourse_route_is_exact_and_keeps_anonymous_download_guards(self):
        route='/fileservice/file/thumbnail/h/'+'a'*32+'.png/s/f1200x/a/12345/sc/123'
        valid='https://fs-thb01.getcourse.ru'+route
        self.assertEqual(assets._url(valid),valid)
        self.opener.response=Response(valid)
        self.assertEqual(self.cache.fetch(valid),(png(),'png'))
        request,timeout=self.opener.calls[0]
        self.assertEqual(timeout,25)
        self.assertFalse({'cookie','authorization'} & {name.lower() for name in request.headers})
        for url in ('https://fs-thb02.getcourse.ru'+route,
                    'https://fs-thb01.getcourse.ru.evil.test'+route,
                    'https://fs-thb01.getcourse.ru'+route.replace('/thumbnail/','/download/'),
                    valid.replace('a'*32,'A'*32),valid.replace('.png/','.jpg/'),
                    valid.replace('f1200x','f120x'),valid.replace('f1200x','f1200x50'),
                    valid.replace('/a/12345/','/a/123456/'),valid.replace('/sc/123','/sc/12'),
                    valid+'/extra',valid+'?token=private',valid+'#fragment',
                    'https://user:password@fs-thb01.getcourse.ru'+route,
                    'https://fs-thb01.getcourse.ru:443'+route,
                    'https://cdn1.savepice.ru/uploads/2020/1/01/'+'a'*32+'-full.png'):
            with self.subTest(url=url),self.assertRaises(Review):assets._url(url)
        self.assertEqual(len(self.opener.calls),1)


if __name__=='__main__':unittest.main()
