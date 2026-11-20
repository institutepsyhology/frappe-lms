import copy
import hashlib
import unittest
from unittest.mock import patch

import import_capture  # Configure the shared import paths.
import normalize_iomp_archive_html as material
from normalize_source import table_content


def record(markup, course='10', lesson='42', kind='text', **extra_fields):
    return {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
            'course_id': course, 'lesson_id': lesson, 'ape': {'name': 'page', 'children': [
                {'id': 'a', 'name': kind, 'fields': {'html': markup, 'anchor': '', **extra_fields}},
            ]}}


def sha(markup):
    return hashlib.sha256(markup.encode()).hexdigest()


class ArchiveHtmlTests(unittest.TestCase):
    def test_timing_table_retains_widths_cells_text_and_links(self):
        table = ('<table style="border:none" width="612"><colgroup><col width="85" /></colgroup>'
                 '<thead><tr><th style="vertical-align:top" scope="col">Время</th></tr></thead>'
                 '<tbody><tr><td><a href="https://example.org/lesson">00:15</a></td></tr></tbody></table>')
        result = material._table(table)
        material.make_html_block(result)
        self.assertEqual(table_content(table), table_content(result))
        self.assertIn('width:612px', result)
        self.assertIn('width:85px', result)
        self.assertIn('font-weight:bold', result)

    def test_only_confirmed_missing_illustration_is_omitted(self):
        intro, outro = '<p>Часть 1</p>', '<p><a href="https://example.org">Задание</a></p>'
        picture = ('<span style="border:none"><span style="display:inline-block"><span style="overflow:hidden">'
                   '<span style="width:400px"><span style="height:219px"><img src="https://example.org/404" />'
                   '</span></span></span></span></span>')
        raw = intro + picture + outro
        data = record(raw)
        with patch.object(material, 'MISSING_ILLUSTRATIONS', {sha(raw)}):
            material.normalize_iomp_archive_html(data)
            material.normalize_iomp_archive_html(data)
            changed = record(raw.replace('/404', '/new'))
            original = copy.deepcopy(changed)
            material.normalize_iomp_archive_html(changed)
        self.assertEqual(data['ape']['children'][0]['fields']['html'], intro + outro)
        self.assertEqual(changed, original)

    def test_course_heading_and_bounded_visibility(self):
        source = 'Вводное занятие <br>с Жанной Абрамовой'
        for cid, lid in [('294', '5638'), ('321', '5934')]:
            data = record(source, cid, lid, 'header-simple', level='h4')
            material.normalize_iomp_archive_html(data)
            node = data['ape']['children'][0]
            self.assertEqual((node['name'], node['fields']['html']), ('text', f'<h4>{source}</h4>'))
        for args in ({'visibleConditions': {'tag': 1}}, {'displayDelay': 2}, {'anchor': 'jump'}):
            data = record(source, '294', '5638', 'header-simple', level='h4', **args)
            original = copy.deepcopy(data)
            material.normalize_iomp_archive_html(data)
            self.assertEqual(data, original)

    def test_form_requires_exact_document_and_correct_source_account(self):
        url = 'https://docs.google.com/forms/d/e/test/viewform?embedded=true'
        form = f'<iframe src="{url}">Загрузка…</iframe>'
        with patch.object(material, 'GOOGLE_FORM', sha(form)):
            data = record(form, kind='code')
            material.normalize_iomp_archive_html(data)
            self.assertEqual(table_content(data['ape']['children'][0]['fields']['html'])[1], [url])
            for changed in [record(form.replace('Загрузка…', '<script>1</script>'), kind='code'),
                            dict(record(form, kind='code'), account='mastervision')]:
                before = copy.deepcopy(changed)
                material.normalize_iomp_archive_html(changed)
                self.assertEqual(changed, before)


if __name__ == '__main__':
    unittest.main()
