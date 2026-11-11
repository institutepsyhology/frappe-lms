<template>
	<MemberForm v-if="target" :key="target" v-bind="{ memberID: target }" />
	<div v-else-if="error" class="p-8" role="alert">Не удалось открыть контакт по ID. Проверьте номер и права доступа.</div>
	<div v-else class="p-8">Загружаем контакт…</div>
</template>
<script setup lang="ts">
import { call } from 'frappe-ui'
import { ref, watch } from 'vue'
import MemberForm from './MemberForm.vue'

const props = defineProps<{ avoId: string }>()
const target = ref('')
const error = ref(false)
let sequence = 0
watch(() => props.avoId, async id => {
	const current = ++sequence
	target.value = ''
	error.value = false
	try {
		const result = await call('lms.lms.avo_contact_card.resolve_source_id', { source_id:id })
		if (current !== sequence) return
		if (!result || !['User', 'Contact'].includes(result.kind) || typeof result.name !== 'string' || !result.name) throw new Error('invalid contact')
		target.value = result.kind === 'Contact' ? `avo-contact:${result.name}` : result.name
	} catch {
		if (current === sequence) error.value = true
	}
}, { immediate:true })
</script>
