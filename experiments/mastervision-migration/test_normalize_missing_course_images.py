import copy
import unittest
from unittest.mock import patch

from importer import Review
import normalize_missing_course_images as mod
from normalize_source import static_validator


MISSING = '<img width="10" height="20" src="https://example.test/missing.png">'
LIVE = '<img src="https://example.test/live.png">'


def page(markup):
    return {'name': 'page', 'children': [
        {'id': 'original', 'name': 'text', 'fields': {'html': markup, 'anchor': ''}, 'style': {}}]}


def binding(source, tag=MISSING, path=None, result=None):
    from html.parser import HTMLParser
    class Img(HTMLParser):
        def handle_starttag(self, name, attrs):
            if name == 'img': self.src = dict(attrs)['src']
    parser = Img(); parser.feed(tag); parser.close()
    return {'course_id': 520, 'lesson_id': 5171, 'path': [0] if path is None else path,
            'kind': 'html', 'source_sha256': mod._sha(source),
            'result_sha256': mod._sha(source.replace(tag, '', 1) if result is None else result),
            'images': [[mod._sha(parser.src), mod._sha(tag)]]}


class MissingCourseImageTests(unittest.TestCase):
    def test_v17_integration_retains_original_and_audio_receipt_and_replays(self):
        from normalize_source import normalize_payload
        from test_normalize_audio import audio,key,receipt
        from lms.lms.avo_transform import plan_import
        source=MISSING+'<p>Keep all authored material.</p>'
        data={'account':'mastervision','source_origin':'https://shop.mastervision.su',
              'course_id':520,'lesson_id':5171,'course_title':'Synthetic','lesson_title':'Synthetic',
              'format':'ape','ape':page(source)}
        data['ape']['children'].append(audio());before=copy.deepcopy(data)
        with patch.object(mod,'BINDINGS',[binding(source)]):
            normalized,codes=normalize_payload(data,{key():receipt()})
            self.assertEqual(data,before)
            self.assertEqual(normalized['source_original_ape'],data['ape'])
            self.assertEqual(normalized['source_normalization']['version'],17)
            self.assertIn(mod.CODE,codes)
            self.assertTrue(plan_import(normalized)['ready'])
            self.assertEqual(normalize_payload(normalized),(normalized,codes))

    def clean(self, source, *, tree=None, selected=None, cid=520, lid=5171):
        with patch.object(mod, 'BINDINGS', [binding(source)] if selected is None else selected):
            return mod.normalize_missing_course_images(
                page(source) if tree is None else tree, cid, lid, static_validator())

    def test_only_bound_img_removed_all_other_bytes_preserved(self):
        source = ('<p>  Text &amp; line\n<a href="https://example.test/file" target="_blank">File</a>'
                  '<span style="color:red">' + MISSING + '</span> end</p>' + LIVE +
                  '<table><tbody><tr><td>One</td><td>Two</td></tr></tbody></table>')
        tree = page(source); before = copy.deepcopy(tree)
        expected = source.replace('<span style="color:red">' + MISSING + '</span>', '')
        out, changes = self.clean(source, tree=tree, selected=[binding(source, result=expected)])
        self.assertEqual(tree, before)
        self.assertEqual(out['children'][0]['fields']['html'], expected)
        self.assertEqual(changes[0]['images'], 1)
        self.assertEqual(changes[0]['path'], [0])
        self.assertNotIn('http', repr(changes))
        self.assertEqual(out['children'][0]['id'], 'original')

    def test_only_missing_image_wrappers_removed_whitespace_preserved(self):
        source = '<span style="transform:rotate(3.14rad)"> \n<span style="display:inline-block;overflow:hidden;width:602px;height:380px">' + MISSING + '</span>\t</span>'
        expected = ' \n\t'
        out, changes = self.clean(source, selected=[binding(source, result=expected)])
        self.assertEqual(out['children'][0]['fields']['html'], expected)
        self.assertEqual(changes[0]['empty_image_wrappers'], 2)
        for inside in ('Keep ' + MISSING, MISSING + LIVE,
                       '<a href="https://example.test/file">' + MISSING + '</a>'):
            source = '<span>' + inside + '</span>'
            out, _ = self.clean(source)
            self.assertEqual(out['children'][0]['fields']['html'], source.replace(MISSING, ''))
        for css in ('display:none', 'overflow:scroll', 'height:9000px',
                    'transform:rotate(180deg)', 'background-image:url(x)', 'content:label'):
            source = '<span style="' + css + '">' + MISSING + '</span>'
            out, changes = self.clean(source)
            self.assertEqual(out['children'][0]['fields']['html'], source.replace(MISSING, ''))
            self.assertEqual(changes[0]['empty_image_wrappers'], 0)

    def test_exact_result_is_idempotent_and_live_or_redirect_not_omitted(self):
        source = MISSING + LIVE + '<img src="https://example.test/redirect.png">'
        selected = [binding(source)]
        out, changes = self.clean(source, selected=selected)
        self.assertTrue(changes)
        with patch.object(mod, 'BINDINGS', selected):
            self.assertEqual(mod.normalize_missing_course_images(out, 520, 5171, static_validator()), (out, []))
        self.assertIn(LIVE, out['children'][0]['fields']['html'])
        self.assertIn('redirect.png', out['children'][0]['fields']['html'])

    def test_future_html_src_tag_and_binding_changes_require_review(self):
        selected = [binding(MISSING)]
        for source in (MISSING + 'new', MISSING.replace('missing.png', 'new.png'),
                       MISSING.replace('width="10"', 'width="11"'), 'future replacement'):
            with self.subTest(source=source), self.assertRaises(Review):
                self.clean(source, selected=selected)
        for field in ('source_sha256', 'result_sha256'):
            changed = copy.deepcopy(selected); changed[0][field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(Review): self.clean(MISSING, selected=changed)
        for index in (0, 1):
            changed = copy.deepcopy(selected); changed[0]['images'][0][index] = '0' * 64
            with self.subTest(index=index), self.assertRaises(Review): self.clean(MISSING, selected=changed)

    def test_outside_account_specific_numeric_scope_stays_unchanged(self):
        for cid, lid in ((519, 5171), (520, 5176), (618, 5171)):
            tree = page(MISSING)
            self.assertEqual(self.clean(MISSING, cid=cid, lid=lid), (tree, []))
        with patch.object(mod, 'ACCOUNT', 'mvcentr'):
            with self.assertRaisesRegex(Review, 'account_mismatch'): self.clean(MISSING)

    def test_moved_paths_missing_and_duplicate_bindings_require_review(self):
        tree = page(MISSING); tree['children'].insert(0, {'name': 'text', 'fields': {'html': 'Keep'}})
        for value in (tree, {'name': 'page', 'children': []}):
            with self.assertRaises(Review): self.clean(MISSING, tree=value)
        selected = [binding(MISSING), binding(MISSING)]
        with self.assertRaises(Review): self.clean(MISSING, selected=selected)
        selected = [binding(MISSING)]; selected[0]['images'] *= 2
        with self.assertRaises(Review): self.clean(MISSING, selected=selected)

    def test_protected_source_and_unknown_fields_are_never_dropped(self):
        for extra in ({'anchor': 'chapter'}, {'visibleConditions': {'paid': True}},
                      {'displayDelay': 100}, {'caption': 'Keep'}):
            tree = page(MISSING); tree['children'][0]['fields'].update(extra)
            with self.subTest(extra=extra), self.assertRaises(Review): self.clean(MISSING, tree=tree)
        for key, value in (('children', [{'name': 'text', 'fields': {'html': 'Keep'}}]),
                           ('other', 'meaningful'), ('style', {'caption': 'Keep'})):
            tree = page(MISSING); tree['children'][0][key] = value
            with self.subTest(key=key), self.assertRaises(Review): self.clean(MISSING, tree=tree)
        tree = page(MISSING); tree['fields'] = {'visibleConditions': {'paid': True}}
        with self.assertRaises(Review): self.clean(MISSING, tree=tree)

    def test_nonempty_alt_events_duplicate_attrs_do_not_authorize_removal(self):
        for tag in (MISSING.replace('>', ' alt="Diagram">'),
                    MISSING.replace('>', ' onload="run()">'),
                    MISSING.replace('>', ' src="https://example.test/other.png">')):
            with self.subTest(tag=tag), self.assertRaises(Review):
                self.clean(tag, selected=[binding(tag, tag)])

    def test_unrelated_unknown_html_and_live_rotation_are_byte_exact(self):
        source = ('<script>unknown()</script><span style="transform:rotate(3.14rad)">' + LIVE +
                  '</span><span>' + MISSING + '</span>')
        expected = source.replace('<span>' + MISSING + '</span>', '')
        out, _ = self.clean(source, selected=[binding(source, result=expected)])
        self.assertEqual(out['children'][0]['fields']['html'], expected)
        with self.assertRaises(ValueError): static_validator()(out['children'][0]['fields']['html'])

    def test_native_images_have_no_unverified_bindings_and_stay_unchanged(self):
        tree = {'name': 'page', 'children': [{'name': 'image', 'fields': {'imageSrc': 'https://example.test/image.png'}}]}
        self.assertEqual(self.clean(MISSING, tree=tree, lid=5176), (tree, []))
        selected = [binding(MISSING)]; selected[0]['kind'] = 'image'
        with self.assertRaises(Review): self.clean(MISSING, tree=tree, selected=selected)

    def test_material_mismatch_and_invalid_source_fail_closed(self):
        with patch.object(mod, '_material', side_effect=[[('text', 'before')], [('text', 'after')]]):
            with self.assertRaisesRegex(Review, 'material_mismatch'): self.clean(MISSING)
        for tree, cid, lid in ((None, 520, 5171), ({'name': 'page'}, 520, 5171),
                               (page(MISSING), True, 5171), (page(MISSING), 520, False)):
            with self.assertRaises(Review):
                mod.normalize_missing_course_images(tree, cid, lid, static_validator())

    def test_public_bindings_are_only_confirmed_404_metadata(self):
        self.assertEqual(len(mod.BINDINGS), 26)
        self.assertEqual(sum(len(item['images']) for item in mod.BINDINGS), 47)
        self.assertTrue(all(item['course_id'] == 520 and item['kind'] == 'html' for item in mod.BINDINGS))
        self.assertNotIn(5176, {item['lesson_id'] for item in mod.BINDINGS})
        self.assertNotIn('http', repr(mod.BINDINGS))


if __name__ == '__main__': unittest.main()
