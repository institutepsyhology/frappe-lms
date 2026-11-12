"""Apply only this release's changes to the verified deployed source."""
import hashlib
from pathlib import Path
import sys

ROOT=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/home/frappe/frappe-bench/apps/lms')
HASHES={'frontend/src/pages/Lesson.vue': '0f2095840da36dc9124560add1f34ebdf60d7cf6c793c30984798b3132e89835',
 'frontend/src/pages/LessonForm.vue': '07b702c23285f9136ba4214a736412e5342744ba3d78d7f23ff5fb4bc47d6ee3',
 'frontend/src/utils/index.js': '24b6254ec957f0cc6d7c3944a955da1ab7e1d06d7fb46517b5169f69a4f321fd'}
CHANGES={'frontend/src/pages/Lesson.vue': [('\t\t\t\t<CertificationLinks :courseName="courseName" />\n'
                                    '\t\t\t\t<router-link\n'
                                    '\t\t\t\t\tv-if="canEditLesson"\n'
                                    '\t\t\t\t\t:to="{\n'
                                    "\t\t\t\t\t\tname: 'CourseDetail',\n"
                                    '\t\t\t\t\t\tparams: { courseName: courseName },\n'
                                    "\t\t\t\t\t\thash: '#editor',\n",
                                    '\t\t\t\t<CertificationLinks :courseName="courseName" />\n'
                                    '\t\t\t\t<router-link\n'
                                    '\t\t\t\t\tv-if="canEditLesson"\n'
                                    '\t\t\t\t\t:to="avoCourseId && avoLessonId ? { name:\'AvoLessonEdit\', params:{ avoCourseId, '
                                    'avoLessonId } } : {\n'
                                    "\t\t\t\t\t\tname: 'CourseDetail',\n"
                                    '\t\t\t\t\t\tparams: { courseName: courseName },\n'
                                    "\t\t\t\t\t\thash: '#editor',\n")],
 'frontend/src/pages/LessonForm.vue': [('<template>\n'
                                        '\t<div class="py-6 sm:py-10">\n'
                                        '\t\t<div class="mx-0 space-y-6 px-4 sm:mx-10 sm:px-20">\n'
                                        '\t\t\t<nav class="flex gap-2 border-b border-outline-gray-2" aria-label="Разделы урока">\n'
                                        '\t\t\t\t<button type="button" class="px-4 py-3 font-medium" :class="lessonSection === \'content\' '
                                        '? \'border-b-2 border-ink-gray-9\' : \'text-ink-gray-5\'" :aria-current="lessonSection === '
                                        '\'content\' ? \'page\' : undefined" @click="lessonSection = \'content\'">Содержание '
                                        'урока</button>\n',
                                        '<template>\n'
                                        '\t<div v-if="props.avoCourseId && props.avoLessonId && !lessonDetails.data?.lesson" class="p-8" '
                                        'role="status">Загрузка урока для редактирования… Если урок недоступен, обновите страницу.</div>\n'
                                        '\t<div v-else class="py-6 sm:py-10">\n'
                                        '\t\t<div class="mx-0 space-y-6 px-4 sm:mx-10 sm:px-20">\n'
                                        '\t\t\t<nav class="flex gap-2 border-b border-outline-gray-2" aria-label="Разделы урока">\n'
                                        '\t\t\t\t<button type="button" class="px-4 py-3 font-medium" :class="lessonSection === \'content\' '
                                        '? \'border-b-2 border-ink-gray-9\' : \'text-ink-gray-5\'" :aria-current="lessonSection === '
                                        '\'content\' ? \'page\' : undefined" @click="lessonSection = \'content\'">Содержание '
                                        'урока</button>\n'),
                                       ('\t\ttype: String,\n\t\trequired: true,\n\t},\n})\n\nconst isDirty = ref(false)\n',
                                        '\t\ttype: String,\n'
                                        '\t\trequired: true,\n'
                                        '\t},\n'
                                        "\tavoCourseId: { type: String, default: '' },\n"
                                        "\tavoLessonId: { type: String, default: '' },\n"
                                        '})\n'
                                        '\n'
                                        'const isDirty = ref(false)\n'),
                                       ('const lessonHasVideo = computed(() => hasVideoContent(lesson))\n'
                                        '\n'
                                        'const lessonDetails = createResource({\n'
                                        "\turl: 'lms.lms.utils.get_lesson_creation_details',\n"
                                        '\tparams: {\n'
                                        '\t\tcourse: props.courseName,\n'
                                        '\t\tchapter: props.chapterNumber,\n'
                                        '\t\tlesson: props.lessonNumber,\n',
                                        'const lessonHasVideo = computed(() => hasVideoContent(lesson))\n'
                                        '\n'
                                        'const lessonDetails = createResource({\n'
                                        "\turl: props.avoCourseId && props.avoLessonId ? 'lms.lms.avo_course_routes.get_editor_by_source' "
                                        ": 'lms.lms.utils.get_lesson_creation_details',\n"
                                        '\tparams: props.avoCourseId && props.avoLessonId ? { course_id:props.avoCourseId, '
                                        'lesson_id:props.avoLessonId } : {\n'
                                        '\t\tcourse: props.courseName,\n'
                                        '\t\tchapter: props.chapterNumber,\n'
                                        '\t\tlesson: props.lessonNumber,\n'),
                                       ('\t\t\tcontentUploadContext.docname = data.lesson.name\n'
                                        '\t\t\tinstructorUploadContext.docname = data.lesson.name\n'
                                        '\t\t\tnextTick(autoGrowTitle)\n'
                                        '\t\t\tPromise.all([addLessonContent(data), addInstructorNotes(data)]).then(\n'
                                        '\t\t\t\t() => {\n'
                                        '\t\t\t\t\tnextTick(() => {\n'
                                        "\t\t\t\t\t\t// Loaded content isn't user input; arm autosave after render.\n",
                                        '\t\t\tcontentUploadContext.docname = data.lesson.name\n'
                                        '\t\t\tinstructorUploadContext.docname = data.lesson.name\n'
                                        '\t\t\tnextTick(autoGrowTitle)\n'
                                        '\t\t\tnextTick(() => Promise.all([addLessonContent(data), addInstructorNotes(data)]).then(\n'
                                        '\t\t\t\t() => {\n'
                                        '\t\t\t\t\tnextTick(() => {\n'
                                        "\t\t\t\t\t\t// Loaded content isn't user input; arm autosave after render.\n"),
                                       ('\t\t\t\t\t\t}\n\t\t\t\t\t})\n\t\t\t\t}\n\t\t\t)\n\t\t}\n\t},\n})\n',
                                        '\t\t\t\t\t\t}\n\t\t\t\t\t})\n\t\t\t\t}\n\t\t\t))\n\t\t}\n\t},\n})\n'),
                                       ('})\n'
                                        '\n'
                                        'const editLesson = createResource({\n'
                                        "\turl: 'frappe.client.set_value',\n"
                                        '\tmakeParams(values) {\n'
                                        '\t\treturn {\n'
                                        "\t\t\tdoctype: 'Course Lesson',\n"
                                        '\t\t\tname: values.lesson,\n',
                                        '})\n'
                                        '\n'
                                        'const editLesson = createResource({\n'
                                        "\turl: props.avoCourseId && props.avoLessonId ? 'lms.lms.avo_course_routes.save_editor_by_source' "
                                        ": 'frappe.client.set_value',\n"
                                        '\tmakeParams(values) {\n'
                                        '\t\tif (props.avoCourseId && props.avoLessonId) {\n'
                                        '\t\t\tconst '
                                        "fields=['title','include_in_preview','body','content','instructor_notes','instructor_content']\n"
                                        '\t\t\treturn { course_id:props.avoCourseId, lesson_id:props.avoLessonId, '
                                        'expected_name:values.lesson,\n'
                                        '\t\t\t\tvalues:Object.fromEntries(fields.map(field => [field, lesson[field] ?? (field === '
                                        "'include_in_preview' ? false : null)])) }\n"
                                        '\t\t}\n'
                                        '\t\treturn {\n'
                                        "\t\t\tdoctype: 'Course Lesson',\n"
                                        '\t\t\tname: values.lesson,\n'),
                                       ('}\n'
                                        '\n'
                                        'function persistLesson(bodyData, notesData, flush) {\n'
                                        '\tconst bodyHasContent = foldEditorData(bodyData, notesData)\n'
                                        '\n'
                                        '\t// Nothing to save: no title, no body.\n',
                                        '}\n'
                                        '\n'
                                        'function persistLesson(bodyData, notesData, flush) {\n'
                                        '\tif (props.avoCourseId && props.avoLessonId && !lessonDetails.data?.lesson) return\n'
                                        '\tconst bodyHasContent = foldEditorData(bodyData, notesData)\n'
                                        '\n'
                                        '\t// Nothing to save: no title, no body.\n'),
                                       ('\t\t\t// The daily untitled-lesson rename can move the docname under an open\n'
                                        '\t\t\t// editor; re-resolve it by index and retry once (a plain reload would\n'
                                        "\t\t\t// drop the unsaved edits we're saving).\n"
                                        "\t\t\tif (!isRetry && err?.exc_type === 'DoesNotExistError') {\n"
                                        '\t\t\t\tresolveLessonName().then((name) => {\n'
                                        '\t\t\t\t\tif (name) editCurrentLesson(true)\n'
                                        '\t\t\t\t\telse toast.error(err.messages?.[0] || err.message || err)\n',
                                        '\t\t\t// The daily untitled-lesson rename can move the docname under an open\n'
                                        '\t\t\t// editor; re-resolve it by index and retry once (a plain reload would\n'
                                        "\t\t\t// drop the unsaved edits we're saving).\n"
                                        "\t\t\tif (!props.avoCourseId && !isRetry && err?.exc_type === 'DoesNotExistError') {\n"
                                        '\t\t\t\tresolveLessonName().then((name) => {\n'
                                        '\t\t\t\t\tif (name) editCurrentLesson(true)\n'
                                        '\t\t\t\t\telse toast.error(err.messages?.[0] || err.message || err)\n')],
 'frontend/src/utils/index.js': [("\t\t\t\t\tlabel: 'Courses',\n"
                                  "\t\t\t\t\ticon: 'BookOpen',\n"
                                  "\t\t\t\t\tto: 'Courses',\n"
                                  "\t\t\t\t\tactiveFor: ['Courses', 'CourseDetail', 'Lesson', 'AvoCourse', 'AvoLesson'],\n"
                                  '\t\t\t\t},\n'
                                  '\t\t\t\t{\n'
                                  "\t\t\t\t\tlabel: 'Programs',\n",
                                  "\t\t\t\t\tlabel: 'Courses',\n"
                                  "\t\t\t\t\ticon: 'BookOpen',\n"
                                  "\t\t\t\t\tto: 'Courses',\n"
                                  "\t\t\t\t\tactiveFor: ['Courses', 'CourseDetail', 'Lesson', 'AvoCourse', 'AvoLesson', 'AvoLessonEdit'],\n"
                                  '\t\t\t\t},\n'
                                  '\t\t\t\t{\n'
                                  "\t\t\t\t\tlabel: 'Programs',\n")]}

def main():
    staged={}
    for name,expected in HASHES.items():
        path=ROOT/name;data=path.read_bytes().replace(b"\r\n",b"\n")
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('deployed_source_changed:'+name)
        text=data.decode('utf-8')
        for old,new in CHANGES[name]:
            if text.count(old)!=1:raise ValueError('delta_context_changed:'+name)
            text=text.replace(old,new,1)
        staged[path]=text
    for path,text in staged.items():path.write_text(text,encoding='utf-8',newline='\n')
    print('verified_live_delta_applied')

if __name__=='__main__':main()
