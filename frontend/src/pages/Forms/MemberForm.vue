<template>
	<FormShell :title="isEdit ? 'Карточка контакта' : 'Новый контакт'" size="3xl" @close="close">
		<template #default>
			<AvoContactCard v-if="isEdit" :key="memberID" :member-id="targetId" :kind="isContact ? 'Contact' : 'User'" />
			<p v-else-if="loading" class="p-4 text-ink-gray-6">Проверяем права…</p>
			<p v-else-if="refusal" role="alert" class="p-4 text-ink-gray-6">{{ refusal }}</p>
			<div v-else data-testid="new-contact-fields" class="grid gap-4 md:grid-cols-2">
				<FormControl v-model="form.last_name" label="Фамилия" />
				<FormControl v-model="form.first_name" label="Имя" />
				<FormControl v-model="form.middle_name" label="Отчество" />
				<FormControl v-model="form.email" label="Email" type="email" />
				<FormControl v-model="form.mobile_no" label="Телефон" />
				<FormControl v-model="form.custom_avo_telegram_username" label="Telegram" />
				<FormControl v-model="form.custom_avo_telegram_id" label="Telegram ID" />
				<FormControl v-model="form.custom_avo_vk_username" label="ВКонтакте" />
				<FormControl v-model="form.custom_avo_vk_id" label="ВКонтакте ID" />
				<p class="text-sm text-ink-gray-6 md:col-span-2">Почта необязательна. Укажите имя, почту, телефон или аккаунт в социальной сети. Создаётся контакт без учётной записи сотрудника.</p>
			</div>
		</template>
		<template #actions>
			<HeaderButton v-if="!isEdit && !loading && !refusal" data-testid="contact-create" label="Создать контакт" variant="solid" :loading="submitting" @click="createContact" />
		</template>
	</FormShell>
</template>
<script setup lang="ts">
import { call, FormControl, toast } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import FormShell from '@/components/FormShell.vue'
import HeaderButton from '@/components/HeaderButton.vue'
import AvoContactCard from '@/components/Settings/AvoContactCard.vue'
import { useFormRoute } from '@/composables/useFormRoute'
import { notifyMembersChanged } from '@/stores/members'
import { cleanError } from '@/utils'

const props = defineProps<{ memberID: string }>()
const router = useRouter()
const { close } = useFormRoute({ name: 'MobileYou' })
const isEdit = computed(() => props.memberID !== 'new')
const isContact = computed(() => props.memberID.startsWith('avo-contact:'))
const targetId = computed(() => isContact.value ? props.memberID.slice('avo-contact:'.length) : props.memberID)
const loading = ref(false)
const allowed = ref(false)
const submitting = ref(false)
const form = reactive({ first_name:'', middle_name:'', last_name:'', email:'', mobile_no:'', custom_avo_telegram_username:'', custom_avo_telegram_id:'', custom_avo_vk_username:'', custom_avo_vk_id:'' })
const refusal = computed(() => {
	if (window.read_only_mode) return 'Сайт работает в режиме чтения.'
	return allowed.value ? '' : 'Нет права создавать контакты.'
})
let sequence = 0
async function loadCapabilities() {
	const token = ++sequence
	if (isEdit.value) { loading.value=false;allowed.value=false;submitting.value=false;return }
	loading.value = true
	allowed.value = false
	try {
		const caps = await call('lms.lms.contact_workspace.get_capabilities')
		if (token === sequence) allowed.value = Boolean(caps?.create)
	} catch { /* Permission is denied until the server confirms it. */ }
	finally { if (token === sequence) loading.value = false }
}
onMounted(loadCapabilities)
watch(() => props.memberID, loadCapabilities)
onBeforeUnmount(() => { ++sequence })
async function createContact() {
	if (isEdit.value || refusal.value || submitting.value) return
	if (!Object.values(form).some(value => value.trim())) {
		toast.error('Укажите имя, почту, телефон или аккаунт в социальной сети.')
		return
	}
	submitting.value = true
	const token=sequence
	try {
		const result = await call('lms.lms.contact_workspace.create_contact', { values: { ...form } })
		if (result?.kind !== 'Contact' || typeof result.name !== 'string' || !result.name) throw new Error('invalid contact')
		notifyMembersChanged()
		if(token!==sequence||isEdit.value)return
		toast.success('Контакт создан')
		await router.replace({ name:'MemberForm', params:{ memberID:`avo-contact:${result.name}` } })
	} catch (err: any) { if(token===sequence)toast.error(cleanError(err?.messages?.[0]) || 'Не удалось создать контакт') }
	finally { if(token===sequence)submitting.value = false }
}
</script>
