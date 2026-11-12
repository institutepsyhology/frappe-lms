"""Apply only the legacy URL changes to the verified deployed lesson source."""
import hashlib
from pathlib import Path
import sys
ROOT=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/home/frappe/frappe-bench/apps/lms')
HASHES={'frontend/src/pages/Lesson.vue': '8d062d2ac6d6a22fd18222807a763826facde8cb8481b297aa062e566e1033bc'}
CHANGES={'frontend/src/pages/Lesson.vue': [('\t\t\t\t<CertificationLinks :courseName="courseName" />\n'
                                    '\t\t\t\t<router-link\n'
                                    '\t\t\t\t\tv-if="canEditLesson"\n'
                                    '\t\t\t\t\t:to="avoCourseId && avoLessonId ? { name:\'AvoLessonEdit\', params:{ '
                                    'avoCourseId, avoLessonId } } : {\n'
                                    "\t\t\t\t\t\tname: 'CourseDetail',\n"
                                    '\t\t\t\t\t\tparams: { courseName: courseName },\n'
                                    "\t\t\t\t\t\thash: '#editor',\n",
                                    '\t\t\t\t<CertificationLinks :courseName="courseName" />\n'
                                    '\t\t\t\t<router-link\n'
                                    '\t\t\t\t\tv-if="canEditLesson"\n'
                                    '\t\t\t\t\t:to="avoCourseId && avoLessonId ? { name:\'AvoLessonEdit\', query:{ '
                                    "id:avoLessonId, lg:'ru' } } : {\n"
                                    "\t\t\t\t\t\tname: 'CourseDetail',\n"
                                    '\t\t\t\t\t\tparams: { courseName: courseName },\n'
                                    "\t\t\t\t\t\thash: '#editor',\n"),
                                   ("import Notes from '@/components/Notes/Notes.vue'\n"
                                    "import InlineLessonMenu from '@/components/Notes/InlineLessonMenu.vue'\n"
                                    "import { parseStoredEditorJs } from '@/utils/lessonForm'\n"
                                    "import { getLmsRoute } from '@/utils/basePath'\n"
                                    "import { provideStudentView } from '@/composables/useStudentView'\n"
                                    '\n'
                                    'const router = useRouter()\n',
                                    "import Notes from '@/components/Notes/Notes.vue'\n"
                                    "import InlineLessonMenu from '@/components/Notes/InlineLessonMenu.vue'\n"
                                    "import { parseStoredEditorJs } from '@/utils/lessonForm'\n"
                                    "import { provideStudentView } from '@/composables/useStudentView'\n"
                                    '\n'
                                    'const router = useRouter()\n'),
                                   ('})\n'
                                    '\n'
                                    'const redirectToLogin = () => {\n'
                                    '\twindow.location.href = `/login?redirect-to=${getLmsRoute(\n'
                                    '\t\t`courses/${props.courseName}`\n'
                                    '\t)}`\n'
                                    '}\n'
                                    '\n'
                                    'usePageMeta(() => {\n',
                                    '})\n'
                                    '\n'
                                    'const redirectToLogin = () => {\n'
                                    '\twindow.location.href = '
                                    '`/login?redirect-to=${encodeURIComponent(window.location.pathname + '
                                    'window.location.search + window.location.hash)}`\n'
                                    '}\n'
                                    '\n'
                                    'usePageMeta(() => {\n')]}
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
