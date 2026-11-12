import type { RouteLocationNormalized } from 'vue-router'

export function courseCardRoute(course: { name:string; avo_course_id?:string }) {
	return typeof course.avo_course_id === 'string' && /^[1-9]\d{0,19}$/.test(course.avo_course_id)
		? { name:'AvoCourse', params:{ avoCourseId:course.avo_course_id } }
		: { name:'CourseDetail', params:{ courseName:course.name } }
}

// Canonicalise only mapped, authorised AVO records. Old and non-AVO routes
// continue working if the lookup fails or there is no unique mapping.
export async function canonicalAvoCourseRoute(to: RouteLocationNormalized, call: (method: string, args: object) => Promise<any>) {
	if (to.name !== 'CourseDetail' && to.name !== 'Lesson') return null
	const { courseName, chapterNumber, lessonNumber } = to.params
	if (typeof courseName !== 'string') return null
	const args = to.name === 'Lesson'
		? { course_name:courseName, chapter_number:chapterNumber, lesson_number:lessonNumber }
		: { course_name:courseName }
	try {
		const mapped = await call('lms.lms.avo_course_routes.canonical', args)
		if (!mapped || !/^[1-9]\d*$/.test(mapped.course_id) || (to.name === 'Lesson' && !/^[1-9]\d*$/.test(mapped.lesson_id))) return null
		return to.name === 'Lesson'
			? { name:'AvoLesson', params:{ avoCourseId:mapped.course_id, avoLessonId:mapped.lesson_id }, query:to.query, hash:to.hash }
			: { name:'AvoCourse', params:{ avoCourseId:mapped.course_id }, query:to.query, hash:to.hash }
	} catch { return null }
}
