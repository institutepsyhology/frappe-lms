"""Owner-reviewed material decisions for IOMP course 193."""

from importer import Review
from normalize_reviewed_pairs import _digest, _heading


QUESTIONNAIRE_BUTTON = '2368fda55ce24fcfdad0e562fa9c620baf52af5dca5e96301a5429e7bb417bc7'


def _matches(payload, lesson):
    return (payload.get('account'), payload.get('source_origin'), str(payload.get('course_id')),
            str(payload.get('lesson_id'))) == ('iomp', 'https://shop.iomp.ru', '193', lesson)


def awaiting_presentation_decision(payload):
    """Keep 3260 on hold even if a later converter accepts the duplicate links."""
    return _matches(payload, '3260')


def omit_questionnaire_button(payload):
    if not _matches(payload, '3280') or payload.get('format') != 'ape':
        return
    children = payload['ape']['children']
    matches = [node for node in children
               if node['name'] == 'button' and _heading(node).casefold() == 'анкета']
    if not matches:
        return
    if len(matches) != 1 or _digest(matches[0]) != QUESTIONNAIRE_BUTTON:
        raise Review('questionnaire_button_changed')
    children.remove(matches[0])
