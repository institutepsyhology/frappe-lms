<template>
	<details v-if="user?.data?.is_system_manager && lesson" class="rounded-lg border border-outline-gray-2 p-4">
		<summary class="cursor-pointer font-medium">Настройки доступа к этому уроку</summary>
		<div v-if="loading" class="mt-3">Загрузка настроек…</div>
		<div v-else-if="!overview" class="mt-3 text-red-700">Не удалось загрузить настройки доступа.</div>
		<div v-else-if="!overview.policy_exists" class="mt-3">Сначала создайте настройки индивидуального доступа в настройках курса.</div>
		<div v-else class="mt-3 space-y-3">
			<p v-if="!overview.release_enabled || !overview.policy_enabled" class="text-amber-700">Правила доступа пока выключены.</p>
			<label class="block">Открыть урок
				<select v-model="rule.opening_type" class="block w-full rounded border p-2">
					<option value="Unknown">Не задано</option><option value="After Start">Через дни после начала курса</option><option value="At">В указанную дату</option>
				</select>
			</label>
			<label v-if="rule.opening_type === 'After Start'" class="block">Количество дней (0 — сразу)
				<input v-model.number="rule.delay_days" type="number" min="0" class="block w-full rounded border p-2" />
			</label>
			<label v-if="rule.opening_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
				<input v-model="rule.opens_at" type="datetime-local" step="1" class="block w-full rounded border p-2" />
			</label>
			<label class="block">Дополнительное условие
				<select v-model="rule.prerequisite_type" class="block w-full rounded border p-2">
					<option value="Unknown">Не задано</option><option value="None">Без условия</option><option value="Lesson Complete">Завершён другой урок</option><option value="Assignment Submitted">Отправлено задание</option><option value="Assignment Passed">Задание принято</option>
				</select>
			</label>
			<label v-if="!['Unknown', 'None'].includes(rule.prerequisite_type)" class="block">Урок с условием
				<select v-model="rule.prerequisite_lesson" class="block w-full rounded border p-2"><option :value="null">Выберите урок</option><option v-for="item in overview.lessons.filter((item) => item.name !== lesson)" :key="item.name" :value="item.name">{{ item.title || item.name }}</option></select>
			</label>
			<label v-if="['Assignment Submitted', 'Assignment Passed'].includes(rule.prerequisite_type)" class="block">Задание в выбранном уроке
				<select v-model="rule.prerequisite_assignment" :disabled="assignmentsLoading" class="block w-full rounded border p-2"><option :value="null">Выберите задание</option><option v-for="item in assignments" :key="item.name" :value="item.name">{{ item.title }}</option></select>
			</label>
			<p v-if="overview.lessons_truncated">Показаны первые 500 уроков курса.</p>
			<button type="button" class="rounded bg-ink-gray-9 px-4 py-2 text-white" :disabled="busy" @click="save">Сохранить настройки урока</button>
		</div>
	</details>
</template>
<script setup lang="ts">
import { call, toast } from 'frappe-ui'
import { inject, reactive, ref, watch } from 'vue'
import type { SessionUser } from '@/types'
type Rule = { opening_type: string; opens_at: string | null; delay_days: number; prerequisite_type: string; prerequisite_lesson: string | null; prerequisite_assignment: string | null }
type Overview = { release_enabled: boolean; policy_enabled: boolean; policy_exists: boolean; timezone: string; lessons: {name: string; title: string}[]; lessons_truncated: boolean; schedule: (Rule & {lesson: string})[] }
const props = defineProps<{ course: string; lesson?: string }>()
const user = inject<SessionUser>('$user')
const overview = ref<Overview | null>(null)
const loading = ref(false), busy = ref(false), assignmentsLoading = ref(false)
const assignments = ref<{name: string; title: string}[]>([])
const rule = reactive<Rule>({ opening_type: 'Unknown', opens_at: null, delay_days: 0, prerequisite_type: 'Unknown', prerequisite_lesson: null, prerequisite_assignment: null })
let generation = 0
async function load() {
	const request = ++generation
	if (!props.course || !props.lesson || !user?.data?.is_system_manager) return
	loading.value = true
	try {
		const result: Overview = await call('lms.lms.access_actions.get_course_access_overview', { course: props.course })
		if (request !== generation) return
		overview.value = result
		Object.assign(rule, { opening_type: 'Unknown', opens_at: null, delay_days: 0, prerequisite_type: 'Unknown', prerequisite_lesson: null, prerequisite_assignment: null }, result.schedule?.find(item => item.lesson === props.lesson) || {})
		rule.opens_at = rule.opens_at?.replace(' ', 'T') || null
	} catch { if (request === generation) overview.value = null }
	finally { if (request === generation) loading.value = false }
}
let assignmentGeneration = 0
watch(() => [rule.prerequisite_lesson, rule.prerequisite_type], async ([lesson, kind]) => {
	const request = ++assignmentGeneration
	assignments.value = []
	if (!lesson || !['Assignment Submitted', 'Assignment Passed'].includes(kind || '')) { assignmentsLoading.value = false; return }
	assignmentsLoading.value = true
	try {
		const result = await call('lms.lms.access_actions.get_lesson_assignments', { course: props.course, lesson })
		if (request !== assignmentGeneration) return
		assignments.value = result
		if (!result.some((item: {name: string}) => item.name === rule.prerequisite_assignment)) rule.prerequisite_assignment = null
	} catch { if (request === assignmentGeneration) toast.error('Не удалось загрузить задания.') }
	finally { if (request === assignmentGeneration) assignmentsLoading.value = false }
})
async function save() {
	busy.value = true
	try {
		await call('lms.lms.access_actions.update_course_lesson_rule', { course: props.course, lesson: props.lesson, rule: {
			opening_type: rule.opening_type, opens_at: rule.opening_type === 'At' ? rule.opens_at : null,
			delay_days: rule.opening_type === 'After Start' ? rule.delay_days : 0, prerequisite_type: rule.prerequisite_type,
			prerequisite_lesson: ['Unknown', 'None'].includes(rule.prerequisite_type) ? null : rule.prerequisite_lesson,
			prerequisite_assignment: ['Assignment Submitted', 'Assignment Passed'].includes(rule.prerequisite_type) ? rule.prerequisite_assignment : null,
		} })
		await load()
	} catch { toast.error('Не удалось сохранить настройки. Проверьте дату, урок и задание.') }
	finally { busy.value = false }
}
watch(() => [props.course, props.lesson, user?.data?.is_system_manager], load, { immediate: true })
</script>
