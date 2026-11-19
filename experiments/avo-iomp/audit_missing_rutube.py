"""Find explicit IOMP player pairs for YouTube-only blocks in current source captures."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from import_capture import ACCOUNT, ARCHIVE, EXCLUDED_LESSONS, ORIGIN, plan_import, refreshed_lessons
from lms.lms.avo_transform import _legacy_player_pairs, _player_url


@dataclass(frozen=True, order=True)
class Place:
    course: int
    lesson: int
    video: int

    def label(self):
        return f'{self.course}/{self.lesson} №{self.video}'


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def snapshots(archive, counts, skipped):
    folders = sorted(archive.glob('course-*'), key=lambda p: int(p.name.split('-')[1]))
    selected = []
    for folder in folders:
        course = int(folder.name.split('-')[1])
        for receipt in sorted(folder.glob('*/capture-status.json'), reverse=True):
            status = _json(receipt)
            ids = status.get('lesson_ids')
            if (status.get('account') == ACCOUNT and status.get('course_id') == course
                    and status.get('outline_verified') is True and status.get('issues') == []
                    and isinstance(ids, list) and status.get('saved') == ids
                    and all(type(i) is int and i > 0 for i in ids) and len(ids) == len(set(ids))):
                break
        else:
            skipped.append(f'{course} (нет полного снимка)')
            continue
        meta = _json(receipt.parent / 'course.json')
        if (meta['course_id'], meta['lesson_ids']) != (course, ids):
            raise ValueError(f'Несовпадение состава курса {course}')
        updates = refreshed_lessons(receipt.parent, course, ids)
        counts['courses'] += 1
        for lesson in ids:
            if str(lesson) in EXCLUDED_LESSONS:
                counts['excluded'] += 1
                continue
            path = updates.get(str(lesson), receipt.parent / f'lesson-{lesson}.json')
            selected.append((course, lesson, meta['title'], path))
            counts['refreshed'] += str(lesson) in updates
    # Resolve all full/partial source files before reading individual lessons.
    # Subsequent captures in the background cannot change the resulting set.
    for course, lesson, title, path in selected:
        payload = _json(path)['payload']
        if (payload['account'], payload['source_origin'], str(payload['course_id']),
                str(payload['lesson_id']), payload['course_title']) != (
                ACCOUNT, ORIGIN, str(course), str(lesson), title):
            raise ValueError(f'Несовпадение источника {course}/{lesson}')
        counts['lessons'] += 1
        yield course, lesson, payload


def source_videos(payload):
    if payload['format'] != 'ape':
        for block in plan_import(payload, {})['blocks']:
            if block['type'] == 'videoChoice':
                yield block['data']
        return
    root = payload['ape']
    nodes, stack = [], [root]
    while stack:
        node = stack.pop()
        if node.get('name') == 'video':
            nodes.append(node)
        else:
            stack.extend(reversed(node.get('children', [])))
    # A legacy pair always contains a first-provider RuTube video node.
    legacy, skip = {}, set()
    if any(n['fields'].get('videoProvider') == 'rutube' for n in nodes):
        legacy, skip, _ = _legacy_player_pairs(root)
    for node in nodes:
        if id(node) in skip:
            continue
        fields = node['fields']
        primary = fields.get('videoProvider'), fields.get('videoSrc')
        other = fields.get('videoProvider2'), fields.get('videoSrc2')
        if id(node) in legacy:
            linked = legacy[id(node)]
            other = linked['videoProvider'], linked['videoSrc']
        if (primary[0] not in ('youtube', 'rutube') or not _player_url(primary[1], primary[0])
                or other[0] not in (None, '', 'youtube', 'rutube')):
            continue
        media = {'youtube': '', 'rutube': '', primary[0]: primary[1]}
        if other[1] and other != primary:
            if (other[0] not in ('youtube', 'rutube') or primary[0] == other[0]
                    or not _player_url(other[1], other[0])):
                continue
            media[other[0]] = other[1]
        yield media


def index_videos(records, counts):
    singles = defaultdict(list)
    donors = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for course, lesson, payload in records:
        for number, video in enumerate(source_videos(payload), 1):
            counts['videos'] += 1
            if not video['youtube']:
                continue
            url = urlsplit(video['youtube'])
            youtube = parse_qs(url.query)['v'][0] if url.path == '/watch' else url.path.rstrip('/').split('/')[-1]
            place = Place(course, lesson, number)
            if video['rutube']:
                alternate = urlsplit(video['rutube'])
                rutube = alternate.path.rstrip('/').split('/')[-1].lower()
                # The same recording with distinct access parameters needs a separate
                # link check. Never output the parameters or store them in the report.
                access = tuple(parse_qs(alternate.query).get('p', []))
                donors[youtube][rutube][access].append(place)
                counts['pairs'] += 1
            else:
                singles[youtube].append(place)
                counts['single'] += 1
    return singles, donors


def group_matches(singles, donors):
    # One representative donor per access variant. Prefer another lesson when possible.
    lessons = defaultdict(list)
    stats = Counter()
    for youtube, places in singles.items():
        options = donors.get(youtube)
        if not options:
            stats['no_donor'] += len(places)
            continue
        conflict = len(options) > 1
        access_conflict = any(len(versions) > 1 for versions in options.values())
        for place in places:
            examples = []
            for versions in options.values():
                for authors in versions.values():
                    first = min(authors, key=lambda p: (p.lesson == place.lesson, p))
                    examples.append((first, len(authors)))
            status = 'разные ролики' if conflict else ('варианты доступа' if access_conflict else 'одна пара')
            lessons[(place.course, place.lesson)].append((place.video, status, sorted(examples)))
            stats[status] += 1
    return lessons, stats


def report(archive):
    counts, skipped = Counter(), []
    started = datetime.now(timezone.utc)
    singles, donors = index_videos(snapshots(archive, counts, skipped), counts)
    lessons, stats = group_matches(singles, donors)
    output = [
        '# ИОМП · недостающие альтернативы RuTube',
        '',
        f"Перечень снимков зафиксирован {started:%d.%m.%Y в %H:%M} UTC. "
        f"В локальном архиве {counts['courses']} полных снимков курсов. "
        f"Проверено уроков — {counts['lessons']}, из них по обновлённому снимку — {counts['refreshed']}. "
        f"Исключено по списку владельца — {counts['excluded']}.",
        '',
        f"Распознано видеоблоков — {counts['videos']}, из них с явно заданной парой YouTube и RuTube — {counts['pairs']}. "
        f"У {counts['single']} блоков есть только YouTube. Для {stats['одна пара']} найдена однозначная альтернатива, "
        f"для {stats['разные ролики']} найдены разные записи, для {stats['варианты доступа']} — варианты доступа "
        f"к одной записи. Для {stats['no_donor']} точной пары в проверенном архиве не найдено.",
        '',
        f"Совпадения затрагивают {len(lessons)} уроков в {len({course for course, _ in lessons})} курсах. "
        'Таблица показывает исходные уроки АВО до обработки для переноса. Совпадения установлены по точному '
        'YouTube ID. Учитывались пары в одном видеоблоке и пары, распознанные по подписям основного и '
        'альтернативного плеера. Доступность воспроизведения в этом отчёте не оценивалась.',
        '',
        'Номер видео считается с единицы среди распознанных блоков выбора плеера в уроке. '
        'Для каждого совпадения приведён один источник в формате «курс/урок № видео». '
        'Число в скобках показывает, в скольких блоках архива есть эта пара.',
        '',
        '| Курс/урок | Видео → источник RuTube |',
        '| --- | --- |',
    ]
    for (course, lesson), items in sorted(lessons.items()):
        entries = []
        for video, status, examples in sorted(items):
            prefix = '' if status == 'одна пара' else f'**{status}** · '
            sample = ', '.join(f'{p.label()} ({total})' for p, total in examples)
            entries.append(f'№{video} → {prefix}{sample}')
        output.append(f"| {course}/{lesson} | {'<br>'.join(entries)} |")
    if skipped:
        output.extend(['', 'Пропущены курсы без подходящего снимка — ' + ', '.join(skipped) + '.'])
    return '\n'.join(output) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(report(ARCHIVE), encoding='utf-8')
