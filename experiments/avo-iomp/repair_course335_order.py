"""Restore the first three references of the closed IOMP course 335.

The default command only previews. --apply appends the two missing drafts
and moves the existing 6311 reference. The usual importer handles the rest.
"""

import argparse
from contextlib import closing
import json

from import_capture import (
    ARCHIVE, WORKSPACE, IompClient, IompImporter, Review, Stop, diagnostic,
    lesson_images, preflight_source, read_capture,
)


COURSE = '335'
ORIGINAL = '6311'
SOURCE_PREFIX = ['6348', '6309', ORIGINAL]
TEMPORARY = [ORIGINAL, '6348', '6309']
MOVE = 'lms.lms.api.update_lesson_index'


def inspect_order(importer, source_order):
    outline = importer.outline(COURSE)
    ids = outline['ids']
    if ORIGINAL not in ids or not outline['course']:
        raise Review('course335_original_missing')
    if len(ids) >= len(SOURCE_PREFIX) and ids == source_order[:len(ids)]:
        return outline, True
    if ids != TEMPORARY[:len(ids)]:
        raise Review('course335_unexpected_order')
    return outline, False


def repair(importer, payloads, apply=False):
    source_order = [p['lesson_id'] for p in payloads]
    if (source_order[:3] != SOURCE_PREFIX or len(set(source_order)) != len(source_order)
            or any(p['course_id'] != COURSE or p['account'] != 'iomp' for p in payloads)):
        raise Review('course335_source_changed')
    outline, complete = inspect_order(importer, source_order)
    original = outline['by_id'][ORIGINAL]
    chapter, name = original['chapter'], original['name']
    by_id = {p['lesson_id']: p for p in payloads[:3]}
    staged = [by_id[lid] for lid in TEMPORARY]
    images = {p['lesson_id']: lesson_images(p) for p in staged}

    def preview_original():
        result, _ = importer.preview(by_id[ORIGINAL], images[ORIGINAL])
        if result['action'] != 'already_imported':
            raise Review('course335_original_changed')

    if complete:
        preview_original()
        return {'status': 'already_ordered', 'course_id': COURSE, 'existing': len(outline['ids'])}
    # The importer's ordinary dry run compares the stored source and student
    # content of every existing draft to its payload before the first write.
    report = importer.import_course(staged, apply=apply, images_for_lesson=lambda p: images[p['lesson_id']])
    if not apply:
        return {'status': 'ready', 'course_id': COURSE, 'existing_ids': outline['ids'],
                'proposed_first_ids': SOURCE_PREFIX}
    before, already_moved = inspect_order(importer, source_order)
    if before['by_id'][ORIGINAL] != original or before['course'] != outline['course']:
        raise Stop('course335_original_changed')
    if not already_moved:
        if before['ids'] != TEMPORARY:
            raise Stop('course335_unexpected_order')
        args = {'lesson': name, 'sourceChapter': chapter, 'targetChapter': chapter, 'idx': 2}
        # This is the LMS course editor's own same-chapter drag-and-drop call.
        # If the response is lost, the next run reads the current order first.
        result = importer.client.rpc('tools/call', {'name': 'call_method',
            'arguments': {'method': MOVE, 'args': args}})
        if result.get('isError'):
            raise Stop('course335_move_uncertain')
    after, complete = inspect_order(importer, source_order)
    if not complete or after['by_id'][ORIGINAL] != original or after['course'] != outline['course']:
        raise Stop('course335_move_uncertain')
    preview_original()
    return {'status': 'ordered', 'course_id': COURSE, 'first_ids': after['ids'][:3],
            'created_ids': report['created_lesson_ids']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        receipts = sorted((ARCHIVE / 'course-335').glob('*/capture-status.json'))
        if not receipts:
            raise Review('course335_capture_missing')
        _, _, payloads = read_capture(receipts[-1].parent)
        preflight_source(payloads)
        with closing(IompClient(WORKSPACE)) as client:
            result = repair(IompImporter(client), payloads, apply=args.apply)
    except Exception as error:
        print(json.dumps({'status': 'stopped', 'course_id': COURSE, 'code': diagnostic(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
