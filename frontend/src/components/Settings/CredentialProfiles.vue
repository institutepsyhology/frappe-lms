<template>
	<SettingsLayout title="Должности и доступы" description="Настройте право работы с паролями для должностей сотрудников.">
		<div v-if="!isManager" class="p-4 text-ink-gray-6">Настройки доступны системному администратору.</div>
		<div v-else class="space-y-4 p-4">
			<p>Администратор всегда может работать с паролями. Для остальных сотрудников право зависит от их должности.</p>
			<p class="text-sm text-ink-gray-6">При назначении должности Frappe применяет её набор ролей. Проверьте роли должности перед назначением.</p>
			<a href="/app/role-profile" class="text-blue-600 underline">Создать или изменить должности</a>
			<p v-if="loading">Загрузка должностей…</p>
			<p v-else-if="error" role="alert">Не удалось загрузить должности.</p>
			<p v-else-if="!profiles.length">Должностей пока нет. Создайте их по ссылке выше.</p>
			<div v-for="profile in profiles" :key="profile.name" class="flex flex-wrap items-center gap-4 rounded border p-3">
				<span class="min-w-40 font-medium">{{ profile.role_profile || profile.name }}</span>
				<label class="flex items-center gap-2"><input v-model="profile.allowed" type="checkbox" /> Работа с паролями контактов</label>
				<Button :loading="saving===profile.name" @click="save(profile)">Сохранить</Button>
			</div>
		</div>
	</SettingsLayout>
</template>

<script setup lang="ts">
import { Button, call, toast } from 'frappe-ui'
import { computed, inject, onMounted, ref } from 'vue'
import SettingsLayout from '@/components/Layouts/SettingsLayout.vue'
import type { SessionUser } from '@/types'

type Profile = { name:string; role_profile:string; allowed:boolean }
const user=inject<SessionUser>('$user')!
const isManager=computed(() => Boolean(user.data?.name==='Administrator' || user.data?.is_system_manager))
const profiles=ref<Profile[]>([])
const loading=ref(true), error=ref(false), saving=ref('')
onMounted(async () => {
	if (!isManager.value) { loading.value=false; return }
	try {
		const rows=await call('lms.lms.credential_profiles.list_profiles')
		profiles.value=rows.map((row:any) => ({name:row.name,role_profile:row.role_profile,allowed:Boolean(row.custom_can_manage_credentials)}))
	} catch { error.value=true } finally { loading.value=false }
})
async function save(profile:Profile) {
	saving.value=profile.name
	try { const result=await call('lms.lms.credential_profiles.set_profile_access',{profile:profile.name,enabled:profile.allowed ? 1 : 0}); profile.allowed=Boolean(result.enabled); toast.success('Право должности сохранено') }
	catch (err:any) { toast.error(err?.messages?.[0] || 'Не удалось сохранить право') } finally { saving.value='' }
}
</script>
