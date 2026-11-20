"""Preserve the diagnostic session description and link to its original IOMP checkout."""

from importer import Review
from lms.lms.avo_html_fragment import make_html_block
from normalize_reviewed_pairs import _digest


SOURCE = 'b08e6b33fff1cdfe88dfd8e64b9b0e5cf46d46064eeb7a9530eb3c61347b4f0c'
RESULT = '2bcd86196061892991bf3077cbbbca5cd21475ce388a328fca1c524c39ff20a5'
# The public form and checkout were both checked for the same product 1047.
CHECKOUT = 'https://shop.iomp.ru/?r=ordering%2Fcart%2Fas1&amp;id=1047&amp;clean=true&amp;lg=ru'
FORM = ('<p>Диагностическая сессия. Стоимость 990 рублей вместо <s>4990 рублей</s>.</p>'
        f'<p><a href="{CHECKOUT}">Записаться на диагностику</a></p>')


def normalize_diagnostic_session(payload):
    if (payload.get('account'), payload.get('source_origin'), str(payload.get('course_id')),
            str(payload.get('lesson_id')), payload.get('format')) != (
            'iomp', 'https://shop.iomp.ru', '246', '4462', 'ape'):
        return
    root = payload['ape']
    digest = _digest(root)
    if digest == RESULT:
        return
    if digest != SOURCE:
        raise Review('diagnostic_session_changed')

    def convert(parent):
        children = []
        for node in parent.get('children', []):
            kind, fields = node['name'], node.get('fields', {})
            if kind == 'icon':
                continue  # Decorative ticks without text, targets or links in the reviewed source.
            markup = None
            if kind == 'list-with-icons':
                markup = '<ul>' + ''.join(f"<li>{item['text']['html']}</li>" for item in fields['list']) + '</ul>'
            elif kind == 'header-simple':
                tag = fields['level']
                markup = f"<{tag}>{fields['html']}</{tag}>"
            elif kind == 'code':
                markup = FORM
            if markup:
                make_html_block(markup)
                node.update(name='text', fields={'html': markup})
            elif 'children' in node:
                convert(node)
            children.append(node)
        parent['children'] = children

    convert(root)
