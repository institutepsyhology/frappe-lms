"""Preserve the final display of the fixed June 2024 countdown in four IOMP lessons."""

from importer import Review
from normalize_reviewed_pairs import _digest


LESSONS = {('232', '4299'), ('233', '4093'), ('233', '4297'), ('233', '4298')}
TIMER = 'd61354bc2e28de763d4efe0ee227b411689b124cef8d5c9aeaad5fb426cb0180'
FINAL_TEXT = '00 ДНЕЙ 00 ЧАСОВ 00 МИНУТ 00 СЕКУНД'


def normalize_expired_countdown(payload):
    if ((payload.get('account'), payload.get('source_origin'), payload.get('format')) !=
            ('iomp', 'https://shop.iomp.ru', 'ape')
            or (str(payload.get('course_id')), str(payload.get('lesson_id'))) not in LESSONS):
        return
    children = payload['ape']['children']
    indices = [i for i, node in enumerate(children) if node['name'] == 'timer']
    if not indices:
        return
    if len(indices) != 1 or _digest(children[indices[0]]) != TIMER:
        raise Review('expired_countdown_changed')
    i = indices[0]
    children[i] = {'id': children[i]['id'], 'name': 'text',
                   'fields': {'html': f'<p style="text-align: center;">{FINAL_TEXT}</p>'}}
