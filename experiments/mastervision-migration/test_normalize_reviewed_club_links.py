import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
import normalize_reviewed_club_links as subject


FRAGMENTS = ('<p><strong>Choose payment:</strong></p>',
             '<p>Old yearly price<br>Old quarter price<br>Old month price</p>',
             '<p>Pay below:</p>')


def text(html, optional=False):
    fields = {'anchor': '', 'html': html}
    if optional:
        fields.update(displayDelay=None, visibleConditions=None)
    return {'name': 'text', 'fields': fields}


def frame(path, second=False):
    attrs = ('width="100%" height="3100px"' if second else
             'style="position:absolute;top:0;left:0;width:100%;height:100%"')
    return '<p><iframe src="https://source.example.org' + path + '" ' + attrs + ' frameborder="0" allowfullscreen=""></iframe></p>'


def fixture():
    intro = '<h1>Hello, {name}!</h1><p>Keep subscription access rule.</p>' + ''.join(FRAGMENTS)
    payments = [{'name': 'button', 'fields': {'html': f'Old payment {i}',
                 'url': f'https://example.org/old-payment/{i}', 'linkType': 'url'}} for i in range(6)]
    return {'name': 'page', 'children': [text(intro, True), *payments,
        text('<p>Keep support: <a href="https://example.org/support">Contact help</a>.</p>'),
        text(frame('/'), True), text(frame('/schedule/', True), True)]}


def expected(source):
    result = copy.deepcopy(source)
    for fragment in FRAGMENTS:
        result['children'][0]['fields']['html'] = result['children'][0]['fields']['html'].replace(fragment, '', 1)
    result['children'][8]['fields']['html'] = '<p><a href="https://example.org/" target="_blank" rel="noopener noreferrer">Клуб «Профит»</a></p>'
    result['children'][9]['fields']['html'] = '<p><a href="https://example.org/schedule/" target="_blank" rel="noopener noreferrer">Расписание клуба «Профит»</a></p>'
    result['children'] = [node for i, node in enumerate(result['children']) if i not in range(1, 7)]
    return result


def bindings(source):
    stack = ExitStack()
    stack.enter_context(patch.object(subject, 'SOURCE_APE_SHA256', subject._digest(source)))
    stack.enter_context(patch.object(subject, 'NODE_SHA256', {i: subject._digest(n) for i, n in enumerate(source['children'])}))
    stack.enter_context(patch.object(subject, 'RESULT_APE_SHA256', subject._digest(expected(source))))
    stack.enter_context(patch.object(subject, 'SOURCE_HOST', 'source.example.org'))
    stack.enter_context(patch.object(subject, 'CANONICAL_HOST', 'example.org'))
    stack.enter_context(patch.object(subject, 'PAYMENT_FRAGMENTS', tuple(
        (ordinal, subject._sha(html)) for ordinal, html in zip((2, 4, 7), FRAGMENTS))))
    frames = copy.deepcopy(subject.FRAMES)
    for i, binding in frames.items():
        html = source['children'][i]['fields']['html']
        node = next(n for n in subject._Document(html).nodes if n['tag'] == 'iframe')
        binding['source_url_sha256'] = subject._sha(node['attrs']['src'])
        binding['iframe_sha256'] = subject._sha(html[node['start']:node['end']])
        binding['canonical_url_sha256'] = subject._sha('https://example.org' + binding['path'])
    stack.enter_context(patch.object(subject, 'FRAMES', frames))
    return stack


def normalize(source, cid=619, lid=6883):
    return subject.normalize_reviewed_club_links(source, cid, lid, static_validator())


class ReviewedClubLinkTests(unittest.TestCase):
    def test_payment_only_is_removed_and_nonpayment_intro_and_support_stay_exact(self):
        source = fixture()
        before = copy.deepcopy(source)
        with bindings(source):
            result, changes = normalize(source)
            self.assertEqual(result, expected(source))
            self.assertEqual(normalize(source), (result, changes))
        self.assertEqual(source, before)
        self.assertEqual(len(result['children']), 4)
        self.assertEqual(result['children'][1], source['children'][7])
        self.assertIn('Hello, {name}!', result['children'][0]['fields']['html'])
        self.assertIn('Keep subscription access rule.', result['children'][0]['fields']['html'])
        self.assertNotIn('Old payment', json.dumps(result))
        self.assertNotIn('Old yearly price', json.dumps(result))

    def test_both_iframes_become_real_distinct_links_and_pass_the_core_directly(self):
        source = fixture()
        with bindings(source):
            result, _ = normalize(source)
        self.assertIn('href="https://example.org/"', result['children'][2]['fields']['html'])
        self.assertIn('href="https://example.org/schedule/"', result['children'][3]['fields']['html'])
        self.assertNotIn('<iframe', json.dumps(result))
        # Do not feed an already scoped-helper result through that same scoped
        # helper again after its integration. The converter accepts this output.
        payload = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                   'course_id': 619, 'lesson_id': 6883, 'course_title': 'Synthetic',
                   'lesson_title': 'Synthetic', 'format': 'ape', 'ape': result}
        plan = _core().plan_import(payload)
        self.assertTrue(plan['ready'], plan['issues'])
        self.assertEqual(len(plan['blocks']), 4)

    def test_owner_omissions_and_link_changes_have_hash_witnesses_without_private_urls(self):
        source = fixture()
        with bindings(source):
            _, changes = normalize(source)
        self.assertEqual(len([c for c in changes if c['action'] == 'payment_button_omitted']), 6)
        self.assertEqual(len([c for c in changes if c['action'] == 'payment_paragraph_omitted']), 3)
        links = [c for c in changes if c['action'] == 'iframe_replaced_by_verified_public_link']
        self.assertEqual([c['path'] for c in links], [[8], [9]])
        self.assertTrue(all(c['legacy_iframe_layout_replaced'] for c in links))
        self.assertTrue(changes[0]['literal_greeting_placeholder_preserved'])
        for value in ('https://', 'Contact help', 'Hello, {name}'):
            self.assertNotIn(value, json.dumps(changes))

    def test_source_text_link_condition_order_and_caption_changes_stop(self):
        source = fixture()
        variants = []
        for index, key, value in ((0, 'html', '<p>New teaching text.</p>'),
                                  (7, 'html', '<p><a href="https://example.org/new">New help</a></p>'),
                                  (8, 'visibleConditions', {'paid': True}),
                                  (1, 'url', 'https://example.org/new-payment')):
            changed = copy.deepcopy(source)
            changed['children'][index]['fields'][key] = value
            variants.append(changed)
        changed = copy.deepcopy(source)
        changed['children'][9]['style'] = {'caption': 'Keep image caption'}
        variants.append(changed)
        changed = copy.deepcopy(source)
        changed['children'].reverse()
        variants.append(changed)
        with bindings(source):
            for changed in variants:
                with self.subTest(changed=changed), self.assertRaisesRegex(Review, 'source_changed'):
                    normalize(changed)

    def test_unknown_css_retained_condition_and_caption_are_not_silently_dropped(self):
        variants = []
        source = fixture()
        source['children'][7]['fields']['html'] = '<p style="display:none">Keep hidden text.</p>'
        variants.append(source)
        source = fixture()
        source['children'][8]['fields']['visibleConditions'] = {'paid': True}
        variants.append(source)
        source = fixture()
        source['children'][8]['style'] = {'caption': 'Keep meaningful caption'}
        variants.append(source)
        for source in variants:
            with bindings(source), self.subTest(source=source), self.assertRaises(Review):
                normalize(source)

    def test_only_exact_source_https_host_path_without_tokens_or_auth_is_accepted(self):
        for url in ('http://source.example.org/', 'https://source.example.org:443/',
                    'https://user:secret@source.example.org/', 'https://source.example.org/?token=x',
                    'https://source.example.org/#content', 'https://other.example.org/',
                    'https://source.example.org/another/', 'https://source.example.org//'):
            source = fixture()
            source['children'][8]['fields']['html'] = frame('/').replace('https://source.example.org/', url)
            with bindings(source), self.subTest(url=url), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)

    def test_meaningful_iframe_fallback_or_adjacent_material_cannot_be_replaced(self):
        for html in (frame('/').replace('</iframe>', 'Keep fallback text</iframe>'),
                     '<p>Keep adjacent material.</p>' + frame('/'),
                     frame('/').replace('<p>', '<p title="Keep wrapper meaning">', 1)):
            source = fixture()
            source['children'][8]['fields']['html'] = html
            with bindings(source), self.subTest(html=html), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)

    def test_changed_payment_fragment_canonical_target_or_result_digest_is_refused(self):
        source = fixture()
        with bindings(source):
            wrong = list(subject.PAYMENT_FRAGMENTS)
            wrong[0] = (wrong[0][0], '0' * 64)
            with patch.object(subject, 'PAYMENT_FRAGMENTS', tuple(wrong)), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)
            changed = copy.deepcopy(subject.FRAMES)
            changed[8]['canonical_url_sha256'] = '0' * 64
            with patch.object(subject, 'FRAMES', changed), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)
            with patch.object(subject, 'RESULT_APE_SHA256', '0' * 64), self.assertRaisesRegex(Review, 'material_mismatch'):
                normalize(source)

    def test_other_lessons_unchanged_and_mastervision_account_is_required(self):
        source = fixture()
        result, changes = normalize(source, 619, 6884)
        self.assertEqual((result, changes), (source, []))
        self.assertIsNot(result, source)
        with patch.object(subject, 'ACCOUNT', 'mvcentr'), self.assertRaisesRegex(Review, 'account_mismatch'):
            normalize(source)
        with self.assertRaisesRegex(Review, 'source_invalid'):
            normalize(source, True, 6883)

    def test_nonfinite_unserializable_and_invalid_unicode_source_use_club_fatal_code(self):
        for value in (float('nan'), object(), '\ud800'):
            source = fixture()
            source['children'][0]['fields']['html'] = value
            with self.subTest(value=type(value).__name__), self.assertRaisesRegex(Review, '^reviewed_club_source_invalid$'):
                normalize(source)

    def test_all_public_hash_bindings_are_complete_and_contain_no_source_urls(self):
        values = [subject.SOURCE_APE_SHA256, subject.RESULT_APE_SHA256,
                  *subject.NODE_SHA256.values(), *[v[1] for v in subject.PAYMENT_FRAGMENTS]]
        for binding in subject.FRAMES.values():
            values.extend(binding[key] for key in ('source_url_sha256', 'canonical_url_sha256', 'iframe_sha256'))
        self.assertTrue(all(len(value) == 64 and not set(value) - set('0123456789abcdef') for value in values))


if __name__ == '__main__':
    unittest.main()
