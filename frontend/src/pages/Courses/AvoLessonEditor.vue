<template>
	<div v-if="target" class="h-full overflow-auto">
		<div class="flex items-center justify-between gap-4 border-b px-5 py-3">
			<router-link :to="{name:'AvoCourse',params:{avoCourseId}}" class="text-sm">Курс № {{ avoCourseId }}</router-link>
			<router-link :to="{name:'AvoLesson',params:{avoCourseId,avoLessonId}}" class="rounded border px-3 py-2 text-sm">Предпросмотр урока</router-link>
		</div>
		<LessonForm :key="`${avoCourseId}:${avoLessonId}`" :course-name="target.course_name"
			:chapter-number="String(target.chapter_number)" :lesson-number="String(target.lesson_number)"
			:avo-course-id="avoCourseId" :avo-lesson-id="avoLessonId" />
	</div>
	<div v-else-if="error" class="p-8" role="alert">Урок не найден или у вас нет прав на его редактирование.</div>
	<div v-else class="p-8">Загрузка редактора…</div>
</template>
<script setup lang="ts">
import { call } from 'frappe-ui'
import { ref, watch } from 'vue'
import LessonForm from '@/pages/LessonForm.vue'
type Target = { course_name:string; lesson_name:string; chapter_number:number; lesson_number:number }
const props=defineProps<{avoCourseId:string;avoLessonId:string}>()
const target=ref<Target|null>(null)
const error=ref(false)
let sequence=0
watch(() => [props.avoCourseId,props.avoLessonId],async ([courseId,lessonId]) => {
	const current=++sequence;target.value=null;error.value=false
	try {
		const result=await call('lms.lms.avo_course_routes.resolve_editor',{course_id:courseId,lesson_id:lessonId})
		if (current!==sequence) return
		if (!result || typeof result.course_name!=='string' || typeof result.lesson_name!=='string' ||
			!Number.isInteger(result.chapter_number) || !Number.isInteger(result.lesson_number)) throw new Error('unavailable')
		target.value=result
	} catch { if (current===sequence) error.value=true }
},{immediate:true})
</script>
