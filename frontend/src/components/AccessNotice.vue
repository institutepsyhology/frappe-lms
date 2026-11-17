<template>
	<section class="rounded-lg border border-outline-gray-2 bg-surface-base p-5 space-y-4" role="status">
		<p class="font-medium text-ink-gray-9">{{ message || 'Доступ пока закрыт.' }}</p>
		<div ref="holder" class="ProseMirror prose prose-sm max-w-none" />
	</section>
</template>
<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import EditorJS from '@editorjs/editorjs'
import { getEditorTools } from '@/utils'
import { parseStoredEditorJs } from '@/utils/lessonForm'
const props = defineProps({ message: String, content: String })
const holder = ref(null)
let editor = null, generation = 0
let lifecycle = Promise.resolve()
async function destroyEditor() {
    const previous = editor
    editor = null
    if (!previous) return
    try { await previous.isReady; previous.destroy() } catch {}
}
function render() {
    const request = ++generation
    // EditorJS owns this holder until its initialization and destruction finish.
    lifecycle = lifecycle.then(async () => {
        if (request !== generation) return
        await destroyEditor()
        if (request !== generation || !holder.value) return
        holder.value.replaceChildren()
        const data = parseStoredEditorJs(props.content)
        if (!data?.blocks?.length) return
        try {
            editor = new EditorJS({ holder: holder.value, data, readOnly: true,
                tools: getEditorTools(false, {}, { studentView: true }), minHeight: 0 })
            editor.isReady.catch(() => {})
        } catch { editor = null }
    })
    return lifecycle
}
onMounted(render)
watch(() => props.content, render)
onBeforeUnmount(() => { ++generation; lifecycle = lifecycle.then(destroyEditor) })
</script>
