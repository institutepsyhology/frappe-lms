<template>
	<SettingsLayout title="Должности" description="Настройте подчинённость и права на контакты, доступы к курсам, сотрудников и пароли.">
		<template #header-actions><Button v-if="meta?.capabilities.positions.create" @click="newPosition">Новая должность</Button></template>
		<div v-if="loading">Загрузка…</div>
		<div v-else-if="error" role="alert">{{ error }}</div>
		<div v-else class="grid gap-6 lg:grid-cols-[280px_1fr]">
			<div class="space-y-2">
				<p v-if="!positions.length" class="text-ink-gray-6">Должностей пока нет.</p>
				<button v-for="position in treePositions" :key="position.name" type="button" class="block w-full rounded border p-3 text-left"
					:class="draft?.name === position.name ? 'border-outline-gray-5 bg-surface-gray-2' : ''"
					:style="{ paddingLeft: `${12 + depth(position) * 14}px` }" @click="choose(position)">
					{{ position.title }} <span v-if="!position.active" class="text-ink-gray-5">(отключена)</span>
				</button>
			</div>
			<form v-if="draft" class="space-y-5" @submit.prevent="save">
				<p v-if="!editable" class="rounded bg-surface-gray-2 p-3">Эту должность можно просматривать. Изменения доступны вышестоящему сотруднику.</p>
				<fieldset :disabled="!editable || saving" class="space-y-5">
					<label class="block">Название должности<input v-model="draft.title" maxlength="140" required class="mt-1 block w-full rounded border p-2" /></label>
					<label class="block">Должность руководителя<select v-model="draft.parent_position" class="mt-1 block w-full rounded border p-2">
						<option v-if="!meta?.own_position" value="">Без вышестоящей должности</option>
						<option v-for="position in parentOptions" :key="position.name" :value="position.name">{{ position.title }}</option>
					</select></label>
					<label class="flex gap-2"><input v-model="draft.active" type="checkbox" /> Должность активна</label>
					<label class="block">Работа с доступами к курсам<select v-model="draft.course_scope" class="mt-1 block w-full rounded border p-2">
						<option value="Owned">Только свои курсы</option><option value="All">Все курсы</option>
					</select></label>
					<div class="space-y-3"><h3 class="font-semibold">Права по разделам</h3>
						<p class="text-sm text-ink-gray-6">Изменения в разделе требуют права просмотра. Отправка пароля может быть разрешена без права видеть его.</p>
						<div v-for="(actions, resource) in meta?.resources" :key="resource" class="rounded border p-3">
							<div class="mb-2 font-medium">{{ staffResources[resource] || resource }}</div>
							<div class="flex flex-wrap gap-x-5 gap-y-2"><label v-for="action in actions" :key="action" class="flex items-center gap-2">
								<input type="checkbox" :checked="has(resource, action)" :aria-label="`${staffResources[resource]}: ${staffActions[action]}`"
									@change="toggle(resource, action, ($event.target as HTMLInputElement).checked)" />{{ staffActions[action] }}
							</label></div>
						</div>
					</div>
					<div class="space-y-2"><h3 class="font-semibold">Функции обучения</h3>
						<label v-for="role in meta?.native_roles" :key="role" class="flex gap-2"><input v-model="draft.native_roles" :value="role" type="checkbox" :disabled="role === 'LMS Student'" />{{ staffNativeRoles[role] }}</label>
					</div>
					<p class="text-sm text-ink-gray-6">Подчинённая должность не может получить больше прав, чем её руководитель или сотрудник, который её создаёт.</p>
				</fieldset>
				<div class="flex gap-3"><Button v-if="editable" type="submit" variant="solid" :loading="saving">Сохранить</Button>
					<Button v-if="editable && draft.name && meta?.capabilities.positions.delete" :disabled="saving" @click="remove">Удалить должность</Button></div>
			</form>
			<p v-else class="text-ink-gray-6">Выберите должность или создайте новую.</p>
		</div>
	</SettingsLayout>
</template>
<script setup lang="ts">
import { Button, call, toast } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'
import SettingsLayout from '@/components/Layouts/SettingsLayout.vue'
import { cleanError } from '@/utils'
import { staffActions, staffNativeRoles, staffResources, toggleStaffPermission, type StaffPermission } from '@/utils/staffMatrix'

type Position = { name?: string; title: string; parent_position: string; active: boolean; course_scope: string; permissions: StaffPermission[]; native_roles: string[]; can_edit?: boolean }
type Meta = { own_position: string | null; resources: Record<string,string[]>; native_roles: string[]; capabilities: Record<string,Record<string,boolean>> }
const positions = ref<Position[]>([]), draft = ref<Position | null>(null), meta = ref<Meta | null>(null)
const loading = ref(true), saving = ref(false), error = ref('')
const editable = computed(() => Boolean(draft.value && (draft.value.name ? draft.value.can_edit : meta.value?.capabilities.positions.create)))
const treePositions = computed(() => {
	const result:Position[]=[], seen=new Set<string>()
	const visit=(parent:string)=>{
		for(const position of positions.value.filter(row=>(row.parent_position||'')===parent).sort((a,b)=>a.title.localeCompare(b.title,'ru'))){
			if(!position.name || seen.has(position.name))continue
			seen.add(position.name);result.push(position);visit(position.name)
		}
	}
	const roots=positions.value.filter(row=>!row.parent_position || !positions.value.some(p=>p.name===row.parent_position))
	for(const root of roots.sort((a,b)=>a.title.localeCompare(b.title,'ru'))){if(root.name&&!seen.has(root.name)){seen.add(root.name);result.push(root);visit(root.name)}}
	return result
})
const parentOptions = computed(() => treePositions.value.filter(position => {
	let current=position.name
	const seen=new Set<string>()
	while(current && !seen.has(current)){if(current===draft.value?.name)return false;seen.add(current);current=positions.value.find(p=>p.name===current)?.parent_position}
	return true
}))
const message = (e:any, fallback:string) => cleanError(e?.messages?.[0] || '') || fallback
function depth(position:Position) {
	let parent = position.parent_position, value = 0
	const seen = new Set<string>()
	while (parent && !seen.has(parent)) { const found=positions.value.find(item=>item.name===parent);if(!found)break;seen.add(parent);value++;parent=found.parent_position||'' }
	return value
}
async function load() {
	loading.value = true; error.value = ''
	try { const [m,rows] = await Promise.all([call('lms.lms.staff_positions.metadata'),call('lms.lms.staff_positions.list_positions')]); meta.value=m; positions.value=rows }
	catch(e:any) { error.value=message(e,'Нет доступа к должностям или не удалось загрузить список.') }
	finally { loading.value=false }
}
function choose(position:Position) { draft.value=JSON.parse(JSON.stringify(position)) }
function newPosition() { draft.value={title:'',parent_position:draft.value?.name || meta.value?.own_position || '',active:true,course_scope:'Owned',permissions:[],native_roles:['LMS Student']} }
function has(resource:string,action:string) { return Boolean(draft.value?.permissions.some(row => row.resource===resource && row.action===action)) }
function toggle(resource:string,action:string,enabled:boolean) { if(draft.value) draft.value.permissions=toggleStaffPermission(draft.value.permissions,resource,action,enabled) }
async function save() {
	if(!draft.value || !editable.value) return
	saving.value=true
	try {
		const {can_edit,...values}=draft.value
		const saved=await call('lms.lms.staff_positions.save_position',{values})
		await load(); choose(saved); toast.success('Должность сохранена')
	} catch(e:any) { toast.error(message(e,'Не удалось сохранить должность. Проверьте пределы прав.')) }
	finally { saving.value=false }
}
async function remove() {
	if(!draft.value?.name || !window.confirm('Удалить должность? Должность с сотрудниками или подчинёнными удалить нельзя.')) return
	saving.value=true
	try { await call('lms.lms.staff_positions.delete_position',{name:draft.value.name}); draft.value=null; await load(); toast.success('Должность удалена') }
	catch(e:any) { toast.error(message(e,'Не удалось удалить должность.')) } finally { saving.value=false }
}
onMounted(load)
</script>
