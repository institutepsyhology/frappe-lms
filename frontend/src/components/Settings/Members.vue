<template>
	<section class="flex h-full min-h-0 flex-col gap-4 p-5" aria-label="Контакты">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div><h2 class="text-lg font-semibold">Контакты</h2><p class="text-sm text-ink-gray-6">{{ description }}</p></div>
			<Button v-if="canCreate && !readOnly" variant="solid" @click="openNew">Новый контакт</Button>
		</div>
		<FormControl v-model="search" type="search" placeholder="ФИО, почта, телефон или ID АВО" label="Поиск контактов" />
		<p v-if="error" class="text-red-700" role="alert">Не удалось загрузить контакты. Проверьте права доступа.</p>
		<div class="min-h-0 flex-1 overflow-auto" :aria-busy="loading">
			<table class="w-full text-left text-sm">
				<thead class="sticky top-0 bg-surface-white"><tr>
					<th v-for="column in columns" :key="column.key" class="p-2" :aria-sort="sort === column.key ? direction === 'asc' ? 'ascending' : 'descending' : 'none'">
						<button type="button" class="text-left font-medium" @click="setSort(column.key)">{{ column.label }} {{ sort === column.key ? direction === 'asc' ? '↑' : '↓' : '' }}</button>
					</th>
				</tr></thead>
				<tbody><tr v-for="row in rows" :key="`${row.kind}:${row.name}`" class="border-t">
					<td class="p-2"><button type="button" class="text-left text-blue-700 underline" @click="openContact(row)">{{ row.full_name || 'Без имени' }}</button></td>
					<td class="p-2"><button v-if="row.email" type="button" class="text-left text-blue-700 underline" @click="openContact(row)">{{ row.email }}</button><span v-else>—</span></td>
					<td class="p-2">{{ row.mobile_no || '—' }}</td>
					<td class="p-2">{{ row.source_id || '—' }}</td>
				</tr></tbody>
			</table>
			<p v-if="loading" class="p-3 text-ink-gray-6">Загрузка…</p>
			<p v-else-if="!rows.length && !error" class="p-3 text-ink-gray-6">Контакты не найдены.</p>
		</div>
		<div class="flex flex-wrap items-center justify-between gap-3 text-sm">
			<label>На странице <select v-model.number="pageSize" class="rounded border p-1" aria-label="Контактов на странице" @change="resetPage"><option v-for="size in [25,50,100,200]" :key="size" :value="size">{{ size }}</option></select></label>
			<div class="flex items-center gap-2"><Button :disabled="page <= 1 || loading" @click="goPage(page - 1)">Назад</Button><span>Страница {{ page }} из {{ pageCount }} · Всего {{ total }}</span><Button :disabled="page >= pageCount || loading" @click="goPage(page + 1)">Далее</Button></div>
		</div>
	</section>
</template>
<script setup lang="ts">
import { Button, FormControl, call } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { openFormRoute } from '@/composables/useFormRoute'
import { membersRevision } from '@/stores/members'

defineProps<{ label?:string; description?:string }>()
defineModel('show')
type Person = { kind:'User'|'Contact'; name:string; full_name:string|null; email:string|null; mobile_no:string|null; source_id:string|null }
type Sort = 'full_name'|'email'|'mobile_no'|'source_id'
const router=useRouter()
const rows=ref<Person[]>([]),total=ref(0),page=ref(1),pageSize=ref(50)
const search=ref(''),sort=ref<Sort>('full_name'),direction=ref<'asc'|'desc'>('asc')
const loading=ref(false),error=ref(false),canCreate=ref(false)
const readOnly=Boolean(window.read_only_mode)
const pageCount=computed(() => Math.max(1,Math.ceil(total.value/pageSize.value)))
const columns:{key:Sort;label:string}[]=[{key:'full_name',label:'ФИО'},{key:'email',label:'Email'},{key:'mobile_no',label:'Телефон'},{key:'source_id',label:'ID АВО'}]
let request=0,searchTimer:ReturnType<typeof setTimeout>|undefined
async function fetchPeople(){
	const token=++request
	loading.value=true;error.value=false
	try{
		const result=await call('lms.lms.contact_workspace.list_people',{page:page.value,page_size:pageSize.value,search:search.value,sort:sort.value,direction:direction.value})
		if(token!==request)return
		if(!Array.isArray(result?.rows)||!Number.isInteger(result.total))throw new Error('invalid contacts')
		rows.value=result.rows;total.value=result.total;canCreate.value=Boolean(result.can_create)
		if(page.value>pageCount.value){page.value=pageCount.value;await fetchPeople()}
	}catch{if(token===request){error.value=true;rows.value=[];total.value=0;canCreate.value=false}}
	finally{if(token===request)loading.value=false}
}
function resetPage(){page.value=1;fetchPeople()}
function goPage(value:number){page.value=value;fetchPeople()}
function setSort(value:Sort){direction.value=sort.value===value&&direction.value==='asc'?'desc':'asc';sort.value=value;resetPage()}
function openContact(row:Person){
	if(row.source_id&&/^[1-9][0-9]*$/.test(row.source_id)){openFormRoute(router,{name:'AvoContactById',params:{avoId:row.source_id}});return}
	openFormRoute(router,{name:'MemberForm',params:{memberID:row.kind==='Contact'?`avo-contact:${row.name}`:row.name}})
}
function openNew(){if(canCreate.value&&!readOnly)openFormRoute(router,{name:'MemberForm',params:{memberID:'new'}})}
watch(search,()=>{clearTimeout(searchTimer);++request;loading.value=true;searchTimer=setTimeout(resetPage,250)})
watch(membersRevision,resetPage)
onMounted(fetchPeople)
onBeforeUnmount(()=>{++request;clearTimeout(searchTimer)})
</script>
