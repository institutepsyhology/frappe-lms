"""Apply the URL changes to the verified deployed versions of three files.

The repository contains other changes not yet installed in the running image.
Keep those changes out of this release rather than silently deploying them.
"""
import hashlib
from pathlib import Path
import sys

ROOT=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/home/frappe/frappe-bench/apps/lms')
HASHES={
    'frontend/src/components/ChapterRow.vue':'fe1d2345a220bdc804ade36babc5f5f066ec0c5374143009d23bf331a8eda8cb',
    'frontend/src/pages/Lesson.vue':'a0f1b2578c9fd97e0e0b38dd809a5e93eae84b771757a144c846d9f6ff765cbe',
    'frontend/src/utils/index.js':'a2a74d15acea09bc00202b54a060af464b27e37d2e1755daf99b2e82521ff0b1',
}
CHANGES={
    'frontend/src/components/ChapterRow.vue':[(
        'if (props.inlineSelect) return props.selectedLessonNumber === lessonNumber',
        'if (props.selectedLessonNumber || props.inlineSelect) return props.selectedLessonNumber === lessonNumber')],
    'frontend/src/pages/Lesson.vue':[(
        "\tlessonNumber: {\n\t\ttype: String,\n\t\trequired: true,\n\t},\n",
        "\tlessonNumber: {\n\t\ttype: String,\n\t\trequired: true,\n\t},\n\tavoCourseId: { type: String, default: '' },\n\tavoLessonId: { type: String, default: '' },\n"),(
        "const lesson = createResource({\n\turl: 'lms.lms.utils.get_lesson',\n\tmakeParams(values) {\n",
        "const lesson = createResource({\n\turl: props.avoCourseId && props.avoLessonId ? 'lms.lms.avo_course_routes.get_lesson_by_source' : 'lms.lms.utils.get_lesson',\n\tmakeParams(values) {\n\t\tif (props.avoCourseId && props.avoLessonId) return { course_id:props.avoCourseId, lesson_id:props.avoLessonId }\n")],
    'frontend/src/utils/index.js':[(
        "activeFor: ['Courses', 'CourseDetail', 'Lesson']",
        "activeFor: ['Courses', 'CourseDetail', 'Lesson', 'AvoCourse', 'AvoLesson']")],
}

def main():
    staged={}
    for name,expected in HASHES.items():
        path=ROOT/name;data=path.read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('deployed_source_changed:'+name)
        text=data.decode('utf-8')
        for old,new in CHANGES[name]:
            if text.count(old)!=1:raise ValueError('delta_context_changed:'+name)
            text=text.replace(old,new,1)
        staged[path]=text
    for path,text in staged.items():path.write_text(text,encoding='utf-8',newline='\n')
    print('verified_live_delta_applied')

if __name__=='__main__':main()
