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
    def test_v19_access_denied_omission_preserves_audio_original_and_exact_replay(self):
        from normalize_source import normalize_payload
        from test_normalize_audio import audio, key, receipt
        from lms.lms.avo_transform import plan_import
        source = MISSING + '<p>Keep all authored material and <a href="https://example.test/file">File</a>.</p>'
        selected = binding(source); selected.update(lesson_id=5197, code=mod.ACCESS_DENIED_CODE)
        data = {'account':'mastervision','source_origin':'https://shop.mastervision.su',
                'course_id':520,'lesson_id':5197,'course_title':'Synthetic','lesson_title':'Synthetic',
                'format':'ape','ape':page(source)}
        data['ape']['children'].append(audio()); before = copy.deepcopy(data)
        with patch.object(mod, 'BINDINGS', [selected]):
            normalized, codes = normalize_payload(data, {key():receipt()})
            self.assertEqual(data, before)
            self.assertEqual(normalized['source_original_ape'], before['ape'])
            meta = normalized['source_normalization']
            self.assertEqual(meta['version'], 19)
            self.assertIn(mod.ACCESS_DENIED_CODE, codes)
            self.assertNotIn(mod.CODE, codes)
            self.assertEqual(meta['audio_assets'], {key():receipt()})
            omission = meta['missing_course_images'][0]
            self.assertEqual(omission['http_status'], 403)
            self.assertEqual(omission['reason'], 'owner_approved_access_denied')
            self.assertEqual(omission['code'], mod.ACCESS_DENIED_CODE)
            self.assertTrue(plan_import(normalized)['ready'])
            self.assertEqual(normalize_payload(normalized), (normalized, codes))
            for field, value in (('http_status',404), ('reason','confirmed_missing')):
                changed = copy.deepcopy(normalized)
                changed['source_normalization']['missing_course_images'][0][field] = value
                with self.assertRaisesRegex(Review,'normalization_metadata_conflict'):
                    normalize_payload(changed)

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

    def test_hash_bound_missing_image_with_exact_inert_legacy_style_is_omitted(self):
        tag=MISSING.replace('>', ' style="border:0px;vertical-align:middle;margin-top:0px;">')
        source='<p>Keep before '+tag+' and after.</p>'+LIVE
        selected=[binding(source,tag)]
        out,changes=self.clean(source,selected=selected)
        self.assertEqual(out['children'][0]['fields']['html'],source.replace(tag,''))
        self.assertEqual(changes[0]['images'],1)
        for css in ('display:none','border:0px;vertical-align:middle;margin-top:1px;',
                    'border:0px;vertical-align:middle;margin-top:0px;content:label'):
            changed=tag.replace('border:0px;vertical-align:middle;margin-top:0px;',css)
            with self.subTest(css=css),self.assertRaises(Review):
                self.clean(changed,selected=[binding(changed,changed)])
        with self.assertRaises(Review):self.clean(source+' changed',selected=selected)

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

    def test_public_bindings_separate_47_confirmed_404_and_one_owner_denied_image(self):
        missing = [item for item in mod.BINDINGS if item['course_id']==520 and item.get('code', mod.CODE) == mod.CODE]
        denied = [item for item in mod.BINDINGS if item.get('code') == mod.ACCESS_DENIED_CODE]
        self.assertEqual(len(missing), 26)
        self.assertEqual(sum(len(item['images']) for item in missing), 47)
        self.assertEqual(len(denied), 1)
        self.assertEqual((denied[0]['course_id'], denied[0]['lesson_id'], denied[0]['path']), (520, 5197, [2]))
        self.assertEqual(len(denied[0]['images']), 1)
        self.assertEqual(denied[0]['images'][0][0], '3662ecb5917de8b02aab745da6fd6173421ae2aaac3ef6ea9708feccb89e5dbd')
        self.assertTrue(all(item['kind'] == 'html' for item in mod.BINDINGS))
        self.assertNotIn(5176, {item['lesson_id'] for item in mod.BINDINGS})
        self.assertNotIn('https://', repr(mod.BINDINGS))

    def test_additional_confirmed_missing_images_have_exact_source_tag_and_result_bindings(self):
        added=[item for item in mod.BINDINGS if item['course_id']!=520 and item.get('code',mod.CODE)==mod.CODE]
        self.assertEqual({(x['course_id'],x['lesson_id'],tuple(x['path']))for x in added},
                         {(178,984,(0,)),(538,5605,(5,)),(184,1024,(0,)),(187,1037,(0,))})
        self.assertEqual(sum(len(x['images'])for x in added),6)
        for record in added:
            self.assertNotIn('code',record)
            for value in (record['source_sha256'],record['result_sha256'],
                          *[v for pair in record['images']for v in pair]):
                self.assertEqual(len(value),64)
                self.assertFalse(set(value)-set('0123456789abcdef'))

    def test_owner_approved_402_is_scoped_and_never_reported_as_missing404(self):
        tag=MISSING.replace('>', ' style=" width: 217.5px">')
        source=tag+'<p>Keep all teaching material.</p>'
        selected=binding(source,tag);selected.update(course_id=174,lesson_id=955,code=mod.UNAVAILABLE_CODE)
        tree=page(source);before=copy.deepcopy(tree)
        out,changes=self.clean(source,tree=tree,selected=[selected],cid=174,lid=955)
        self.assertEqual(tree,before)
        self.assertEqual(out['children'][0]['fields']['html'],'<p>Keep all teaching material.</p>')
        self.assertEqual(changes[0]['code'],mod.UNAVAILABLE_CODE)
        self.assertEqual(changes[0]['http_status'],402)
        self.assertEqual(changes[0]['reason'],'owner_approved_unavailable')
        for cid,lid in ((174,956),(175,955),(520,5171)):
            other=copy.deepcopy(selected);other.update(course_id=cid,lesson_id=lid)
            with self.subTest(cid=cid,lid=lid),self.assertRaises(Review):
                self.clean(source,selected=[other],cid=cid,lid=lid)
        for changeset in ({'code':mod.CODE},{'code':mod.ACCESS_DENIED_CODE},{'path':[1]}):
            changed=copy.deepcopy(selected);changed.update(changeset)
            with self.subTest(changeset=changeset),self.assertRaises(Review):
                self.clean(source,selected=[changed],cid=174,lid=955)
        changed=tag.replace('217.5px','218px')
        with self.assertRaises(Review):
            self.clean(changed,selected=[{**selected,**binding(changed,changed),'course_id':174,'lesson_id':955}],cid=174,lid=955)

    def test_402_integration_keeps_original_audio_and_exact_replay(self):
        import normalize_reviewed_getcourse as gc
        from normalize_source import normalize_payload
        from test_normalize_audio import audio,key,receipt
        source=MISSING+'<p>Keep lesson text.</p>'
        selected=binding(source);selected.update(course_id=174,lesson_id=955,code=mod.UNAVAILABLE_CODE)
        data={'account':'mastervision','source_origin':'https://shop.mastervision.su',
              'course_id':174,'lesson_id':955,'course_title':'Synthetic','lesson_title':'Synthetic',
              'format':'ape','ape':page(source)}
        data['ape']['children'].append(audio());before=copy.deepcopy(data)
        with patch.object(mod,'BINDINGS',[selected]),patch.object(gc,'BINDINGS',{}):
            q,codes=normalize_payload(data,{key():receipt()})
            self.assertEqual(data,before)
            self.assertEqual(q['source_original_ape'],data['ape'])
            self.assertIn(mod.UNAVAILABLE_CODE,codes);self.assertNotIn(mod.CODE,codes)
            self.assertEqual(q['source_normalization']['missing_course_images'][0]['http_status'],402)
            self.assertEqual(normalize_payload(q),(q,codes))
            changed=copy.deepcopy(q)
            changed['source_normalization']['missing_course_images'][0]['http_status']=404
            with self.assertRaisesRegex(Review,'normalization_metadata_conflict'):normalize_payload(changed)

    def test_public_402_binding_is_separate_from_all_missing_and_denied_records(self):
        selected=[x for x in mod.BINDINGS if x.get('code')==mod.UNAVAILABLE_CODE]
        self.assertEqual(len(selected),1)
        self.assertEqual((selected[0]['course_id'],selected[0]['lesson_id'],selected[0]['path']),(174,955,[0]))
        self.assertEqual(len(selected[0]['images']),8)

    def test_denied_metadata_only_for_exact_scope_and_changed_source_requires_review(self):
        selected = binding(MISSING); selected.update(lesson_id=5197, code=mod.ACCESS_DENIED_CODE)
        out, changes = self.clean(MISSING, selected=[selected], lid=5197)
        self.assertEqual(out['children'][0]['fields']['html'], '')
        self.assertEqual(changes[0]['code'], mod.ACCESS_DENIED_CODE)
        self.assertEqual(changes[0]['http_status'], 403)
        self.assertEqual(changes[0]['reason'], 'owner_approved_access_denied')
        with self.assertRaises(Review): self.clean(MISSING + 'changed', selected=[selected], lid=5197)
        for lid in (5171, 5198):
            changed = copy.deepcopy(selected); changed['lesson_id'] = lid
            with self.assertRaises(Review): self.clean(MISSING, selected=[changed], lid=lid)
        changed = copy.deepcopy(selected); changed['code'] = 'unknown_decision'
        with self.assertRaises(Review): self.clean(MISSING, selected=[changed], lid=5197)
        changed = copy.deepcopy(selected); changed.pop('code')
        with self.assertRaises(Review): self.clean(MISSING, selected=[changed], lid=5197)

    def test_old_missing_receipt_shape_has_no_denied_status_or_reason(self):
        _, changes = self.clean(MISSING)
        self.assertEqual(set(changes[0]), {'path','code','images','empty_image_wrappers',
                                          'source_sha256','result_sha256','url_sha256'})
        self.assertEqual(changes[0]['code'], mod.CODE)


if __name__ == '__main__': unittest.main()
