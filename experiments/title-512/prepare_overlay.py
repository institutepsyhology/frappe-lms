"""Assemble only reviewed files into one Docker overlay layer."""
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
FILES=('lms/lms/avo_import.py','lms/lms/avo_transform.py','lms/lms/avo_html_fragment.py',
       'lms/lms/avo_title_schema.py','lms/lms/doctype/lms_course/lms_course.py',
       'lms/lms/doctype/lms_course/lms_course.json','lms/lms/doctype/course_lesson/course_lesson.json')


def main():
    target=ROOT/'overlay'
    target.mkdir(exist_ok=False)
    for name in FILES:
        src=ROOT/name
        if not src.is_file() or src.is_symlink():raise ValueError('invalid_source')
        dest=target/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dest)


if __name__=='__main__':main()
