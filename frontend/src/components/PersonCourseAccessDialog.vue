<template>
	<Dialog :open="open" title="Индивидуальный доступ к курсу" size="5xl" @update:open="emit('update:open', $event)">
		<template #default>
			<div class="max-h-[72vh] overflow-y-auto space-y-4 text-base" data-testid="person-course-access">
				<p v-if="loading">Загрузка доступа…</p>
				<div v-else-if="error" role="alert">Не удалось загрузить доступ. <Button @click="load">Повторить</Button></div>
				<template v-else-if="details">
					<p v-if="details.archive_only">{{ details.notice }}</p>
					<template v-else>
						<fieldset class="rounded border p-3 space-y-3" :disabled="busy || !details.capabilities.write">
							<legend class="font-semibold">Блокировка курса для этого ученика</legend>
							<p v-if="courseBlock?.effective" class="text-red-700">Курс закрыт {{ courseBlock.blocked_until ? 'до ' + courseBlock.blocked_until : 'бессрочно' }}. Эта блокировка действует для всех записей доступа ученика к курсу.</p>
							<label class="flex gap-2"><input v-model="blockForm.blocked" type="checkbox" /> Закрыть доступ к курсу</label>
							<div v-if="blockForm.blocked" class="flex flex-wrap gap-2"><select v-model="blockForm.kind" class="border rounded p-2"><option value="permanent">Бессрочно</option><option value="until">До указанной даты</option></select><input v-if="blockForm.kind === 'until'" v-model="blockForm.until" type="datetime-local" step="1" class="border rounded p-2" /></div>
							<p v-if="blockForm.blocked && blockForm.kind === 'until'" class="text-sm text-ink-gray-6">После этой даты блокировка завершится автоматически; остальные сроки и правила курса сохраняются.</p>
							<Button v-if="details.capabilities.write" :disabled="blockForm.blocked && blockForm.kind === 'until' && !blockForm.until" @click="saveCourseBlock">Сохранить блокировку курса</Button>
						</fieldset>
						<p v-if="!details.release_enabled || !details.policy_enabled" class="rounded bg-amber-50 p-3 text-amber-900">Индивидуальные сроки и расписание этого курса выключены. Персональные блокировки курса и уроков действуют независимо от расписания.</p>
						<p v-if="details.grants_truncated" role="alert">У ученика более 100 записей доступа к этому курсу. Для полного разбора нужна отдельная проверка.</p>
						<div v-if="!details.grants.length" class="space-y-2">
							<p>Ученик записан на курс; индивидуальная карточка доступа ещё не создана.</p>
							<Button v-if="details.capabilities.write && details.policy_exists" :loading="busy" @click="createAccess">Создать индивидуальные настройки</Button>
							<p v-else-if="!details.policy_exists">Сначала задайте общие правила доступа в настройках курса.</p>
						</div>
						<template v-else>
							<label v-if="details.grants.length > 1" class="block">Запись доступа
								<select v-model="selected" class="border rounded p-2 w-full" :disabled="busy"><option v-for="grant in details.grants" :key="grant.name" :value="grant.name">{{ statusLabel(grant.status) }} · {{ grant.starts_at || grant.creation }}</option></select>
							</label>
							<p v-if="activeGrantCount > 1" class="text-amber-800">Есть несколько незакрытых доступов. Изменение одной записи не закрывает доступ через остальные.</p>
							<template v-if="current">
								<div class="rounded border p-3 space-y-1">
									<div class="font-semibold">{{ statusLabel(current.status) }}</div>
									<div>Источник: {{ current.source?.label || 'Способ выдачи не записан' }}</div>
									<div v-if="current.source?.issued_at">Выдан: {{ current.source.issued_at }} <span v-if="current.source.actor">· {{ current.source.actor }}</span></div>
									<div v-else class="text-sm text-ink-gray-6">Дата и сотрудник первоначальной выдачи не записаны.</div>
									<div v-if="current.source?.snapshot_at" class="text-sm text-ink-gray-6">Снимок АВО: {{ current.source.snapshot_at }}</div>
								</div>
								<fieldset :disabled="busy || !details.capabilities.write || current.status === 'Revoked'" class="rounded border p-3 space-y-3">
									<legend class="font-semibold">Сроки курса · {{ details.timezone }}</legend>
									<div class="grid gap-3 sm:grid-cols-2">
										<label>Открытие доступа<input v-model="timing.starts_at" type="datetime-local" step="1" class="block border rounded p-2 w-full" /></label>
										<label>Окончание доступа<select v-model="timing.personal_end_type" class="block border rounded p-2 w-full"><option value="Inherit">Как у курса</option><option value="Unlimited">Бессрочно</option><option value="At">Указанная дата</option><option value="After Start">Количество дней</option><option value="Unknown">Не задано</option></select></label>
										<label v-if="timing.personal_end_type === 'At'">Дата окончания<input v-model="timing.ends_at" type="datetime-local" step="1" class="block border rounded p-2 w-full" /></label>
										<label v-if="timing.personal_end_type === 'After Start'">Дней от начала<input v-model.number="timing.personal_end_days" type="number" min="1" class="block border rounded p-2 w-full" /></label>
									</div>
									<label class="flex gap-2"><input v-model="timing.ignore_course_end" type="checkbox" /> Не учитывать общее окончание курса</label>
									<Button v-if="details.capabilities.write" :disabled="!timing.starts_at" @click="saveTiming">Сохранить сроки</Button>
								</fieldset>
								<div class="flex flex-wrap gap-2 items-center">
									<Button v-if="details.capabilities.write && current.status === 'Active'" :disabled="busy" @click="freeze">Заморозить этот доступ</Button>
									<template v-if="details.capabilities.write && current.status === 'Frozen'">
										<span class="text-sm">Заморозка действует до ручного возобновления.</span>
										<select v-model="extendEnd" class="border rounded p-2" :disabled="busy"><option value="">Срок после заморозки</option><option value="0">Не продлевать</option><option value="1">Продлить на время заморозки</option></select>
										<Button :disabled="busy || !extendEnd" @click="resume">Возобновить</Button>
									</template>
									<Button v-if="details.capabilities.remove && ['Active','Frozen','Limited'].includes(current.status)" :disabled="busy" @click="revoke">Закрыть этот доступ навсегда</Button>
								</div>
                                <section class="space-y-3 rounded border p-3">
                                    <div class="flex flex-wrap items-center justify-between gap-2">
                                        <h4 class="font-semibold">{{ lessonMode === 'assigned' ? 'Уроки ученика' : 'Добавить уроки' }}</h4>
                                        <Button v-if="lessonMode === 'assigned' && canEditLessons" :disabled="busy || lessonsLoading" @click="showLessonMode('available')">Добавить урок</Button>
                                        <Button v-if="lessonMode === 'available'" :disabled="busy || lessonsLoading" @click="showLessonMode('assigned')">К урокам ученика</Button>
                                    </div>
                                    <p class="text-sm text-ink-gray-6">{{ lessonMode === 'assigned' ? 'Здесь показаны уроки, добавленные ученику, включая ожидающие расписания.' : 'Здесь показаны уроки курса, которые ещё не добавлены в эту запись доступа.' }} Изменение списка сохраняет прогресс и домашние задания.</p>
                                    <p class="text-sm text-ink-gray-6">Посещение означает открытие страницы учеником, а не просмотр всего видео. Служебные входы не учитываются. Время указано для {{ details.timezone }}.</p>
                                    <div v-if="canEditLessons" class="flex flex-wrap items-center gap-3">
                                        <label class="flex items-center gap-2"><input data-testid="select-lesson-page" type="checkbox" :disabled="busy || lessonsLoading || lessonsError || !lessonRows.length" :checked="allPageSelected" @change="selectPage(($event.target as HTMLInputElement).checked)" /> Выбрать все на странице</label>
                                        <span>Выбрано: {{ selectedLessons.length }}</span>
                                        <Button :disabled="busy || lessonsLoading || lessonsError || !selectedLessons.length" @click="changeSelected(lessonMode === 'available')">{{ lessonMode === 'available' ? 'Добавить выбранные' : 'Удалить выбранные' }}</Button>
                                    </div>
                                    <p v-if="lessonsLoading" role="status">Загрузка уроков…</p>
                                    <div v-else-if="lessonsError" role="alert">Не удалось загрузить уроки. <Button :disabled="busy" @click="loadLessons">Повторить</Button></div>
                                    <p v-else-if="!lessonRows.length">{{ lessonMode === 'assigned' ? 'Ученику пока не добавлены уроки этой записи доступа.' : 'Все уроки курса уже добавлены.' }}</p>
                                    <div v-else class="overflow-x-auto">
                                        <table class="w-full text-left text-sm">
                                            <thead><tr class="border-b">
                                                <th v-if="canEditLessons" class="p-2"><span class="sr-only">Выбор урока</span></th>
                                                <th class="p-2">Урок</th>
                                                <th class="p-2">Доступен к просмотру</th>
                                                <th class="p-2">Открытие по расписанию</th>
                                                <th class="p-2">Первое посещение учеником</th>
                                                <th class="p-2">Последнее посещение учеником</th>
                                                <th class="p-2">Прохождение</th>
                                                <th v-if="details.capabilities.write" class="p-2">Действия</th>
                                            </tr></thead>
                                            <tbody>
                                                <tr v-for="row in lessonRows" :key="row.lesson" class="border-b align-top" data-testid="personal-lesson">
                                                    <td v-if="canEditLessons" class="p-2"><input type="checkbox" :aria-label="'Выбрать урок ' + (row.title || row.lesson)" :disabled="busy || lessonsLoading" :checked="selectedLessons.includes(row.lesson)" @change="toggleSelection(row.lesson, ($event.target as HTMLInputElement).checked)" /></td>
                                                    <td class="min-w-48 p-2">{{ row.title || row.lesson }}</td>
                                                    <td class="min-w-40 p-2">
                                                        <label class="flex items-center gap-2"><input type="checkbox" disabled :checked="row.effective_available === true" :aria-label="'Урок доступен: ' + (row.title || row.lesson)" />{{ row.effective_available === true ? 'Доступен' : row.effective_available === false ? 'Недоступен' : 'Нет данных' }}</label>
                                                        <p v-if="row.access_reason" class="mt-1 text-ink-gray-6">{{ row.access_reason }}</p>
                                                        <p v-if="row.manual_open" class="mt-1 text-ink-gray-6">Открыт досрочно</p>
                                                    </td>
                                                    <td class="min-w-36 p-2">{{ row.opens_at_effective ? formatDate(row.opens_at_effective) : 'Не определено' }}</td>
                                                    <td class="min-w-36 p-2" data-testid="first-visit">{{ row.first_learner_visit_at ? formatDate(row.first_learner_visit_at) : 'Нет подтверждённых данных' }}</td>
                                                    <td class="min-w-36 p-2" data-testid="last-visit">{{ row.last_learner_visit_at ? formatDate(row.last_learner_visit_at) : 'Нет подтверждённых данных' }}</td>
                                                    <td class="min-w-28 p-2">{{ completionLabel(row.completion_status) }}</td>
                                                    <td v-if="details.capabilities.write" class="min-w-48 space-y-2 p-2">
                                                        <Button v-if="row.assignment && current.status !== 'Revoked' && (row.manual_open || row.effective_available !== true)" :disabled="busy || lessonsLoading || (!row.manual_open && (!!courseBlock || row.blocked))" @click="setManual(row)">{{ row.manual_open ? 'Вернуть расписание' : 'Открыть досрочно' }}</Button>
                                                        <details v-if="row.assignment && canEditLessons" class="space-y-2">
                                                            <summary class="cursor-pointer">Индивидуальное правило</summary>
                                                            <fieldset :disabled="busy" class="space-y-2">
                                                                <select v-model="row.opening_type" class="w-full rounded border p-2"><option value="Inherit">Как у курса</option><option value="At">Указанная дата</option><option value="After Start">Дней после начала</option><option value="Unknown">Не задано</option></select>
                                                                <input v-if="row.opening_type === 'At'" v-model="row.opens_at" type="datetime-local" step="1" class="w-full rounded border p-2" />
                                                                <input v-if="row.opening_type === 'After Start'" v-model.number="row.delay_days" type="number" min="0" class="w-full rounded border p-2" />
                                                                <select v-model="row.prerequisite_state" class="w-full rounded border p-2"><option value="Inherit">Условия курса</option><option value="Satisfied">Условие выполнено</option><option value="Blocked">Заблокировать урок</option><option value="Unknown">Не задано</option></select>
                                                                <Button @click="saveRule(row)">Сохранить правило</Button>
                                                            </fieldset>
                                                        </details>
                                                        <details v-if="row.assignment" class="space-y-2">
                                                            <summary class="cursor-pointer">Блокировка урока</summary>
                                                            <fieldset :disabled="busy" class="space-y-2">
                                                                <p v-if="row.blocked" class="text-red-700">Урок закрыт {{ row.blocked_until ? 'до ' + formatDate(row.blocked_until) : 'бессрочно' }}</p>
                                                                <select v-model="row.block_kind" class="w-full rounded border p-1"><option value="permanent">Закрыть бессрочно</option><option value="until">Закрыть до даты</option></select>
                                                                <input v-if="row.block_kind === 'until'" v-model="row.block_end" type="datetime-local" step="1" class="w-full rounded border p-1" />
                                                                <Button :disabled="row.block_kind === 'until' && !row.block_end" @click="setLessonBlock(row, true)">Закрыть урок</Button>
                                                                <Button v-if="row.blocked" @click="setLessonBlock(row, false)">Снять блокировку</Button>
                                                            </fieldset>
                                                        </details>
                                                    </td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                    <div class="flex items-center justify-between gap-2"><Button :disabled="busy || lessonsLoading || lessonPage <= 1" @click="lessonPage--">Назад</Button><span class="text-sm">Страница {{ lessonPage }} из {{ lessonPages }} · {{ lessonTotal }} уроков</span><Button :disabled="busy || lessonsLoading || lessonPage >= lessonPages" @click="lessonPage++">Далее</Button></div>
                                </section>
							</template>
						</template>
					</template>
				</template>
			</div>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { Button, Dialog, call, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps<{ open: boolean; course: string; member?: string; contact?: string; enrollment?: string }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; saved: [] }>()
const details = ref<any>(null), selected = ref(''), loading = ref(false), error = ref(false), busy = ref(false)
const lessonRows = ref<any[]>([]), lessonTotal = ref(0), lessonPage = ref(1), lessonsLoading = ref(false), lessonsError = ref(false)
const selectedLessons = ref<string[]>([])
const lessonMode = ref<'assigned' | 'available'>('assigned')
const extendEnd=ref('')
const blockForm=reactive({blocked:false,kind:'permanent',until:''})
const courseBlock=computed(()=>details.value?.blocks?.find((b:any)=>!b.lesson && b.effective))
const timing=reactive({ starts_at:'',personal_end_type:'Inherit',ends_at:'',personal_end_days:0,ignore_course_end:false })
const current = computed(() => details.value?.grants?.find((x:any)=>x.name===selected.value))
const canEditLessons = computed(() => !!details.value?.capabilities.write && ['Draft', 'Active', 'Frozen'].includes(current.value?.status))
const allPageSelected = computed(() => lessonRows.value.length > 0 && lessonRows.value.every(row => selectedLessons.value.includes(row.lesson)))
const lessonPages=computed(()=>Math.max(1,Math.ceil(lessonTotal.value/50)))
const activeGrantCount=computed(()=>details.value?.grants?.filter((g:any)=>g.status!=='Revoked').length||0)
const STATUS:Record<string,string>={Draft:'Черновик',Active:'Доступ активен',Frozen:'Заморожен',Limited:'Ограниченный доступ',Revoked:'Доступ закрыт'}
const statusLabel=(status:string)=>STATUS[status]||status
const identity=()=>({ course:props.course,member:props.member||undefined,contact:props.contact||undefined,enrollment:props.enrollment||undefined })
const pair=()=>({course:props.course,member:details.value?.member||props.member||undefined,enrollment:props.enrollment||(!details.value?.member?details.value?.enrollment?.name:undefined)})
let request=0, lessonRequest=0, identityVersion=0
const isCurrentIdentity=(version:number,grant?:string)=>props.open && version===identityVersion && (!grant || selected.value===grant)
async function load() {
	if(!props.open||!props.course)return
	const token=++request;loading.value=true;error.value=false
	try { const result=await call('lms.lms.course_people.get_member_access',identity());if(token!==request)return;details.value=result
		selected.value=result.grants?.some((g:any)=>g.name===selected.value)?selected.value:(result.grants?.[0]?.name||'')
		const block=result.blocks?.find((b:any)=>!b.lesson&&b.effective);Object.assign(blockForm,{blocked:!!block,kind:block?.blocked_until?'until':'permanent',until:block?.blocked_until?.replace(' ','T')||''})
	} catch {if(token===request)error.value=true}finally{if(token===request)loading.value=false}
}
async function loadLessons(){
	if(!props.open||!current.value)return
	const token=++lessonRequest;lessonsLoading.value=true;lessonsError.value=false
	try{const result=await call('lms.lms.course_people.list_member_lessons',{...pair(),grant:current.value.name,page:lessonPage.value,page_length:50,assignment_filter:lessonMode.value});if(token!==lessonRequest)return
		lessonRows.value=result.rows.map((r:any)=>{const block=details.value?.blocks?.find((b:any)=>b.lesson===r.lesson&&b.effective);return {...r,opening_type:r.opening_type||'Inherit',prerequisite_state:r.prerequisite_state==='Clear'?'Satisfied':r.prerequisite_state||'Inherit',opens_at:r.opens_at?.replace(' ','T')||'',delay_days:r.delay_days||0,blocked:!!block,blocked_until:block?.blocked_until,block_kind:block?.blocked_until?'until':'permanent',block_end:block?.blocked_until?.replace(' ','T')||''}});lessonTotal.value=result.total;if(lessonPage.value!==result.page)lessonPage.value=result.page
	}catch{if(token===lessonRequest)lessonsError.value=true}finally{if(token===lessonRequest)lessonsLoading.value=false}
}
async function action(kind:string,values:Record<string,unknown>={}){
    if(!current.value||busy.value)return
    const version=identityVersion, grant=current.value.name
    const args={...pair(),grant,action:kind,values}
    busy.value=true
    try{
        await call('lms.lms.course_people.change_member_access',args)
        if(!isCurrentIdentity(version,grant))return
        await load()
        if(!isCurrentIdentity(version,grant))return
        await loadLessons()
        if(!isCurrentIdentity(version,grant))return
        emit('saved');toast.success('Настройки доступа сохранены')
    } catch{if(isCurrentIdentity(version,grant))toast.error('Не удалось изменить доступ. Проверьте данные перед повторной попыткой.')}
    finally{busy.value=false}
}
function formatDate(value:string){
    const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)/.exec(value)
    return match ? `${match[3]}.${match[2]}.${match[1]} ${match[4]}` : value
}
function completionLabel(status?:string){
    return ({Complete:'Пройден', 'In Progress':'В процессе', 'Not Started':'Не пройден', Incomplete:'Не пройден'} as Record<string,string>)[status || ''] || 'Нет отметки о завершении'
}
function showLessonMode(mode:'assigned'|'available'){
    if(busy.value || lessonsLoading.value)return
    lessonMode.value=mode;lessonPage.value=1
}
function saveTiming(){return action('timing',{...timing,ends_at:timing.personal_end_type==='At'?timing.ends_at:null,personal_end_days:timing.personal_end_type==='After Start'?timing.personal_end_days:0,ignore_course_end:timing.ignore_course_end?1:0})}
function freeze(){if(window.confirm('Заморозить эту запись доступа до ручного возобновления?'))return action('freeze')}
function resume(){return action('resume',{extend_personal_end:extendEnd.value})}
function revoke(){if(window.confirm('Закрыть эту запись доступа? Другие записи доступа и результаты обучения сохранятся.'))return action('revoke')}
function setManual(row:any){return action('manual_open',{lesson:row.lesson,enabled:row.manual_open?0:1})}
function saveRule(row:any){return action('lesson_rule',{lesson:row.lesson,rule:{opening_type:row.opening_type,opens_at:row.opening_type==='At'?row.opens_at:null,delay_days:row.opening_type==='After Start'?row.delay_days:0,prerequisite_state:row.prerequisite_state}})}
function toggleSelection(lesson:string, checked:boolean){
    if(busy.value || lessonsLoading.value || !canEditLessons.value)return
    selectedLessons.value = checked ? [...new Set([...selectedLessons.value, lesson])] : selectedLessons.value.filter(x => x !== lesson)
}
function selectPage(checked:boolean){ for(const row of lessonRows.value) toggleSelection(row.lesson,checked) }
async function changeSelected(assigned:boolean){
    if(busy.value || lessonsLoading.value || lessonsError.value || !canEditLessons.value || !current.value || !selectedLessons.value.length)return
    const lessons = [...selectedLessons.value]
    const version=identityVersion, grantName=current.value.name
    if(!assigned && !window.confirm(`Удалить выбранные уроки из доступа (${lessons.length})? Прогресс и задания сохранятся.`))return
    busy.value=true
    try{await call('lms.lms.course_people.change_lesson_assignments',{...pair(),grant:grantName,lessons,assigned:assigned?1:0});if(!isCurrentIdentity(version,grantName))return;selectedLessons.value=[];await loadLessons();if(!isCurrentIdentity(version,grantName))return;emit('saved');toast.success('Список уроков сохранён')}
    catch{if(isCurrentIdentity(version,grantName))toast.error('Не удалось изменить список уроков.')}
    finally{busy.value=false}
}
async function createAccess(){
    if(busy.value)return
    const version=identityVersion, args=pair()
    busy.value=true
    try{
        await call('lms.lms.course_people.create_member_access',args)
        if(!isCurrentIdentity(version))return
        await load()
        if(isCurrentIdentity(version))emit('saved')
    } catch{if(isCurrentIdentity(version))toast.error('Не удалось создать индивидуальный доступ. Проверьте общие правила курса.')}
    finally{busy.value=false}
}
async function changeBlock(blocked:boolean,until:string|null,lesson:string|null=null){
    if(busy.value||!details.value)return
    const version=identityVersion
    const args={...pair(),blocked:blocked?1:0,until:blocked?until:null,lesson}
    busy.value=true
    try{
        await call('lms.lms.course_people.set_member_block',args)
        if(!isCurrentIdentity(version))return
        await load()
        if(!isCurrentIdentity(version))return
        await loadLessons()
        if(!isCurrentIdentity(version))return
        emit('saved');toast.success('Блокировка сохранена')
    } catch{if(isCurrentIdentity(version))toast.error('Не удалось сохранить блокировку. Проверьте дату и права доступа.')}
    finally{busy.value=false}
}
function saveCourseBlock(){return changeBlock(blockForm.blocked,blockForm.kind==='until'?blockForm.until:null)}
function setLessonBlock(row:any,blocked:boolean){return changeBlock(blocked,row.block_kind==='until'?row.block_end:null,row.lesson)}
watch(current,(grant)=>{if(!grant)return;Object.assign(timing,{starts_at:grant.starts_at?.replace(' ','T')||'',personal_end_type:grant.personal_end_type||'Inherit',ends_at:grant.ends_at?.replace(' ','T')||'',personal_end_days:grant.personal_end_days||0,ignore_course_end:!!grant.ignore_course_end});extendEnd.value=''})
watch(()=>current.value?.name,()=>{lessonPage.value=1})
watch([()=>current.value?.name,lessonMode,lessonPage],()=>{++lessonRequest;selectedLessons.value=[];lessonRows.value=[];lessonTotal.value=0;if(current.value)loadLessons()})
watch(()=>[props.open,props.course,props.member,props.contact,props.enrollment],()=>{++identityVersion;++request;++lessonRequest;details.value=null;selected.value='';lessonMode.value='assigned';lessonPage.value=1;selectedLessons.value=[];lessonRows.value=[];lessonTotal.value=0;lessonsLoading.value=false;lessonsError.value=false;if(props.open)load()},{immediate:true})
</script>
