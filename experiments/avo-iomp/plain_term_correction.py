"""Apply the approved plain-text correction to the seven existing IOMP drafts."""

import argparse
import base64
import copy
import hashlib
import json
from contextlib import closing

from import_capture import ARCHIVE, WORKSPACE, IompClient, IompImporter, Stop, mutate, read_capture
from lms.lms.avo_html_fragment import make_html_block
from normalize_iomp_course_material import PSYCHOSOMATOSIS_TEXT_DIGEST


LESSONS = {163: 2683, 208: 3526, 211: 3604, 229: 4017, 267: 4911, 268: 4980, 331: 6102}
TERM = '&laquo;психосоматоз&raquo;'


def versions(course, lesson):
    receipt = sorted((ARCHIVE / f'course-{course}').glob('*/capture-status.json'))[-1]
    _, _, lessons = read_capture(receipt.parent)
    current = next(l for l in lessons if l['lesson_id'] == str(lesson))
    previous = copy.deepcopy(current)
    nodes = [previous['ape']]
    changes = []
    while nodes:
        node = nodes.pop()
        nodes.extend(node.get('children', []))
        fields = node.get('fields', {})
        html = fields.get('html', '')
        if node.get('name') != 'text' or not isinstance(html, str) or html.count(TERM) != 1:
            continue
        authored = html.replace(TERM, f'<code>{TERM}</code>')
        if hashlib.sha256(authored.encode()).hexdigest() != PSYCHOSOMATOSIS_TEXT_DIGEST:
            continue
        fields['html'] = html.replace(TERM, f'<span style="font-family:monospace">{TERM}</span>')
        changes.append((make_html_block(fields['html']), make_html_block(html)))
    if len(changes) != 1:
        raise Stop('plain_term_source_changed')
    return previous, current, changes[0]


def attach_source(client, name, payload):
    # These lessons have no imported image files. Use the importer's canonical
    # fingerprint and snapshot formats, so its normal read-back verifies both.
    envelope = {'payload': payload, 'image_hashes': {}}
    canonical = json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)
    filename = 'avo-source-sha256-' + hashlib.sha256(canonical.encode()).hexdigest() + '.json'
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    filters = {'attached_to_doctype': 'Course Lesson', 'attached_to_name': name, 'file_name': filename, 'is_private': 1}
    fields = ['name', 'file_url', 'file_size', 'content_hash']
    args = {'doctype': 'File', 'fields': fields, 'filters': filters, 'limit': 2}
    if not client.call('list_documents', args)['documents']:
        mutate(client, 'create_document', {'doctype': 'File', 'data': {
            **filters, 'content': base64.b64encode(raw).decode('ascii'), 'decode': 1}})
    files = client.call('list_documents', args)['documents']
    if (len(files) != 1 or not files[0]['file_url'].startswith('/private/files/')
            or files[0]['file_size'] != len(raw) or files[0]['content_hash'] != hashlib.md5(raw).hexdigest()):
        raise Stop('plain_term_snapshot_mismatch')


def correct(importer, course, lesson, apply):
    old, new, (old_block, new_block) = versions(course, lesson)
    name = importer.outline(str(course))['by_id'][str(lesson)]['name']
    args = {'doctype': 'Course Lesson', 'name': name}
    before = importer.client.call('get_document', args)
    content = json.loads(before['content'])
    blocks = content['blocks']
    if blocks.count(new_block) == 1 and old_block not in blocks:
        if importer.preview(new, {})[0]['action'] != 'already_imported':
            raise Stop('plain_term_new_snapshot_mismatch')
        return 'verified'
    if (blocks.count(old_block) != 1 or new_block in blocks
            or importer.preview(old, {})[0]['action'] != 'already_imported'):
        raise Stop('plain_term_original_mismatch')
    if not apply:
        return 'ready'
    blocks[blocks.index(old_block)] = new_block
    attach_source(importer.client, name, new)
    latest = importer.client.call('get_document', args)
    if latest['content'] != before['content'] or latest['modified'] != before['modified']:
        raise Stop('plain_term_concurrent_edit')
    mutate(importer.client, 'update_document', {**args, 'data': {
        'modified': before['modified'], 'content': json.dumps(content, ensure_ascii=False)}})
    after = importer.client.call('get_document', args)
    if json.loads(after['content']) != content or importer.preview(new, {})[0]['action'] != 'already_imported':
        raise Stop('plain_term_readback_mismatch')
    return 'verified'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    with closing(IompClient(WORKSPACE)) as client:
        options = parser.parse_args()
        importer = IompImporter(client)
        for cid, lid in LESSONS.items():
            print(cid, lid, correct(importer, cid, lid, options.apply), flush=True)
