"""Synthetic image cache and HTTP stubs only; no network or real source data."""
import base64
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
                         Response(URL,png()[:-1]+b'!'),Response(URL,png(width=4097))]:
            self.opener.response=response
            with self.assertRaises(Review):self.cache.fetch(URL)
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],0)

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


if __name__=='__main__':unittest.main()
