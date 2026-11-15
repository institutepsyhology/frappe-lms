<template>
	<p v-if="loading" class="p-8 text-ink-gray-6">Проверяем права…</p>
	<div v-else-if="allowed" class="h-full min-h-0">
		<Members label="Контакты" description="Пользователи и контакты АВО" />
	</div>
	<div v-else class="p-8" role="alert">Нет доступа к карточкам контактов.</div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { call } from 'frappe-ui'
import Members from '@/components/Settings/Members.vue'
const loading = ref(true)
const allowed = ref(false)
onMounted(async () => {
	try { allowed.value = Boolean((await call('lms.lms.contact_workspace.get_capabilities'))?.read) }
	catch { allowed.value = false }
	finally { loading.value = false }
})
</script>
