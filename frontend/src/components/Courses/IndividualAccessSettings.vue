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
			<p v-if="!overview.policy_exists">Настройки доступа для курса ещё не созданы.</p>
			<p v-if="!overview.grants.length">Персональных карточек пока нет.</p>
			<div v-for="grant in overview.grants" :key="grant.name" class="border rounded p-3 space-y-2">
				<div class="font-medium break-all">{{ grant.member }}</div>
				<div>{{ labels[grant.status] || grant.status }}</div>
				<div v-if="grant.starts_at">Начало: {{ grant.starts_at }}</div>
				<div v-if="grant.ends_at">Окончание: {{ grant.ends_at }}</div>
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

type Grant = { name: string; member: string; status: string; starts_at?: string; ends_at?: string }
type Overview = { release_enabled: boolean; policy_enabled: boolean; policy_exists: boolean; grants: Grant[]; truncated: boolean }
const props = defineProps<{ course: string }>()
const user = inject<SessionUser>('$user')
const overview = ref<Overview | null>(null)
const loading = ref(false)
const error = ref(false)
const busy = ref(false)
const resumeChoice = reactive<Record<string, string>>({})
const labels: Record<string, string> = { Draft: 'Черновик', Active: 'Действует', Frozen: 'Заморожен', Limited: 'Ограничен', Revoked: 'Закрыт' }

async function load() {
	if (!props.course || !user?.data?.is_system_manager) return
	loading.value = true
	error.value = false
	try {
		overview.value = await call('lms.lms.access_actions.get_course_access_overview', { course: props.course })
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
watch(() => [props.course, user?.data?.is_system_manager], load, { immediate: true })
</script>
