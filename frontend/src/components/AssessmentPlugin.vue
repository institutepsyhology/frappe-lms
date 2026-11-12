<template>
	<Dialog
		v-model:open="show"
		:title="
			type == 'quiz'
				? __('Add a quiz to your lesson')
				: __('Add an assignment to your lesson')
		"
		size="xl"
		:actions="[
			{
				label: __('Save'),
				variant: 'solid',
				onClick: () => {
					addAssessment()
				},
			},
		]"
	>
		<template #default>
			<div class="">
				<div>
					<Link
						v-if="type == 'quiz'"
						v-model="quiz"
						doctype="LMS Quiz"
						:label="__('Select a quiz')"
						placeholder=" "
						:onCreate="(value, close) => redirectToForm()"
					/>
					<div v-else class="space-y-4">
						<Link
							v-if="filterAssignmentsByCourse && courseName"
							v-model="assignment"
							doctype="LMS Assignment"
							:filters="{
								course: courseName,
							}"
							placeholder=" "
							:label="__('Select an Assignment')"
							:onCreate="(value, close) => redirectToForm()"
						/>
						<Link
							v-else-if="!filterAssignmentsByCourse"
							v-model="assignment"
							doctype="LMS Assignment"
							placeholder=" "
							:label="__('Select an Assignment')"
							:onCreate="(value, close) => redirectToForm()"
						/>
						<p v-else class="text-sm text-ink-gray-6">Не удалось определить курс для фильтра.</p>
						<BooleanSwitch
							size="sm"
							:description="__('Only show assignments from the current course')"
							:label="__('Filter assignments by course')"
							v-model="filterAssignmentsByCourse"
						/>
					</div>
				</div>
			</div>
		</template>
	</Dialog>
</template>
<script setup>
import { Dialog, call } from 'frappe-ui'
import BooleanSwitch from '@/components/Controls/BooleanSwitch.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getLmsRoute } from '@/utils/basePath'
import Link from '@/components/Controls/Link.vue'
import { openExternal } from '@/utils/openExternal'

const show = ref(false)
const quiz = ref(null)
const assignment = ref(null)
const filterAssignmentsByCourse = ref(false)
const route = useRoute()
const resolvedCourse = ref('')
const courseName = computed(() => route.params.courseName || resolvedCourse.value)
watch(() => route.params.avoCourseId, async (id) => {
	resolvedCourse.value = ''
	if (typeof id !== 'string') return
	try {
		const result = await call('lms.lms.avo_course_routes.resolve', { course_id:id })
		if (route.params.avoCourseId === id && typeof result?.course_name === 'string') resolvedCourse.value = result.course_name
	} catch { /* keep the filter closed when the course cannot be resolved */ }
}, { immediate:true })

const props = defineProps({
	type: {
		type: String,
		required: true,
	},
	onAddition: {
		type: Function,
		required: true,
	},
})

onMounted(async () => {
	await nextTick()
	show.value = true
})

const addAssessment = () => {
	props.onAddition(props.type == 'quiz' ? quiz.value : assignment.value)
	show.value = false
}

const redirectToForm = () => {
	if (props.type == 'quiz') {
		openExternal(getLmsRoute('quizzes?new=true'))
	} else {
		openExternal(getLmsRoute('assignments/new'))
	}
}
</script>
