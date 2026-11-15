<template>
	<SettingsLayout title="Сотрудники" description="Сотрудник получает одну должность и только разрешённые ею права.">
		<template #header-actions><Button v-if="meta?.capabilities.staff.create" @click="openNew">Новый сотрудник</Button></template>
		<div v-if="error" role="alert" class="mb-4">{{ error }}</div>
		<form class="mb-4 flex gap-2" @submit.prevent="page=1; loadRows()"><input v-model="search" placeholder="Поиск по имени или почте" aria-label="Поиск сотрудников" class="w-full max-w-md rounded border p-2" /><Button type="submit">Найти</Button></form>
		<p v-if="loading">Загрузка…</p>
		<div v-else class="overflow-x-auto"><table class="w-full text-left"><thead><tr class="border-b"><th class="p-3">ФИО</th><th class="p-3">Почта</th><th class="p-3">Должность</th><th class="p-3">Статус</th><th class="p-3">Действия</th></tr></thead>
			<tbody><tr v-for="row in rows" :key="row.name" class="border-b"><td class="p-3">{{ row.full_name || 'Без имени' }}</td><td class="p-3">{{ row.email || '—' }}</td><td class="p-3">{{ row.position_title || 'Должность не назначена' }}</td><td class="p-3">{{ row.enabled && (row.active == null || row.active) ? 'Активен' : 'Отключён' }}</td><td class="p-3"><div class="flex flex-wrap gap-2"><Button v-if="canEdit(row)" @click="edit(row)">Изменить должность</Button><Button v-if="row.assignment && row.active && meta?.capabilities.staff.delete" :disabled="saving" @click="deactivate(row)">Отключить</Button></div></td></tr>
			<tr v-if="!rows.length"><td colspan="5" class="p-4 text-ink-gray-6">Сотрудников не найдено.</td></tr></tbody>
		</table></div>
		<div class="mt-4 flex flex-wrap items-center gap-3"><span>Всего: {{ total }}</span><label class="flex items-center gap-2">На странице<select v-model.number="pageSize" class="rounded border p-1" @change="page=1; loadRows()"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label>
			<Button :disabled="page <= 1 || loading" @click="page--; loadRows()">Назад</Button><span>{{ page }} / {{ Math.max(1,Math.ceil(total/pageSize)) }}</span><Button :disabled="page*pageSize >= total || loading" @click="page++; loadRows()">Далее</Button>
		</div>
		<Dialog v-model:open="editing" :title="form.existing ? 'Должность сотрудника' : 'Новый сотрудник'" size="lg" :actions="[{label:'Сохранить',variant:'solid',loading:saving,onClick:save}]">
			<template #default><div class="space-y-4">
				<label class="block">Почта или существующий пользователь<input v-model="form.user" :disabled="form.existing" class="mt-1 block w-full rounded border p-2" /></label>
				<template v-if="!form.existing"><label class="block">Имя<input v-model="form.first_name" maxlength="140" class="mt-1 block w-full rounded border p-2" /></label><label class="block">Фамилия<input v-model="form.last_name" maxlength="140" class="mt-1 block w-full rounded border p-2" /></label><p class="text-sm text-ink-gray-6">Если учётной записи ещё нет, она будет создана. Письмо с доступом можно отправить отдельно из карточки контакта при наличии права.</p></template>
				<label class="block">Должность<select v-model="form.position" class="mt-1 block w-full rounded border p-2"><option value="">Выберите должность</option><option v-for="position in assignable" :key="position.name" :value="position.name">{{ position.title }}</option></select></label>
				<label class="flex items-center gap-2"><input v-model="form.active" type="checkbox" :disabled="!meta?.capabilities.staff.delete" /> Сотрудник активен</label>
				<p class="text-sm text-ink-gray-6">При отключении закрывается вход сотрудника. Контакт и его история обучения сохраняются.</p>
			</div></template>
		</Dialog>
	</SettingsLayout>
</template>
<script setup lang="ts">
import { Button, call, Dialog, toast } from 'frappe-ui'
import { computed, onMounted, reactive, ref } from 'vue'
import SettingsLayout from '@/components/Layouts/SettingsLayout.vue'
import { cleanError } from '@/utils'
type Employee={name:string;full_name:string;email:string;enabled:boolean;assignment:string|null;position:string|null;position_title:string|null;active:boolean|null}
type Meta={own_position:string|null;positions:{name:string;title:string;active:boolean}[];capabilities:Record<string,Record<string,boolean>>}
const meta=ref<Meta|null>(null), rows=ref<Employee[]>([]), total=ref(0), page=ref(1),pageSize=ref(50),search=ref(''),loading=ref(true),error=ref(''),editing=ref(false),saving=ref(false)
const form=reactive({user:'',position:'',active:true,existing:false,first_name:'',last_name:''})
const assignable=computed(()=>meta.value?.positions.filter(p=>p.active && p.name!==meta.value?.own_position)||[])
const message=(e:any,fallback:string)=>cleanError(e?.messages?.[0]||'')||fallback
let sequence=0
async function loadRows(){const token=++sequence;loading.value=true;error.value='';try{const result=await call('lms.lms.staff_positions.list_employees',{page:page.value,page_size:pageSize.value,search:search.value});if(token!==sequence)return;rows.value=result.rows;total.value=result.total}catch(e:any){if(token===sequence)error.value=message(e,'Не удалось загрузить сотрудников.')}finally{if(token===sequence)loading.value=false}}
const canEdit=(row:Employee)=>Boolean(row.assignment ? meta.value?.capabilities.staff.write : meta.value?.capabilities.staff.create)
function openNew(){Object.assign(form,{user:'',position:'',active:true,existing:false,first_name:'',last_name:''});editing.value=true}
function edit(row:Employee){Object.assign(form,{user:row.name,position:row.position||'',active:Boolean(row.enabled&&(row.active==null||row.active)),existing:true,first_name:'',last_name:''});editing.value=true}
async function save(){if(!form.user||!form.position){toast.error('Укажите пользователя и должность');return}saving.value=true;try{await call('lms.lms.staff_positions.save_employee',{user:form.user.trim(),position:form.position,active:form.active?1:0,first_name:form.first_name||null,last_name:form.last_name||null});editing.value=false;await loadRows();toast.success('Должность сотрудника сохранена')}catch(e:any){toast.error(message(e,'Не удалось сохранить назначение. Проверьте права и подчинённость.'))}finally{saving.value=false}}
async function deactivate(row:Employee){if(!row.position || !window.confirm('Отключить сотрудника? Его контакт и история обучения сохранятся.'))return;saving.value=true;try{await call('lms.lms.staff_positions.save_employee',{user:row.name,position:row.position,active:0});await loadRows();toast.success('Сотрудник отключён')}catch(e:any){toast.error(message(e,'Не удалось отключить сотрудника.'))}finally{saving.value=false}}
onMounted(async()=>{try{meta.value=await call('lms.lms.staff_positions.metadata');await loadRows()}catch(e:any){error.value=message(e,'Нет доступа к сотрудникам.');loading.value=false}})
</script>
