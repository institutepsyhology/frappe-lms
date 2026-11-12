<template>
	<div class="p-8" :role="error ? 'alert' : 'status'">{{ error ? 'В курсе нет доступных вам уроков.' : 'Открываем урок курса…' }}</div>
</template>
<script setup lang="ts">
import { call } from 'frappe-ui'
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
const props=defineProps<{avoCourseId:string}>()
const router=useRouter()
const error=ref(false)
let sequence=0
watch(() => props.avoCourseId, async courseId => {
	const current=++sequence;error.value=false
	try {
		const target=await call('lms.lms.avo_course_routes.resolve_course_start',{course_id:courseId})
		if (current!==sequence) return
		if (!target || target.course_id!==courseId || !/^[1-9]\d{0,19}$/.test(target.lesson_id)) throw new Error('unavailable')
		await router.replace({name:'AvoLesson',params:{avoCourseId:courseId,avoLessonId:target.lesson_id},query:router.currentRoute.value.query})
	} catch { if (current===sequence) error.value=true }
},{immediate:true})
</script>
