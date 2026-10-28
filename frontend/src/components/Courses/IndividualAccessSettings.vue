<template>
	<section v-if="user?.data?.is_system_manager" class="border-t px-5 py-4 space-y-3">
		<h3 class="font-semibold">Индивидуальный доступ</h3>
		<p v-if="loading">Загрузка настроек доступа…</p>
		<p v-else-if="error" class="text-red-700">Не удалось загрузить настройки доступа.</p>
		<template v-else-if="overview">
			<p v-if="!overview.release_enabled" class="text-amber-700">
				Правила пока выключены на сайте. Изменения карточек не влияют на доступ учеников.
			</p>
			<p v-else-if="!overview.policy_enabled" class="text-amber-700">
				Правила этого курса пока выключены.
			</p>
			<div v-if="!overview.policy_exists" class="space-y-2">
				<p>Настройки доступа для курса ещё не созданы.</p>
				<button class="underline" :disabled="busy" @click="createPolicy">Создать настройки доступа</button>
			</div>
			<details v-if="overview.policy && !overview.policy_enabled" class="border rounded p-3">
				<summary class="cursor-pointer">Общие сроки курса</summary>
				<div class="space-y-2 mt-3">
					<label class="block">Персональный срок по умолчанию
						<select v-model="defaults.default_personal_end_type" class="border rounded w-full p-1">
							<option value="Unknown">Не задан</option><option value="Unlimited">Без ограничения</option>
							<option value="After Start">Количество дней от начала</option><option value="At">До даты</option>
						</select>
					</label>
					<label v-if="defaults.default_personal_end_type === 'After Start'" class="block">Дней
						<input v-model.number="defaults.default_personal_end_days" type="number" min="1" class="border rounded w-full p-1" />
					</label>
					<label v-if="defaults.default_personal_end_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
						<input v-model="defaults.default_personal_end_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
					</label>
					<label class="block">Общее окончание курса
						<select v-model="defaults.global_end_type" class="border rounded w-full p-1">
							<option value="Unknown">Не задано</option><option value="Unlimited">Без ограничения</option><option value="At">До даты</option>
						</select>
					</label>
					<label v-if="defaults.global_end_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
						<input v-model="defaults.global_end_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
					</label>
					<label class="block">Доступ к завершённым урокам после окончания
						<select v-model="defaults.completed_retention_type" class="border rounded w-full p-1">
							<option value="None">Не сохранять</option><option value="Unlimited">Без ограничения</option><option value="Days">На количество дней</option>
						</select>
					</label>
					<label v-if="defaults.completed_retention_type === 'Days'" class="block">Дней
						<input v-model.number="defaults.completed_retention_days" type="number" min="1" class="border rounded w-full p-1" />
					</label>
					<button class="underline" :disabled="busy" @click="saveDefaults">Сохранить общие сроки</button>
				</div>
			</details>
			<details v-if="overview.policy_exists && !overview.policy_enabled" class="border rounded p-3">
				<summary class="cursor-pointer">Расписание отдельных уроков</summary>
				<div class="space-y-2 mt-3">
					<label class="block">Урок
						<select v-model="selectedLesson" class="border rounded w-full p-1">
							<option value="">Выберите урок</option>
							<option v-for="lesson in overview.lessons" :key="lesson.name" :value="lesson.name">{{ lesson.title || lesson.name }}</option>
						</select>
					</label>
					<template v-if="selectedLesson">
						<label class="block">Открыть урок
							<select v-model="lessonRule.opening_type" class="border rounded w-full p-1">
								<option value="Unknown">Не задано</option><option value="After Start">Через дни после начала курса</option><option value="At">В указанную дату</option>
							</select>
						</label>
						<label v-if="lessonRule.opening_type === 'After Start'" class="block">Дней после начала
							<input v-model.number="lessonRule.delay_days" type="number" min="0" class="border rounded w-full p-1" />
						</label>
						<label v-if="lessonRule.opening_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
							<input v-model="lessonRule.opens_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
						</label>
						<label class="block">Дополнительное условие
							<select v-model="lessonRule.prerequisite_type" class="border rounded w-full p-1">
								<option value="Unknown">Не задано</option><option value="None">Без условия</option>
								<option value="Lesson Complete">Завершён другой урок</option><option value="Assignment Submitted">Отправлено задание</option><option value="Assignment Passed">Задание принято</option>
							</select>
						</label>
						<label v-if="!['Unknown', 'None'].includes(lessonRule.prerequisite_type)" class="block">Урок с условием
							<select v-model="lessonRule.prerequisite_lesson" class="border rounded w-full p-1">
								<option :value="null">Выберите урок</option>
								<option v-for="lesson in overview.lessons.filter(item => item.name !== selectedLesson)" :key="lesson.name" :value="lesson.name">{{ lesson.title || lesson.name }}</option>
							</select>
						</label>
						<label v-if="['Assignment Submitted', 'Assignment Passed'].includes(lessonRule.prerequisite_type)" class="block">Задание в выбранном уроке
							<select v-model="lessonRule.prerequisite_assignment" class="border rounded w-full p-1" :disabled="assignmentsLoading">
								<option :value="null">Выберите задание</option>
								<option v-for="assignment in assignments" :key="assignment.name" :value="assignment.name">{{ assignment.title }}</option>
							</select>
							<span v-if="!assignmentsLoading && !assignments.length">В уроке нет доступных заданий.</span>
						</label>
						<button class="underline" :disabled="busy" @click="saveLessonRule">Сохранить правило урока</button>
					</template>
				</div>
			</details>
			<details v-if="overview.policy_exists" class="border rounded p-3">
				<summary class="cursor-pointer">Добавить персональную карточку</summary>
				<div class="space-y-2 mt-3">
					<p>Новая карточка не удаляет прежний прогресс и домашние задания.</p>
					<label class="block">Адрес ученика, уже записанного на курс
						<input v-model.trim="newMember" type="email" class="border rounded w-full p-1" />
					</label>
					<label class="block">Начало курса по времени сайта ({{ overview.timezone }})
						<input v-model="newStart" type="datetime-local" class="border rounded w-full p-1" />
					</label>
					<p>Выберите уроки:</p>
					<label v-for="lesson in overview.lessons" :key="lesson.name" class="flex gap-2">
						<input v-model="newLessons" type="checkbox" :value="lesson.name" />
						<span>{{ lesson.title || lesson.name }}</span>
					</label>
					<p v-if="overview.lessons_truncated">Показаны первые 500 уроков.</p>
					<button class="underline" :disabled="busy || !newMember || !newStart || !newLessons.length" @click="createGrant">Создать карточку</button>
				</div>
			</details>
			<p v-if="!overview.grants.length">Персональных карточек пока нет.</p>
			<div v-for="grant in overview.grants" :key="grant.name" class="border rounded p-3 space-y-2">
				<div class="font-medium break-all">{{ grant.member }}</div>
				<div>{{ labels[grant.status] || grant.status }}</div>
				<div v-if="grant.starts_at">Начало: {{ grant.starts_at }}</div>
				<div v-if="grant.ends_at">Окончание: {{ grant.ends_at }}</div>
				<details v-if="grant.status !== 'Revoked' && grantTiming[grant.name]" class="space-y-2">
					<summary class="cursor-pointer">Персональные сроки</summary>
					<div class="space-y-2 mt-2">
						<label class="block">Начало курса ({{ overview.timezone }})
							<input v-model="grantTiming[grant.name].starts_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
						</label>
						<label class="block">Личный срок доступа
							<select v-model="grantTiming[grant.name].personal_end_type" class="border rounded w-full p-1">
								<option value="Inherit">Как у курса</option><option value="Unknown">Не задан</option><option value="Unlimited">Без ограничения</option>
								<option value="After Start">Количество дней от начала</option><option value="At">До даты</option>
							</select>
						</label>
						<label v-if="grantTiming[grant.name].personal_end_type === 'After Start'" class="block">Дней
							<input v-model.number="grantTiming[grant.name].personal_end_days" type="number" min="1" class="border rounded w-full p-1" />
						</label>
						<label v-if="grantTiming[grant.name].personal_end_type === 'At'" class="block">Дата и время окончания
							<input v-model="grantTiming[grant.name].ends_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
						</label>
						<label class="flex gap-2"><input v-model="grantTiming[grant.name].ignore_course_end" type="checkbox" /> Не учитывать общее окончание курса</label>
						<button class="underline" :disabled="busy || !grantTiming[grant.name].starts_at" @click="saveGrantTiming(grant)">Сохранить персональные сроки</button>
					</div>
				</details>
				<div class="flex flex-wrap gap-2">
					<button v-if="grant.status === 'Active'" class="underline" :disabled="busy" @click="freeze(grant)">Заморозить</button>
					<template v-if="grant.status === 'Frozen'">
						<select v-model="resumeChoice[grant.name]" class="border rounded p-1" :disabled="busy">
							<option value="">Выберите действие со сроком</option>
							<option value="1">Продлить на время заморозки</option>
							<option value="0">Не продлевать</option>
						</select>
						<button class="underline" :disabled="busy || !resumeChoice[grant.name]" @click="resume(grant)">Возобновить</button>
					</template>
					<button v-if="['Active', 'Frozen', 'Limited'].includes(grant.status)" class="underline" :disabled="busy" @click="revoke(grant)">Закрыть карточку</button>
				</div>
			</div>
			<p v-if="overview.truncated">Показаны последние 200 карточек.</p>
		</template>
	</section>
</template>

<script setup lang="ts">
import { call, toast } from 'frappe-ui'
import { inject, reactive, ref, watch } from 'vue'
import type { SessionUser } from '@/types'

type Grant = { name: string; member: string; status: string; starts_at?: string; ends_at?: string; personal_end_type?: string; personal_end_days?: number; ignore_course_end?: boolean | number }
type GrantTiming = { starts_at: string; personal_end_type: string; ends_at: string | null; personal_end_days: number; ignore_course_end: boolean }
type Defaults = { default_personal_end_type: string; default_personal_end_at: string | null; default_personal_end_days: number; global_end_type: string; global_end_at: string | null; completed_retention_type: string; completed_retention_days: number }
type LessonRule = { lesson?: string; opening_type: string; opens_at: string | null; delay_days: number; prerequisite_type: string; prerequisite_lesson: string | null; prerequisite_assignment: string | null }
type Overview = { release_enabled: boolean; policy_enabled: boolean; policy_exists: boolean; policy?: Defaults | null; timezone: string; grants: Grant[]; truncated: boolean; lessons: {name: string; title: string}[]; lessons_truncated: boolean; schedule: LessonRule[] }
const props = defineProps<{ course: string }>()
const user = inject<SessionUser>('$user')
const overview = ref<Overview | null>(null)
const loading = ref(false)
const error = ref(false)
const busy = ref(false)
const resumeChoice = reactive<Record<string, string>>({})
const grantTiming = reactive<Record<string, GrantTiming>>({})
const newMember = ref('')
const newStart = ref('')
const newLessons = ref<string[]>([])
const defaults = reactive<Defaults>({ default_personal_end_type: 'Unknown', default_personal_end_at: null,
	default_personal_end_days: 0, global_end_type: 'Unknown', global_end_at: null,
	completed_retention_type: 'None', completed_retention_days: 0 })
const selectedLesson = ref('')
const assignments = ref<{ name: string; title: string }[]>([])
const assignmentsLoading = ref(false)
const lessonRule = reactive<LessonRule>({ opening_type: 'Unknown', opens_at: null, delay_days: 0,
	prerequisite_type: 'Unknown', prerequisite_lesson: null, prerequisite_assignment: null })
const labels: Record<string, string> = { Draft: 'Черновик', Active: 'Активная карточка', Frozen: 'Замороженная карточка', Limited: 'Ограниченная карточка', Revoked: 'Закрытая карточка' }

async function load() {
	if (!props.course || !user?.data?.is_system_manager) return
	loading.value = true
	error.value = false
	try {
		overview.value = await call('lms.lms.access_actions.get_course_access_overview', { course: props.course })
		for (const grant of overview.value?.grants || []) {
			grantTiming[grant.name] = { starts_at: grant.starts_at?.replace(' ', 'T') || '',
				personal_end_type: grant.personal_end_type || 'Unknown', ends_at: grant.ends_at?.replace(' ', 'T') || null,
				personal_end_days: grant.personal_end_days || 0, ignore_course_end: Boolean(grant.ignore_course_end) }
		}
		if (overview.value?.policy) {
			Object.assign(defaults, overview.value.policy)
			defaults.default_personal_end_at = defaults.default_personal_end_at?.replace(' ', 'T') || null
			defaults.global_end_at = defaults.global_end_at?.replace(' ', 'T') || null
		}
	} catch {
		error.value = true
	} finally {
		loading.value = false
	}
}

async function action(method: string, grant: Grant, extra: Record<string, unknown> = {}) {
	busy.value = true
	try {
		await call(`lms.lms.access_actions.${method}`, { name: grant.name, ...extra })
		await load()
	} catch {
		toast.error('Не удалось изменить доступ. Проверьте настройки и попробуйте снова.')
	} finally {
		busy.value = false
	}
}
function freeze(grant: Grant) {
	if (window.confirm('Заморозить эту карточку? Прогресс и домашние задания сохранятся.')) action('freeze_grant', grant)
}
function resume(grant: Grant) {
	if (resumeChoice[grant.name]) action('resume_grant', grant, { extend_personal_end: resumeChoice[grant.name] })
}
function revoke(grant: Grant) {
	if (window.confirm('Закрыть эту карточку? Прогресс и домашние задания сохранятся. Другие карточки ученика не изменятся.')) action('revoke_grant', grant)
}
function saveGrantTiming(grant: Grant) {
	const values = grantTiming[grant.name]
	if (!values?.starts_at) return
	action('update_grant_timing', grant, { starts_at: values.starts_at,
		personal_end_type: values.personal_end_type,
		ends_at: values.personal_end_type === 'At' ? values.ends_at : null,
		personal_end_days: values.personal_end_type === 'After Start' ? values.personal_end_days : 0,
		ignore_course_end: values.ignore_course_end ? 1 : 0 })
}
async function createGrant() {
	if (!newMember.value || !newStart.value || !newLessons.value.length) return
	busy.value = true
	try {
		await call('lms.lms.access_actions.create_grant_for_enrolled_student', {
			course: props.course, member: newMember.value, starts_at: newStart.value, lessons: newLessons.value,
		})
		newMember.value = ''
		newStart.value = ''
		newLessons.value = []
		await load()
	} catch {
		toast.error('Не удалось создать карточку. Проверьте запись ученика на курс и существующие карточки.')
	} finally {
		busy.value = false
	}
}
async function createPolicy() {
	busy.value = true
	try {
		await call('lms.lms.access_actions.create_course_access_policy', { course: props.course })
		await load()
	} catch {
		toast.error('Не удалось создать настройки доступа.')
	} finally {
		busy.value = false
	}
}
async function saveDefaults() {
	busy.value = true
	try {
		await call('lms.lms.access_actions.update_course_access_defaults', { course: props.course, defaults: {
			default_personal_end_type: defaults.default_personal_end_type,
			default_personal_end_at: defaults.default_personal_end_type === 'At' ? defaults.default_personal_end_at : null,
			default_personal_end_days: defaults.default_personal_end_type === 'After Start' ? defaults.default_personal_end_days : 0,
			global_end_type: defaults.global_end_type,
			global_end_at: defaults.global_end_type === 'At' ? defaults.global_end_at : null,
			completed_retention_type: defaults.completed_retention_type,
			completed_retention_days: defaults.completed_retention_type === 'Days' ? defaults.completed_retention_days : 0,
		} })
		await load()
	} catch {
		toast.error('Не удалось сохранить сроки. Проверьте даты и количество дней.')
	} finally {
		busy.value = false
	}
}
watch(selectedLesson, (name) => {
	const saved = overview.value?.schedule?.find((item) => item.lesson === name)
	Object.assign(lessonRule, { opening_type: 'Unknown', opens_at: null, delay_days: 0,
		prerequisite_type: 'Unknown', prerequisite_lesson: null, prerequisite_assignment: null }, saved || {})
	lessonRule.opens_at = lessonRule.opens_at?.replace(' ', 'T') || null
})
let assignmentsRequest = 0
watch(() => [lessonRule.prerequisite_lesson, lessonRule.prerequisite_type], async ([lesson, kind]) => {
	const request = ++assignmentsRequest
	assignments.value = []
	if (!lesson || !['Assignment Submitted', 'Assignment Passed'].includes(kind || '')) {
		assignmentsLoading.value = false
		return
	}
	assignmentsLoading.value = true
	try {
		const result = await call('lms.lms.access_actions.get_lesson_assignments', { course: props.course, lesson })
		if (request !== assignmentsRequest) return
		assignments.value = result
		if (!result.some((item: { name: string }) => item.name === lessonRule.prerequisite_assignment))
			lessonRule.prerequisite_assignment = null
	} catch {
		if (request === assignmentsRequest) toast.error('Не удалось загрузить задания выбранного урока.')
	} finally {
		if (request === assignmentsRequest) assignmentsLoading.value = false
	}
})
async function saveLessonRule() {
	if (!selectedLesson.value) return
	busy.value = true
	try {
		await call('lms.lms.access_actions.update_course_lesson_rule', { course: props.course, lesson: selectedLesson.value, rule: {
			opening_type: lessonRule.opening_type,
			opens_at: lessonRule.opening_type === 'At' ? lessonRule.opens_at : null,
			delay_days: lessonRule.opening_type === 'After Start' ? lessonRule.delay_days : 0,
			prerequisite_type: lessonRule.prerequisite_type,
			prerequisite_lesson: ['Unknown', 'None'].includes(lessonRule.prerequisite_type) ? null : lessonRule.prerequisite_lesson,
			prerequisite_assignment: ['Assignment Submitted', 'Assignment Passed'].includes(lessonRule.prerequisite_type) ? lessonRule.prerequisite_assignment : null,
		} })
		await load()
	} catch {
		toast.error('Не удалось сохранить правило. Проверьте дату, урок и задание.')
	} finally {
		busy.value = false
	}
}
watch(() => [props.course, user?.data?.is_system_manager], load, { immediate: true })
</script>
