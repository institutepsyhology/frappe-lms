"""Parse course/lesson HTML from the isolated IOMP collector's private pipe."""

import json
from pathlib import Path
import re
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mastervision-migration'))
from source import Config, Review, parse_catalog, parse_course, parse_lesson


CONFIG = Config('iomp', 'https://shop.iomp.ru')


def editor_settings(rows, prefix):
    return [row for row in rows if (row['attrs'].get('name') or '').startswith(prefix)
            and row['attrs'].get('type') != 'password']


def main():
    request = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    if request['kind'] == 'catalog':
        result = parse_catalog(request['html'], request['page'], config=CONFIG)
    elif request['kind'] == 'course':
        result = parse_course(request['html'], request['course_id'], config=CONFIG)
        result['settings'] = editor_settings(result['settings'], 'TrainingForm[')
    elif request['kind'] == 'lesson':
        result = parse_lesson(request['html'], request['course_id'], request['lesson_id'],
                              request['course_title'], request['lesson_title'], config=CONFIG)
        result['settings'] = editor_settings(result['settings'], 'TrainingLessons[')
    else:
        raise Review('unknown_editor_kind')
    print(json.dumps({'result': result}, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except Review as error:
        code = str(error)
        print(json.dumps({'error': code if re.fullmatch('[a-z_]{1,100}', code) else 'source_review'}))
    except Exception:
        print(json.dumps({'error': 'source_parse_failed'}))
