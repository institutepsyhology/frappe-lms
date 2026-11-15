<template>
	<section v-if="user?.data" class="border-t px-5 py-4 space-y-3">
		<h3 class="font-semibold">Общие правила доступа курса</h3>
		<p v-if="loading">Загрузка настроек доступа…</p>
		<p v-else-if="error" class="text-red-700">Не удалось загрузить настройки доступа.</p>
		<template v-else-if="overview">
			<p class="text-sm text-ink-gray-6">Личные сроки и уроки ученика открываются по карандашу в списке учеников или из карточки контакта.</p>
			<fieldset :disabled="busy || !overview.capabilities.write" class="space-y-3">
			<p v-if="!overview.release_enabled" class="text-amber-700">
				Правила пока выключены на сайте. Изменения карточек не влияют на доступ учеников.
			</p>
			<p v-else-if="!overview.policy_enabled" class="text-amber-700">
				Правила этого курса пока выключены.
			</p>
			<div v-if="overview.release_enabled && overview.policy_exists && !overview.policy_enabled" class="space-y-1">
				<p>Включение доступно для неопубликованного курса без учеников и с выключенной самостоятельной записью после заполнения сроков и расписания всех уроков.</p>
				<button class="underline" :disabled="busy" @click="enablePolicy">Включить правила для курса</button>
			</div>
			<div v-if="!overview.policy_exists" class="space-y-2">
				<p>Настройки доступа для курса ещё не созданы.</p>
				<button class="underline" :disabled="busy" @click="createPolicy">Создать настройки доступа</button>
			</div>
			<details v-if="overview.policy" class="border rounded p-3">
				<summary class="cursor-pointer">Общие сроки курса</summary>
				<div class="space-y-2 mt-3">
					<label class="block">Персональный срок по умолчанию
						<select v-model="defaults.default_personal_end_type" class="border rounded w-full p-1">
							<option value="Unknown">Не задан</option><option value="Unlimited">Без ограничения</option>
							<option value="After Start">Количество дней от начала</option><option value="At">До даты</option>
						</select>
					</label>
					<label v-if="defaults.default_personal_end_type === 'After Start'" class="block">Дней
						<input v-model.number="defaults.default_personal_end_days" type="number" min="1" class="border rounded w-full p-1" />
					</label>
					<label v-if="defaults.default_personal_end_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
						<input v-model="defaults.default_personal_end_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
					</label>
					<label class="block">Общее окончание курса
						<select v-model="defaults.global_end_type" class="border rounded w-full p-1">
							<option value="Unknown">Не задано</option><option value="Unlimited">Без ограничения</option><option value="At">До даты</option>
						</select>
					</label>
					<label v-if="defaults.global_end_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
						<input v-model="defaults.global_end_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
					</label>
					<label class="block">Доступ к завершённым урокам после окончания
						<select v-model="defaults.completed_retention_type" class="border rounded w-full p-1">
							<option value="None">Не сохранять</option><option value="Unlimited">Без ограничения</option><option value="Days">На количество дней</option>
						</select>
					</label>
					<label v-if="defaults.completed_retention_type === 'Days'" class="block">Дней
						<input v-model.number="defaults.completed_retention_days" type="number" min="1" class="border rounded w-full p-1" />
					</label>
					<label class="block">Доступ к ранее открытым урокам после окончания
						<select v-model="defaults.visited_retention_type" class="border rounded w-full p-1">
							<option value="None">Не сохранять</option><option value="Unlimited">Без ограничения</option><option value="Days">На количество дней</option>
						</select>
					</label>
					<label v-if="defaults.visited_retention_type === 'Days'" class="block">Дней
						<input v-model.number="defaults.visited_retention_days" type="number" min="1" class="border rounded w-full p-1" />
					</label>
					<p>Учитываются открытия, записанные после включения индивидуального доступа. Для предыдущих посещений нужна отдельная история.</p>
					<button class="underline" :disabled="busy" @click="saveDefaults">Сохранить общие сроки</button>
				</div>
			</details>
			<details v-if="overview.policy_exists" class="border rounded p-3">
				<summary class="cursor-pointer">Расписание отдельных уроков</summary>
				<div class="space-y-2 mt-3">
					<label class="block">Урок
						<select v-model="selectedLesson" class="border rounded w-full p-1">
							<option value="">Выберите урок</option>
							<option v-for="lesson in overview.lessons" :key="lesson.name" :value="lesson.name">{{ lesson.title || lesson.name }}</option>
						</select>
					</label>
					<template v-if="selectedLesson">
						<label class="block">Открыть урок
							<select v-model="lessonRule.opening_type" class="border rounded w-full p-1">
								<option value="Unknown">Не задано</option><option value="After Start">Через дни после начала курса</option><option value="At">В указанную дату</option>
							</select>
						</label>
						<label v-if="lessonRule.opening_type === 'After Start'" class="block">Дней после начала
							<input v-model.number="lessonRule.delay_days" type="number" min="0" class="border rounded w-full p-1" />
						</label>
						<label v-if="lessonRule.opening_type === 'At'" class="block">Дата и время ({{ overview.timezone }})
							<input v-model="lessonRule.opens_at" type="datetime-local" step="1" class="border rounded w-full p-1" />
						</label>
						<label class="block">Дополнительное условие
							<select v-model="lessonRule.prerequisite_type" class="border rounded w-full p-1">
								<option value="Unknown">Не задано</option><option value="None">Без условия</option>
								<option value="Lesson Complete">Завершён другой урок</option><option value="Assignment Submitted">Отправлено задание</option><option value="Assignment Passed">Задание принято</option>
							</select>
						</label>
						<label v-if="!['Unknown', 'None'].includes(lessonRule.prerequisite_type)" class="block">Урок с условием
							<select v-model="lessonRule.prerequisite_lesson" class="border rounded w-full p-1">
								<option :value="null">Выберите урок</option>
								<option v-for="lesson in overview.lessons.filter(item => item.name !== selectedLesson)" :key="lesson.name" :value="lesson.name">{{ lesson.title || lesson.name }}</option>
							</select>
						</label>
						<label v-if="['Assignment Submitted', 'Assignment Passed'].includes(lessonRule.prerequisite_type)" class="block">Задание в выбранном уроке
							<select v-model="lessonRule.prerequisite_assignment" class="border rounded w-full p-1" :disabled="assignmentsLoading">
								<option :value="null">Выберите задание</option>
								<option v-for="assignment in assignments" :key="assignment.name" :value="assignment.name">{{ assignment.title }}</option>
							</select>
							<span v-if="!assignmentsLoading && !assignments.length">В уроке нет доступных заданий.</span>
						</label>
						<button class="underline" :disabled="busy" @click="saveLessonRule">Сохранить правило урока</button>
					</template>
				</div>
			</details>
			</fieldset>
		</template>
	</section>
</template>
<script setup lang="ts">
import { call, toast } from 'frappe-ui'
import { inject, reactive, ref, watch } from 'vue'
import type { SessionUser } from '@/types'
const props = defineProps<{ course: string }>()
const user = inject<SessionUser>('$user')
const overview = ref<any>(null)
const loading = ref(false), error = ref(false), busy = ref(false)
const defaults = reactive<any>({ default_personal_end_type:'Unknown', default_personal_end_at:null, default_personal_end_days:0,
 global_end_type:'Unknown', global_end_at:null, completed_retention_type:'None', completed_retention_days:0,
 visited_retention_type:'None', visited_retention_days:0 })
const selectedLesson=ref(''), assignments=ref<any[]>([]), assignmentsLoading=ref(false)
const lessonRule=reactive<any>({opening_type:'Unknown',opens_at:null,delay_days:0,prerequisite_type:'Unknown',prerequisite_lesson:null,prerequisite_assignment:null})
let request=0
async function load() {
 if(!props.course || !user?.data) return
 const token=++request;loading.value=true;error.value=false
 try {
  const result=await call('lms.lms.course_people.get_course_defaults',{course:props.course})
  if(token!==request)return
  overview.value=result
  if(result.policy){Object.assign(defaults,result.policy);defaults.default_personal_end_at=defaults.default_personal_end_at?.replace(' ','T')||null;defaults.global_end_at=defaults.global_end_at?.replace(' ','T')||null}
 }catch{if(token===request)error.value=true}finally{if(token===request)loading.value=false}
}
async function change(method:string,args:Record<string,unknown>={}) {
 busy.value=true
 try{await call('lms.lms.access_actions.'+method,{course:props.course,...args});await load()}
 catch{toast.error('Не удалось сохранить настройки доступа.')}
 finally{busy.value=false}
}
function createPolicy(){return change('create_course_access_policy')}
function enablePolicy(){if(window.confirm('Включить правила доступа для курса без записанных учеников?'))return change('enable_empty_course_policy')}
function saveDefaults(){return change('update_course_access_defaults',{defaults:{
 default_personal_end_type:defaults.default_personal_end_type,default_personal_end_at:defaults.default_personal_end_type==='At'?defaults.default_personal_end_at:null,
 default_personal_end_days:defaults.default_personal_end_type==='After Start'?defaults.default_personal_end_days:0,
 global_end_type:defaults.global_end_type,global_end_at:defaults.global_end_type==='At'?defaults.global_end_at:null,
 completed_retention_type:defaults.completed_retention_type,completed_retention_days:defaults.completed_retention_type==='Days'?defaults.completed_retention_days:0,
 visited_retention_type:defaults.visited_retention_type,visited_retention_days:defaults.visited_retention_type==='Days'?defaults.visited_retention_days:0}})}
watch(selectedLesson,name=>{const rule=overview.value?.schedule?.find((x:any)=>x.lesson===name);Object.assign(lessonRule,{opening_type:'Unknown',opens_at:null,delay_days:0,prerequisite_type:'Unknown',prerequisite_lesson:null,prerequisite_assignment:null},rule||{});lessonRule.opens_at=lessonRule.opens_at?.replace(' ','T')||null})
let assignmentRequest=0
watch(()=>[lessonRule.prerequisite_lesson,lessonRule.prerequisite_type],async([lesson,kind])=>{
 const token=++assignmentRequest;assignments.value=[]
 if(!lesson||!['Assignment Submitted','Assignment Passed'].includes(kind)){assignmentsLoading.value=false;return}
 assignmentsLoading.value=true
 try{const result=await call('lms.lms.access_actions.get_lesson_assignments',{course:props.course,lesson});if(token!==assignmentRequest)return;assignments.value=result;if(!result.some((x:any)=>x.name===lessonRule.prerequisite_assignment))lessonRule.prerequisite_assignment=null}
 catch{if(token===assignmentRequest)toast.error('Не удалось загрузить задания урока.')}
 finally{if(token===assignmentRequest)assignmentsLoading.value=false}
})
function saveLessonRule(){if(!selectedLesson.value)return;return change('update_course_lesson_rule',{lesson:selectedLesson.value,rule:{opening_type:lessonRule.opening_type,opens_at:lessonRule.opening_type==='At'?lessonRule.opens_at:null,delay_days:lessonRule.opening_type==='After Start'?lessonRule.delay_days:0,prerequisite_type:lessonRule.prerequisite_type,prerequisite_lesson:['Unknown','None'].includes(lessonRule.prerequisite_type)?null:lessonRule.prerequisite_lesson,prerequisite_assignment:['Assignment Submitted','Assignment Passed'].includes(lessonRule.prerequisite_type)?lessonRule.prerequisite_assignment:null}})}
watch(()=>props.course,()=>{overview.value=null;selectedLesson.value='';load()},{immediate:true})
</script>
