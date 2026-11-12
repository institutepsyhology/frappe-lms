<template>
	<CourseDetail v-if="target && !avoLessonId" :key="target.course_name" :course-name="target.course_name" />
	<Lesson v-else-if="target && avoLessonId" :key="`${avoCourseId}:${avoLessonId}`"
		:course-name="target.course_name" :chapter-number="String(target.chapter_number)" :lesson-number="String(target.lesson_number)"
		:avo-course-id="avoCourseId" :avo-lesson-id="avoLessonId" />
	<div v-else-if="error" class="p-8" role="alert">Курс или урок не найден либо у вас нет доступа.</div>
	<div v-else class="p-8">Загрузка…</div>
</template>
<script setup lang="ts">
import { call } from 'frappe-ui'
import { ref, watch } from 'vue'
import CourseDetail from '@/pages/Courses/CourseDetail.vue'
import Lesson from '@/pages/Lesson.vue'

type Target = { course_name: string; chapter_number?: number; lesson_number?: number }
const props = defineProps<{ avoCourseId: string; avoLessonId?: string }>()
const target = ref<Target | null>(null)
const error = ref(false)
let sequence = 0
watch(() => [props.avoCourseId, props.avoLessonId], async ([courseId, lessonId]) => {
	const current = ++sequence
	target.value = null
	error.value = false
	try {
		const result = await call('lms.lms.avo_course_routes.resolve', { course_id:courseId, ...(lessonId ? {lesson_id:lessonId} : {}) })
		if (current !== sequence) return
		if (!result || typeof result.course_name !== 'string' || !result.course_name ||
			(lessonId && (!Number.isInteger(result.chapter_number) || !Number.isInteger(result.lesson_number)))) throw new Error('unavailable')
		target.value = result
	} catch {
		if (current === sequence) error.value = true
	}
}, { immediate:true })
</script>
