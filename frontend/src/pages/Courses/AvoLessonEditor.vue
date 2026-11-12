<template>
	<div v-if="target" class="h-full overflow-auto">
		<div class="flex items-center justify-between gap-4 border-b px-5 py-3">
			<router-link :to="{name:'AvoCourse',params:{avoCourseId:sourceCourseId}}" class="text-sm">Курс № {{ sourceCourseId }}</router-link>
			<router-link :to="{name:'AvoLesson',params:{avoCourseId:sourceCourseId,avoLessonId}}" class="rounded border px-3 py-2 text-sm">Предпросмотр урока</router-link>
		</div>
		<LessonForm :key="`${sourceCourseId}:${avoLessonId}`" :course-name="target.course_name"
			:chapter-number="String(target.chapter_number)" :lesson-number="String(target.lesson_number)"
			:avo-course-id="sourceCourseId" :avo-lesson-id="avoLessonId" />
	</div>
	<div v-else-if="error" class="p-8" role="alert">Урок не найден или у вас нет прав на его редактирование.</div>
	<div v-else class="p-8">Загрузка редактора…</div>
</template>
<script setup lang="ts">
import { call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import LessonForm from '@/pages/LessonForm.vue'
type Target = { course_name:string; lesson_name:string; course_id?:string; chapter_number:number; lesson_number:number }
const props=defineProps<{avoCourseId?:string;avoLessonId:string}>()
const target=ref<Target|null>(null)
const sourceCourseId=computed(() => props.avoCourseId || target.value?.course_id || '')
const error=ref(false)
let sequence=0
watch(() => [props.avoCourseId,props.avoLessonId],async ([courseId,lessonId]) => {
	const current=++sequence;target.value=null;error.value=false
	try {
		if (!/^[1-9]\d{0,19}$/.test(lessonId)) throw new Error('invalid_id')
		const result=courseId
			? await call('lms.lms.avo_course_routes.resolve_editor',{course_id:courseId,lesson_id:lessonId})
			: await call('lms.lms.avo_course_routes.resolve_editor_by_lesson',{lesson_id:lessonId})
		if (current!==sequence) return
		if (!result || typeof result.course_name!=='string' || typeof result.lesson_name!=='string' ||
			!Number.isInteger(result.chapter_number) || !Number.isInteger(result.lesson_number) ||
			(!courseId && !/^[1-9]\d{0,19}$/.test(result.course_id))) throw new Error('unavailable')
		target.value=result
	} catch { if (current===sequence) error.value=true }
},{immediate:true})
</script>
