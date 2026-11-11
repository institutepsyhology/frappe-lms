<template>
	<section class="space-y-5 border-t pt-5" data-testid="avo-contact-card">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h3 class="text-lg font-semibold">Карточка контакта</h3>
			<span v-if="card?.custom_avo_contact_id" class="text-sm text-ink-gray-6">
				АВО {{ card.custom_avo_account }} · ID {{ card.custom_avo_contact_id }}
			</span>
		</div>
		<p v-if="loading" class="text-ink-gray-6">Загрузка карточки…</p>
		<p v-else-if="error" class="text-red-700" role="alert">Не удалось загрузить карточку.</p>
		<template v-else-if="card">
			<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
				<FormControl v-model="form.last_name" label="Фамилия" />
				<FormControl v-model="form.first_name" label="Имя" />
				<FormControl v-model="form.middle_name" label="Отчество" />
				<FormControl v-model="form.email" :label="kind === 'User' ? 'Email (логин)' : 'Email'" :disabled="kind === 'User'" />
				<FormControl v-model="form.mobile_no" label="Телефон" />
				<FormControl v-model="form.custom_avo_telegram_username" label="Telegram" />
				<FormControl v-model="form.custom_avo_telegram_id" label="Telegram ID" />
				<FormControl v-model="form.custom_avo_vk_username" label="ВКонтакте" />
				<FormControl v-model="form.custom_avo_vk_id" label="ВКонтакте ID" />
			</div>
			<label class="flex items-center gap-2"><input v-model="noMarketing" type="checkbox" /> Не отправлять рассылки</label>
			<p class="text-sm text-ink-gray-6">Служебные письма о счетах и восстановлении доступа разрешены.</p>
			<div class="flex flex-wrap items-center gap-3">
				<Button variant="solid" :loading="saving" @click="save(false)">Сохранить данные</Button>
				<span class="text-sm text-ink-gray-6">{{ kind === 'Contact' ? 'Контакт без связанной учётной записи' : card.enabled ? 'Учётная запись активна' : 'Учётная запись отключена' }}</span>
				<Button v-if="kind === 'User' && canManageRoles && user.data?.name !== memberId" :loading="statusSaving" @click="changeStatus">{{ card.enabled ? 'Отключить учётную запись' : 'Включить учётную запись' }}</Button>
			</div>
			<details v-if="kind === 'User' && canManageRoles && user.data?.name !== memberId" class="rounded border p-4">
				<summary class="cursor-pointer font-medium">Изменить email-логин</summary>
				<div class="mt-3 flex flex-wrap items-end gap-2">
					<FormControl v-model="newEmail" type="email" label="Новый email" />
					<Button :disabled="!newEmail" :loading="emailSaving" @click="changeEmail">Изменить email</Button>
				</div>
			</details>
			<section v-if="kind === 'User'" class="space-y-3 rounded border p-4" aria-label="Доступ к кабинету">
				<h4 class="font-semibold">Доступ к кабинету</h4>
				<p class="text-sm text-ink-gray-6">Пароль показывается только сотрудникам с правом работы с паролями и после проверки его актуальности.</p>
				<div v-if="canUseCredentials" class="flex flex-wrap gap-2">
					<Button :loading="revealing" @click="revealPassword(false)">Показать пароль</Button>
					<Button :loading="sending" @click="sendPassword">Отправить пароль на почту</Button>
				</div>
				<div v-if="password" class="flex flex-wrap items-center gap-3">
					<code data-testid="revealed-password">{{ password }}</code>
					<Button @click="password = ''">Скрыть</Button>
				</div>
				<p v-if="passwordNotice" class="text-sm text-ink-gray-6">{{ passwordNotice }}</p>
				<div v-if="canUseCredentials" class="flex flex-wrap items-end gap-2">
					<FormControl v-model="newPassword" type="password" label="Новый пароль" autocomplete="new-password" />
					<Button :loading="settingPassword" :disabled="!newPassword" @click="setNewPassword">Установить новый пароль</Button>
				</div>
				<Button :loading="resetting" @click="sendReset">Отправить ссылку для смены пароля</Button>
			</section>
			<section v-if="kind === 'User'" class="space-y-3 rounded border p-4">
				<h4 class="font-semibold">Курсы во Frappe</h4>
				<p v-if="coursesLoading" class="text-sm text-ink-gray-6">Загрузка курсов…</p>
				<p v-else-if="coursesError" class="text-sm text-red-700">Не удалось загрузить курсы.</p>
				<p v-else-if="!courses.length" class="text-sm text-ink-gray-6">Записей на курсы во Frappe пока нет. Доступы из АВО могут быть ещё не перенесены.</p>
				<ul v-else class="space-y-2">
					<li v-for="course in courses" :key="course.course" class="border-b pb-2 text-sm">
						<div>{{ course.title }}</div>
						<div class="text-ink-gray-6">Запись: {{ course.enrolled_at }} · Прогресс: {{ course.progress || 0 }}%</div>
						<div v-for="(grant, index) in course.grants" :key="index" class="text-ink-gray-6">Доступ: {{ grant.status }} · {{ grant.starts_at || 'начало не указано' }} — {{ grant.ends_at || 'окончание не указано' }}</div>
					</li>
				</ul>
			</section>
		</template>
	</section>
</template>

<script setup lang="ts">
import { Button, FormControl, call, toast } from 'frappe-ui'
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { SessionUser } from '@/types'

type Card = { email: string | null; enabled: boolean; custom_avo_contact_id: string; custom_avo_account: string } & Record<string, any>
type Course = { course: string; title: string; enrolled_at: string; progress: number; grants: { status: string; starts_at: string | null; ends_at: string | null }[] }
const props = withDefaults(defineProps<{ memberId: string; kind?: 'User' | 'Contact' }>(), { kind:'User' })
const user = inject<SessionUser>('$user')!
const router = useRouter()
const canManageRoles = computed(() => Boolean(user.data?.is_system_manager || user.data?.name === 'Administrator'))
const canUseCredentials = computed(() => Boolean(user.data?.name === 'Administrator' || user.data?.is_system_manager || user.data?.can_manage_credentials))
const card = ref<Card | null>(null)
const courses = ref<Course[]>([])
const form = reactive({ first_name:'', middle_name:'', last_name:'', email:'', mobile_no:'', custom_avo_telegram_username:'', custom_avo_telegram_id:'', custom_avo_vk_username:'', custom_avo_vk_id:'' })
const noMarketing=ref(false)
const loading=ref(true), error=ref(false), saving=ref(false), revealing=ref(false), sending=ref(false), resetting=ref(false), settingPassword=ref(false), statusSaving=ref(false), emailSaving=ref(false), coursesLoading=ref(true), coursesError=ref(false)
const password=ref('')
const passwordNotice=ref('')
const newPassword=ref('')
const newEmail=ref('')
const message = (err: any, fallback: string) => err?.messages?.[0] || fallback

onMounted(async () => {
	try {
		card.value = await call('lms.lms.avo_contact_card.get_card', { kind:props.kind, name:props.memberId })
		for (const key of Object.keys(form) as (keyof typeof form)[]) form[key] = card.value?.[key] || ''
		noMarketing.value=Boolean(card.value?.custom_no_marketing_email)
	} catch { error.value=true } finally { loading.value=false }
	if (props.kind === 'Contact') { coursesLoading.value=false; return }
	if (card.value && canUseCredentials.value) await revealPassword(true)
	try { courses.value = await call('lms.lms.avo_contact_card.courses_for_user', { name:props.memberId }) }
	catch { coursesError.value=true } finally { coursesLoading.value=false }
})
async function save(silent=false): Promise<boolean> {
	if (!card.value) { toast.error('Дождитесь загрузки карточки'); return false }
	saving.value=true
	try { const values: Record<string,string|boolean>={...form,custom_no_marketing_email:noMarketing.value}; if (props.kind === 'User') delete values.email; card.value=await call('lms.lms.avo_contact_card.save_card',{kind:props.kind,name:props.memberId,values}); if (!silent) toast.success('Данные сохранены'); return true }
	catch (err) { toast.error(message(err,'Не удалось сохранить данные')); return false } finally { saving.value=false }
}
defineExpose({ save })
async function revealPassword(silent=false) {
	password.value=''; passwordNotice.value=''; revealing.value=true
	try { const result=await call('lms.lms.support_credentials.reveal',{name:props.memberId}); password.value=result.password }
	catch (err) { passwordNotice.value='Пароль недоступен. Можно установить новый или отправить ссылку для смены.'; if (!silent) toast.error(message(err,'Пароль недоступен')) } finally { revealing.value=false }
}
async function sendPassword() {
	sending.value=true
	try { await call('lms.lms.support_credentials.send_to_account_email',{name:props.memberId}); toast.success('Письмо поставлено в очередь отправки') }
	catch (err) { toast.error(message(err,'Не удалось отправить пароль')) } finally { sending.value=false }
}
async function sendReset() {
	resetting.value=true
	try { await call('lms.lms.avo_contact_card.send_password_reset',{name:props.memberId}); toast.success('Письмо поставлено в очередь отправки') }
	catch (err) { toast.error(message(err,'Не удалось отправить ссылку')) } finally { resetting.value=false }
}
async function setNewPassword() {
	if (!newPassword.value) return
	settingPassword.value=true
	try { await call('lms.lms.support_credentials.set_new_password',{name:props.memberId,password:newPassword.value}); newPassword.value=''; password.value=''; toast.success('Новый пароль установлен') }
	catch (err) { toast.error(message(err,'Не удалось установить пароль')) } finally { settingPassword.value=false }
}
async function changeStatus() {
	if (!card.value) return
	statusSaving.value=true
	try { const result=await call('lms.lms.avo_contact_card.set_account_enabled',{name:props.memberId,enabled:card.value.enabled ? 0 : 1}); card.value.enabled=result.enabled; toast.success('Статус обновлён') }
	catch (err) { toast.error(message(err,'Не удалось изменить статус')) } finally { statusSaving.value=false }
}
async function changeEmail() {
	if (!newEmail.value.trim()) return
	emailSaving.value=true
	try { if (!(await save(true))) return; const result=await call('lms.lms.avo_contact_card.change_user_email',{name:props.memberId,email:newEmail.value.trim()}); password.value=''; toast.success('Email изменён'); if (router.currentRoute.value.name === 'AvoContactById') window.location.reload(); else await router.replace({name:'MemberForm',params:{memberID:result.name}}) }
	catch (err) { toast.error(message(err,'Не удалось изменить email')) } finally { emailSaving.value=false }
}
</script>
