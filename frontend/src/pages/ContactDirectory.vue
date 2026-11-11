<template>
	<div v-if="allowed" class="h-full min-h-0">
		<Members label="Контакты" description="Пользователи и контакты АВО" />
	</div>
	<div v-else class="p-8" role="alert">Нет доступа к карточкам контактов.</div>
</template>
<script setup lang="ts">
import { computed, inject } from 'vue'
import Members from '@/components/Settings/Members.vue'
import type { SessionUser } from '@/types'
const user=inject<SessionUser>('$user')!
const allowed=computed(() => Boolean(user.data?.is_system_manager || user.data?.name === 'Administrator' || user.data?.roles?.includes('LMS Credential Manager')))
</script>
