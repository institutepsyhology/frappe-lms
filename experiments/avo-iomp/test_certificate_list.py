import base64
import copy
from html import unescape
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch
import unittest

from import_capture import ARCHIVE, Review, normalize_review, plan_import, preflight_source
from certificate_list import LINK_LABEL, PAGE_URL, TARGETS, certificate_page_document, normalize_certificate_list
from normalize_iomp_archive_html import normalize_iomp_archive_html
from install_certificate_page import install


def read_capture(course, lesson):
    paths = sorted((ARCHIVE / f'course-{course}').rglob(f'lesson-{lesson}.json'))
    if not paths:
        raise unittest.SkipTest('private capture unavailable')
    return json.loads(paths[-1].read_text(encoding='utf8'))['payload']


class CertificateListTests(unittest.TestCase):
    def test_all_captured_widgets_become_one_link_and_preserve_surroundings(self):
        for course, lesson in sorted(TARGETS):
            with self.subTest(course=course, lesson=lesson):
                payload = read_capture(course, lesson)
                before = copy.deepcopy(payload['ape']['children'])
                normalize_certificate_list(payload)
                after = payload['ape']['children']
                self.assertEqual(before[:1] + before[3:], after[:1] + after[2:])
                self.assertEqual(after[1]['fields']['html'], LINK_LABEL)
                self.assertEqual(after[1]['fields']['url'], PAGE_URL)
                prepared = copy.deepcopy(payload)
                normalize_certificate_list(payload)
                self.assertEqual(payload, prepared)
                normalize_iomp_archive_html(payload)
                normalize_review(payload)
                preflight_source([payload])
                blocks = json.dumps(plan_import(payload, {})['blocks'], ensure_ascii=False)
                self.assertEqual(blocks.count(PAGE_URL), 1)
                self.assertNotIn('{certificate_', blocks)
                if lesson in ('5299', '5530'):
                    blocks = unescape(''.join(base64.b64decode(block['data']['encodedHtml']).decode()
                                             for block in json.loads(blocks) if block['type'] == 'htmlBlock'))
                    self.assertIn('Оставить заявку', blocks)
                    self.assertIn('ИДУ НА КУРС!', blocks)
                    offer_url = before[3]['children'][1]['children'][0]['fields']['url']
                    self.assertIn(offer_url, blocks)

    def test_other_school_and_changed_widget(self):
        payload = read_capture('296', '5726')
        payload['account'] = 'mv-centr'
        before = copy.deepcopy(payload)
        normalize_certificate_list(payload)
        self.assertEqual(payload, before)
        payload['account'] = 'iomp'
        payload['ape']['children'][2]['children'][0]['children'][0]['fields']['html'] += ' edited'
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(Review, 'certificate_widget_changed'):
            normalize_certificate_list(payload)
        self.assertEqual(payload, before)

    def test_5069_only_the_confirmed_purchase_condition_is_removed(self):
        payload = read_capture('271', '5069')
        original = copy.deepcopy(payload)
        condition = original['ape']['children'][2]['fields']['visibleConditions']['conditions']
        self.assertEqual([(row['typeId'], row['goodsIds']) for row in condition], [('purchaseGoods', ['1336'])])
        expected = copy.deepcopy(original)
        fields = expected['ape']['children'][2]['fields']
        del fields['visibleConditions']
        fields.update(html=LINK_LABEL, url=PAGE_URL)
        normalize_certificate_list(payload)
        normalize_certificate_list(payload)
        self.assertEqual(payload, expected)
        changed = copy.deepcopy(original)
        changed['ape']['children'][2]['fields']['visibleConditions']['conditions'][0]['goodsIds'] = ['1337']
        before = copy.deepcopy(changed)
        with self.assertRaisesRegex(Review, 'certificate_widget_changed'):
            normalize_certificate_list(changed)
        self.assertEqual(changed, before)


    def test_installer_retries_without_replacing_or_duplicating_records(self):
        from import_capture import Stop
        client = Mock(account='iomp', site='my-lk.iomp.ru')
        stored = {}
        def call(method, args):
            if method == 'list_documents':
                return {'documents': [{'name': 'fixture'}] if stored else [], 'has_next_page': False}
            return stored.copy()
        client.call.side_effect = call
        def create(_client, name, args):
            self.assertEqual(name, 'create_document')
            stored.update(args['data'])
        with patch('install_certificate_page.mutate', side_effect=create) as write:
            self.assertEqual(install(client), 'ready_to_create')
            self.assertEqual(install(client, True), 'created_and_verified')
            self.assertEqual(install(client, True), 'verified')
            self.assertEqual(write.call_count, 1)
            stored['title'] = 'Other'
            with self.assertRaisesRegex(Stop, 'certificate_page_route_already_occupied'):
                install(client, True)
            client.site = 'my-lk.mastervision.su'
            with self.assertRaisesRegex(Stop, 'wrong_frappe_site'):
                install(client, True)
            self.assertEqual(write.call_count, 1)


def check_template(source, test):
    from jinja2.sandbox import SandboxedEnvironment
    from html.parser import HTMLParser

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.links.append(dict(attrs))

    template = SandboxedEnvironment().from_string(source)
    def page(user, count, page_no):
        calls = []
        def list_rows(doctype, fields, filters, order_by, limit_start, limit_page_length):
            test.assertEqual(doctype, 'LMS Certificate')
            test.assertEqual(filters, {'member': user})
            test.assertEqual(order_by, 'issue_date desc, name asc')
            test.assertEqual(limit_page_length, 51)
            calls.append(limit_start)
            return [{'course_title': '<script>alert(0)</script>', 'batch_title': None, 'issue_date': None,
                     'name': f'C#/{i}', 'template': None if i % 2 else 'Шаблон & PDF'}
                    for i in range(limit_start, min(count, limit_start + limit_page_length))]
        session = SimpleNamespace(user=user)
        args = dict(member='somebody_else', page=page_no)
        html = template.render(frappe=SimpleNamespace(session=session, get_list=list_rows, form_dict=args))
        test.assertNotIn('<script>', html)
        parser = Links()
        parser.feed(html)
        return html, parser.links, calls
    html, links, calls = page('Guest', 52, '2')
    test.assertEqual(calls, [])
    test.assertEqual([link['href'] for link in links], ['/login?redirect-to=%2Fpersonal%2Fcertificate'])
    for count, number, issued, next_page, offset in [
            (0, '1', 0, False, 0), (50, '1', 50, False, 0), (51, '1', 50, True, 0),
            (100, '2', 50, False, 50), (51, '2', 1, False, 50), (1, '-1', 1, False, 0),
            (1, '99999999999999999', 1, False, 0), (1, 'garbage', 1, False, 0)]:
        html, links, calls = page('student', count, number)
        test.assertEqual(calls, [offset])
        test.assertEqual(next_page, any(link.get('rel') == 'next' for link in links))
        files = [parse_qs(urlsplit(link['href']).query) for link in links if 'download_pdf?' in link['href']]
        test.assertEqual(len(files), issued)
        for i, query in enumerate(files, offset):
            test.assertEqual(query['doctype'], ['LMS Certificate'])
            test.assertEqual(query['name'], [f'C#/{i}'])
            test.assertEqual(query.get('format'), None if i % 2 else ['Шаблон & PDF'])


class CertificateTemplateTests(unittest.TestCase):
    def test_guest_own_empty_page_boundaries_and_escaped_pdf_urls(self):
        try:
            import jinja2
        except ImportError:
            self.skipTest('requires the Jinja runtime used by Frappe')
        check_template(certificate_page_document()['main_section_html'], self)


if __name__ == '__main__':
    unittest.main()
