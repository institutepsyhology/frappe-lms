<template>
	<section class="space-y-5" data-testid="avo-contact-card">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h3 class="text-lg font-semibold">Карточка контакта</h3>
			<span v-if="card?.custom_avo_contact_id" class="text-sm text-ink-gray-6">АВО {{ card.custom_avo_account }} · ID {{ card.custom_avo_contact_id }}</span>
		</div>
		<p v-if="loading" class="text-ink-gray-6">Загрузка карточки…</p>
		<p v-else-if="error" class="text-red-700" role="alert">Нет доступа к карточке или контакт не найден.</p>
		<template v-else-if="card">
			<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
				<FormControl v-model="form.last_name" label="Фамилия" :disabled="!canWrite" />
				<FormControl v-model="form.first_name" label="Имя" :disabled="!canWrite" />
				<FormControl v-model="form.middle_name" label="Отчество" :disabled="!canWrite" />
				<FormControl v-model="form.email" label="Email" :disabled="!canWrite || isUser" />
				<FormControl v-model="form.mobile_no" label="Телефон" :disabled="!canWrite" />
				<FormControl v-model="form.custom_avo_telegram_username" label="Telegram" :disabled="!canWrite" />
				<FormControl v-model="form.custom_avo_telegram_id" label="Telegram ID" :disabled="!canWrite" />
				<FormControl v-model="form.custom_avo_vk_username" label="ВКонтакте" :disabled="!canWrite" />
				<FormControl v-model="form.custom_avo_vk_id" label="ВКонтакте ID" :disabled="!canWrite" />
			</div>
			<label class="flex items-center gap-2"><input v-model="noMarketing" :disabled="!canWrite" type="checkbox" /> Не отправлять рассылки</label>
			<p class="text-sm text-ink-gray-6">Служебные письма о счетах и восстановлении доступа разрешены.</p>
			<div class="flex flex-wrap items-center gap-3">
				<Button v-if="canWrite" variant="solid" :loading="saving" @click="save(false)">Сохранить данные</Button>
				<span class="text-sm text-ink-gray-6">{{ !isUser ? 'Контакт без связанной учётной записи' : card.enabled ? 'Учётная запись активна' : 'Учётная запись отключена' }}</span>
				<span v-if="!canWrite" class="text-sm text-ink-gray-6">Просмотр без изменения данных</span>
			</div>
			<section v-if="isUser && (canReadCredentials || canWriteCredentials || canSendCredentials)" class="space-y-3 rounded border p-4" aria-label="Доступ к кабинету">
				<h4 class="font-semibold">Доступ к кабинету</h4>
				<p class="text-sm text-ink-gray-6">Пароли доступны только сотрудникам с соответствующим правом.</p>
				<div class="flex flex-wrap gap-2">
					<Button v-if="canReadCredentials" :loading="revealing" @click="revealPassword(false)">Показать пароль</Button>
					<Button v-if="canSendCredentials" :loading="sending" @click="sendPassword">Отправить пароль на почту</Button>
				</div>
				<div v-if="password" class="flex flex-wrap items-center gap-3">
					<code data-testid="revealed-password">{{ password }}</code>
					<Button @click="password = ''">Скрыть</Button>
				</div>
				<p v-if="passwordNotice" class="text-sm text-ink-gray-6">{{ passwordNotice }}</p>
				<div v-if="canWriteCredentials" class="flex flex-wrap items-end gap-2">
					<FormControl v-model="newPassword" type="password" label="Новый пароль" autocomplete="new-password" />
					<Button :loading="settingPassword" :disabled="!newPassword" @click="setNewPassword">Установить новый пароль</Button>
				</div>
				<Button v-if="canSendCredentials" :loading="resetting" @click="sendReset">Отправить ссылку для смены пароля</Button>
			</section>
			<section class="space-y-3 rounded border p-4" aria-label="Курсы контакта">
				<h4 class="font-semibold">Курсы контакта</h4>
				<p v-if="coursesLoading" class="text-sm text-ink-gray-6">Загрузка курсов…</p>
				<p v-else-if="coursesError" class="text-sm text-red-700" role="alert">Не удалось загрузить курсы.</p>
				<p v-else-if="!courses.length" class="text-sm text-ink-gray-6">Доступных для просмотра записей на курсы нет.</p>
				<div v-else class="overflow-x-auto">
					<table class="w-full text-left text-sm">
						<thead><tr>
							<th v-for="column in columns" :key="column.key" class="p-2" :aria-sort="sort === column.key ? direction === 'asc' ? 'ascending' : 'descending' : 'none'">
								<button type="button" class="text-left font-medium" @click="sortCourses(column.key)">{{ column.label }} {{ sort === column.key ? direction === 'asc' ? '↑' : '↓' : '' }}</button>
							</th>
						</tr></thead>
						<tbody><tr v-for="course in courses" :key="course.course || `avo:${course.source_course_id}`" class="border-t">
							<td class="p-2 align-top">
								<button v-if="course.course" type="button" class="text-left text-blue-700 underline" @click="openCourse(course)">{{ course.title }}</button>
								<span v-else>{{ course.title }}</span>
								<div class="text-ink-gray-6">{{ statusLabel(course.status) }}{{ course.archive_only ? ' · Архив АВО' : '' }}</div>
							</td>
							<td class="p-2 align-top">{{ course.starts_at || 'Не указана' }}</td>
							<td class="p-2 align-top">{{ course.ends_at || (course.end_unknown ? 'Неизвестно' : 'Без ограничения') }}</td>
							<td class="p-2 align-top">
								<div>{{ course.source_label }}</div>
								<div class="text-ink-gray-6">Кто и когда выдал: {{ course.source_actor || 'не записано' }}{{ course.source_event_at ? ` · ${course.source_event_at}` : '' }}</div>
								<div v-if="course.imported_at" class="text-ink-gray-6">Импорт: {{ course.imported_by || 'сотрудник не указан' }} · {{ course.imported_at }}</div>
							</td>
						</tr></tbody>
					</table>
				</div>
				<div class="flex flex-wrap items-center justify-between gap-3 text-sm">
					<label>На странице <select v-model.number="pageSize" class="rounded border p-1" aria-label="Курсов на странице" @change="changePageSize"><option v-for="size in [25,50,100,200]" :key="size" :value="size">{{ size }}</option></select></label>
					<div class="flex items-center gap-2"><Button :disabled="page <= 1 || coursesLoading" @click="changePage(page - 1)">Назад</Button><span>Страница {{ page }} из {{ pageCount }} · Всего {{ total }}</span><Button :disabled="page >= pageCount || coursesLoading" @click="changePage(page + 1)">Далее</Button></div>
				</div>
			</section>
		</template>
		<PersonCourseAccessDialog v-if="selectedCourse" v-model:open="accessOpen" :course="selectedCourse" :member="isUser ? recordName : undefined" :contact="!isUser ? recordName : undefined" @saved="loadCourses" />
	</section>
</template>

<script setup lang="ts">
import { Button, FormControl, call, toast } from 'frappe-ui'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import PersonCourseAccessDialog from '@/components/PersonCourseAccessDialog.vue'
import { notifyMembersChanged } from '@/stores/members'

type Card = { kind:'User'|'Contact'; name:string; email:string|null; enabled:boolean|null; custom_avo_contact_id:string; custom_avo_account:string; capabilities:{read:boolean;write:boolean;credential_read:boolean;credential_write:boolean;credential_send:boolean} } & Record<string, any>
type SortField = 'title'|'starts_at'|'ends_at'|'source_type'
type Course = { course:string|null; source_course_id:string|null; title:string; starts_at:string|null; ends_at:string|null; end_unknown:boolean; status:string; archive_only:boolean; source_label:string; source_actor:string|null; source_event_at:string|null; imported_at:string|null; imported_by:string|null }
const props = withDefaults(defineProps<{ memberId:string; kind?:'User'|'Contact' }>(), { kind:'User' })
const card = ref<Card|null>(null)
const recordName = computed(() => card.value?.name || props.memberId)
const isUser = computed(() => (card.value?.kind || props.kind) === 'User')
const canWrite = computed(() => Boolean(card.value?.capabilities?.write && !window.read_only_mode))
const canReadCredentials = computed(() => Boolean(card.value?.capabilities?.credential_read))
const canWriteCredentials = computed(() => Boolean(card.value?.capabilities?.credential_write && !window.read_only_mode))
const canSendCredentials = computed(() => Boolean(card.value?.capabilities?.credential_send && !window.read_only_mode))
const form = reactive({ first_name:'', middle_name:'', last_name:'', email:'', mobile_no:'', custom_avo_telegram_username:'', custom_avo_telegram_id:'', custom_avo_vk_username:'', custom_avo_vk_id:'' })
const noMarketing = ref(false)
const loading=ref(true), error=ref(false), saving=ref(false), revealing=ref(false), sending=ref(false), resetting=ref(false), settingPassword=ref(false), coursesLoading=ref(false), coursesError=ref(false)
const password=ref(''), passwordNotice=ref(''), newPassword=ref('')
const courses=ref<Course[]>([]), total=ref(0), page=ref(1), pageSize=ref(50)
const sort=ref<SortField>('title'), direction=ref<'asc'|'desc'>('asc')
const selectedCourse=ref(''), accessOpen=ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value/pageSize.value)))
const columns:{key:SortField;label:string}[] = [{key:'title',label:'Курс'},{key:'starts_at',label:'Открытие доступа'},{key:'ends_at',label:'Закрытие доступа'},{key:'source_type',label:'Как получен доступ'}]
const message = (err:any, fallback:string) => err?.messages?.[0] || fallback
let cardSequence=0, courseSequence=0
onBeforeUnmount(()=>{++cardSequence;++courseSequence;password.value='';newPassword.value=''})

watch(() => [props.kind,props.memberId], async () => {
	const token=++cardSequence
	++courseSequence
	card.value=null;password.value='';newPassword.value='';passwordNotice.value='';courses.value=[];total.value=0;page.value=1;accessOpen.value=false;selectedCourse.value='';error.value=false;loading.value=true
	saving.value=false;revealing.value=false;sending.value=false;resetting.value=false;settingPassword.value=false
	try {
		const result=await call('lms.lms.contact_workspace.get_card',{kind:props.kind,name:props.memberId})
		if(token!==cardSequence)return
		if(!result || !['User','Contact'].includes(result.kind) || !result.name || !result.capabilities?.read)throw new Error('invalid card')
		card.value=result
		for(const key of Object.keys(form) as (keyof typeof form)[])form[key]=result[key]||''
		noMarketing.value=Boolean(result.custom_no_marketing_email)
		if(isUser.value && canReadCredentials.value)await revealPassword(true)
		if(token===cardSequence)await loadCourses()
	} catch { if(token===cardSequence)error.value=true }
	finally { if(token===cardSequence)loading.value=false }
},{immediate:true})

async function save(silent=false):Promise<boolean> {
	if(!card.value || !canWrite.value || saving.value)return false
	const token=cardSequence
	const kind=card.value.kind,name=recordName.value
	saving.value=true
	try {
		const values:Record<string,string|boolean>={...form,custom_no_marketing_email:noMarketing.value}
		if(isUser.value)delete values.email
		const result=await call('lms.lms.contact_workspace.save_card',{kind,name,values})
		if(token!==cardSequence)return false
		card.value=result
		notifyMembersChanged()
		if(!silent)toast.success('Данные сохранены')
		return true
	} catch(err){if(token===cardSequence)toast.error(message(err,'Не удалось сохранить данные'));return false}
	finally{if(token===cardSequence)saving.value=false}
}
defineExpose({save})
async function loadCourses() {
	if(!card.value)return
	const token=++courseSequence
	coursesLoading.value=true;coursesError.value=false
	try {
		const result=await call('lms.lms.contact_workspace.list_person_courses',{kind:card.value.kind,name:recordName.value,page:page.value,page_size:pageSize.value,sort:sort.value,direction:direction.value})
		if(token!==courseSequence)return
		if(!Array.isArray(result?.rows)||!Number.isInteger(result.total))throw new Error('invalid courses')
		courses.value=result.rows;total.value=result.total
		if(page.value>pageCount.value){page.value=pageCount.value;await loadCourses()}
	}catch{if(token===courseSequence){coursesError.value=true;courses.value=[]}}
	finally{if(token===courseSequence)coursesLoading.value=false}
}
function changePage(value:number){page.value=value;loadCourses()}
function changePageSize(){page.value=1;loadCourses()}
function sortCourses(field:SortField){direction.value=sort.value===field&&direction.value==='asc'?'desc':'asc';sort.value=field;page.value=1;loadCourses()}
function openCourse(course:Course){if(!course.course)return;selectedCourse.value=course.course;accessOpen.value=true}
function statusLabel(value:string){return ({Blocked:'Закрыт блокировкой',Active:'Открыт',Frozen:'Приостановлен',Revoked:'Закрыт',Limited:'Ограничен',Expired:'Срок истёк',Draft:'Черновик','Pending Contact':'Ожидает учётную запись','Pending Course':'Ожидает курс',Applied:'Перенесён',Superseded:'Историческая запись',Unknown:'Статус неизвестен'} as Record<string,string>)[value]||value}
async function revealPassword(silent=false){
	if(!isUser.value||!canReadCredentials.value)return
	const target=recordName.value,token=cardSequence
	password.value='';passwordNotice.value='';revealing.value=true
	try{const result=await call('lms.lms.support_credentials.reveal',{name:target});if(token===cardSequence)password.value=result.password}
	catch(err){if(token===cardSequence){passwordNotice.value='Пароль недоступен. Можно установить новый или отправить ссылку для смены.';if(!silent)toast.error(message(err,'Пароль недоступен'))}}
	finally{if(token===cardSequence)revealing.value=false}
}
async function sendPassword(){
	if(!canSendCredentials.value||sending.value)return
	const token=cardSequence,target=recordName.value;sending.value=true
	try{await call('lms.lms.support_credentials.send_to_account_email',{name:target});if(token===cardSequence)toast.success('Письмо поставлено в очередь отправки')}
	catch(err){if(token===cardSequence)toast.error(message(err,'Не удалось отправить пароль'))}
	finally{if(token===cardSequence)sending.value=false}
}
async function sendReset(){
	if(!canSendCredentials.value||resetting.value)return
	const token=cardSequence,target=recordName.value;resetting.value=true
	try{await call('lms.lms.avo_contact_card.send_password_reset',{name:target});if(token===cardSequence)toast.success('Письмо поставлено в очередь отправки')}
	catch(err){if(token===cardSequence)toast.error(message(err,'Не удалось отправить ссылку'))}
	finally{if(token===cardSequence)resetting.value=false}
}
async function setNewPassword(){
	if(!canWriteCredentials.value||!newPassword.value||settingPassword.value)return
	const token=cardSequence,target=recordName.value,value=newPassword.value;settingPassword.value=true
	try{await call('lms.lms.support_credentials.set_new_password',{name:target,password:value});if(token===cardSequence){newPassword.value='';password.value='';toast.success('Новый пароль установлен')}}
	catch(err){if(token===cardSequence)toast.error(message(err,'Не удалось установить пароль'))}
	finally{if(token===cardSequence)settingPassword.value=false}
}
</script>
