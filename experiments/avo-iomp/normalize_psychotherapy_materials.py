"""Owner-reviewed material decisions for IOMP course 193."""

from importer import Review
from normalize_reviewed_pairs import _digest, _heading


QUESTIONNAIRE_BUTTON = '2368fda55ce24fcfdad0e562fa9c620baf52af5dca5e96301a5429e7bb417bc7'


def _matches(payload, lesson):
    return (payload.get('account'), payload.get('source_origin'), str(payload.get('course_id')),
            str(payload.get('lesson_id'))) == ('iomp', 'https://shop.iomp.ru', '193', lesson)


def omit_supervision_presentation(payload):
    """Use the reviewed audio link for either archived layout of lesson 3260."""
    if not _matches(payload, '3260') or payload.get('format') != 'ape':
        return
    children = payload['ape']['children']
    if not children:
        raise Review('supervision_materials_changed')
    section = children[-1]
    fingerprint = _digest(section)
    if fingerprint in {
        '80d0c12d979c1396459899ccd5b50c142b2261e4b085be4b2f5e1f7e85df4f5c',
        '161f48ff5d5caf09ac93f009ab361db866ae5d04272ce2dcde2dcef6d6f88771',
    }:
        return
    if fingerprint == '418a4c2b01966fcfbfacb2289e32fe8002a85125125028ddf66a43fddf1d8dbe':
        section['children'].pop(0)
    elif fingerprint != 'e8cc0104077517e674f9fda29a3b4a0be99dba1444e54546f43551af3bb0c660':
        raise Review('supervision_materials_changed')
    audio = section['children'][0]['children'][0]
    audio['fields']['html'] = _heading(audio)


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
