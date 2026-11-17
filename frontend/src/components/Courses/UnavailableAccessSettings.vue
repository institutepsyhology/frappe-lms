<template>
	<details v-if="canManage" class="rounded-lg border border-outline-gray-2 p-4 space-y-3">
		<summary class="cursor-pointer font-medium">{{ lesson ? 'Показ закрытого урока' : 'Показ закрытого курса' }}</summary>
		<p v-if="loading">Загрузка настроек…</p>
		<p v-else-if="error" role="alert">Не удалось загрузить настройки. <button @click="load">Повторить</button></p>
		<template v-else>
			<label class="flex items-start gap-2"><input v-model="visible" type="checkbox" :disabled="busy" /> {{ lesson ? 'Показывать урок, даже если он недоступен ученику' : 'Всегда показывать курс в личном кабинете' }}</label>
			<p class="text-sm text-ink-gray-6">При нажатии на закрытый материал ученик увидит причину и сообщение ниже. Это не открывает доступ к содержимому.</p>
			<p class="font-medium">Сообщение при закрытом доступе</p>
			<p class="text-sm text-ink-gray-6">Можно добавить текст, изображения и кнопку со ссылкой на оплату. Задания, тесты и программные упражнения в этом сообщении не отображаются.</p>
			<BlockEditor ref="editor" />
			<Button :disabled="busy" :loading="busy" @click="save">Сохранить показ и сообщение</Button>
		</template>
	</details>
</template>
<script setup lang="ts">
import { computed, inject, nextTick, ref, watch } from 'vue'
import { Button, call, toast } from 'frappe-ui'
import BlockEditor from '@/components/BlockEditor.vue'
import { parseStoredEditorJs } from '@/utils/lessonForm'
import type { SessionUser } from '@/types'
const props = defineProps<{course: string; lesson?: string}>()
const user = inject<SessionUser>('$user')
const canManage = computed(() => !!(user?.data?.is_system_manager || user?.data?.is_moderator || user?.data?.name === 'Administrator'))
const editor = ref<InstanceType<typeof BlockEditor> | null>(null)
const visible = ref(true), loading = ref(false), error = ref(false), busy = ref(false)
let sequence = 0
async function load() {
	const request = ++sequence
	if (!props.course || !canManage.value) return
	loading.value = true; error.value = false
	try {
		const data = await call('lms.lms.access_presentation.get_visibility_settings', {course:props.course,lesson:props.lesson})
		if (request !== sequence) return
		visible.value = !!data.show_when_unavailable
		loading.value = false
		await nextTick(); await editor.value?.isReady()
		if (request === sequence) await editor.value?.render(parseStoredEditorJs(data.access_notice_content) || {blocks:[]})
	} catch { if (request === sequence) error.value = true }
	finally { if (request === sequence) loading.value = false }
}
async function save() {
	if (busy.value || !editor.value) return
	const request = sequence
	const identity = { course: props.course, lesson: props.lesson }
	const show = visible.value
	busy.value = true
	try {
		const data = await editor.value.save()
		if (request !== sequence) return
		await call('lms.lms.access_presentation.save_visibility_settings', {...identity,
			show_when_unavailable:show ? 1 : 0,access_notice_content:JSON.stringify(data || {blocks:[]})})
		if (request === sequence) toast.success('Настройки показа сохранены')
	} catch { if (request === sequence) toast.error('Не удалось сохранить настройки показа') }
	finally { busy.value = false }
}
watch(() => [props.course,props.lesson,canManage.value],load,{immediate:true})
</script>
