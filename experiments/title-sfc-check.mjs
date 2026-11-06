import fs from 'node:fs'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const files = ['components/ChapterRow.vue', 'components/CourseCard.vue', 'components/CreateOutline.vue',
  'components/Courses/CourseDetailsSection.vue', 'components/StudentLessonSidebar.vue',
  'pages/Courses/CourseDetail.vue', 'pages/Courses/CourseOverview.vue', 'pages/Courses/CourseCertification.vue',
  'pages/Forms/NewCourseForm.vue', 'pages/Programs/ProgramEnrollment.vue', 'pages/Lesson.vue', 'pages/LessonForm.vue']
for (const file of files) {
  const parsed = parse(fs.readFileSync('src/' + file, 'utf8'), { filename: file })
  if (parsed.errors.length) throw parsed.errors[0]
  const script = compileScript(parsed.descriptor, { id: 'title-test' })
  const template = compileTemplate({ source: parsed.descriptor.template.content, filename: file,
    id: 'title-test', compilerOptions: { bindingMetadata: script.bindings } })
  if (template.errors.length) throw template.errors[0]
}
console.log('Compiled Vue components:', files.length)
