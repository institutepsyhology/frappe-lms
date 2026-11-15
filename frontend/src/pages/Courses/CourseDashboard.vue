<template>
	<div class="p-5">
		<div
			class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-5 text-ink-gray-9"
		>
			<NumberChartGraph
				:title="__('Enrolled')"
				:value="formatAmount(course.data?.enrollments)"
			/>
			<NumberChartGraph
				:title="__('Average Completion Rate')"
				:value="averageCompletionRate"
			/>
			<NumberChartGraph
				:title="__('Average Rating')"
				:value="course.data?.rating || 0"
			>
				<template #prefix>
					<LucideStar class="size-5 text-transparent fill-amber-500" />
				</template>
			</NumberChartGraph>
			<NumberChartGraph :title="__('Lessons')" :value="course.data?.lessons" />
		</div>
		<div
			v-if="showStudentsEmptyState"
			class="flex min-h-[30vh] sm:min-h-[70vh] flex-col items-center justify-center gap-3 px-4 text-center"
		>
			<span class="lucide-users size-7.5 text-ink-gray-5" />
			<div class="flex flex-col items-center gap-1">
				<span class="text-lg-medium text-ink-gray-8">
					{{ __('No students enrolled yet') }}
				</span>
				<span class="text-p-base text-ink-gray-6">
					{{ __('Enroll students to track their progress here') }}
				</span>
			</div>
		</div>
		<div
			v-else
			class="space-y-5"
		>
			<section class="border rounded-lg p-4 space-y-3" aria-label="Ученики курса">
				<div class="flex flex-wrap justify-between gap-3 items-center">
					<h3 class="text-lg-semibold">Ученики · {{ studentTotal }}</h3>
					<FormControl v-model="searchFilter" :debounce="300" placeholder="ФИО, почта, телефон или ID" aria-label="Поиск учеников" type="text" />
				</div>
				<p v-if="studentsError" role="alert">Не удалось загрузить учеников. <Button @click="loadStudents">Повторить</Button></p>
				<div class="overflow-x-auto" :aria-busy="studentsLoading">
					<table class="w-full text-sm whitespace-nowrap" data-testid="course-students">
						<thead><tr class="border-b text-left"><th v-for="column in studentColumns" :key="column.key" class="p-2" :aria-sort="sortBy === column.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"><button type="button" @click="sortStudents(column.key)">{{ column.label }} <span v-if="sortBy === column.key" aria-hidden="true">{{ sortDir === 'asc' ? '↑' : '↓' }}</span></button></th><th class="p-2">Действия</th></tr></thead>
						<tbody><tr v-for="row in studentRows" :key="row.enrollment" class="border-b" data-testid="course-student">
							<td class="p-2"><RouterLink v-if="studentCapabilities.contacts_read && row.avo_id" :to="{name:'AvoContactById',params:{avoId:row.avo_id}}" class="underline">{{ row.full_name || 'Без имени' }}</RouterLink><span v-else>{{ row.full_name || 'Без имени' }}</span></td>
							<td v-if="studentCapabilities.contacts_read" class="p-2"><RouterLink v-if="row.email && row.avo_id" :to="{name:'AvoContactById',params:{avoId:row.avo_id}}" class="underline">{{ row.email }}</RouterLink><span v-else>{{ row.email || '—' }}</span></td>
							<td v-if="studentCapabilities.contacts_read" class="p-2">{{ row.phone || '—' }}</td>
							<td class="p-2">{{ formatDate(row.enrolled_at) }}</td><td class="p-2">{{ formatDate(row.starts_at) }}</td><td class="p-2">{{ row.grant_count > 1 ? 'Несколько доступов' : row.ends_at ? formatDate(row.ends_at) : row.grant_count ? 'По правилу доступа' : 'По правилам курса' }}</td>
							<td class="p-2">{{ Math.ceil(row.progress || 0) }}%</td>
							<td class="p-2"><div class="flex gap-2"><Button v-if="studentCapabilities.contacts_read && row.member" aria-label="Прогресс ученика" title="Прогресс ученика" @click="openProgress(row)"><span class="lucide-chart-no-axes-combined size-4" /></Button><Button v-if="studentCapabilities.write" aria-label="Индивидуальный доступ" title="Индивидуальный доступ" @click="openAccess(row)"><span class="lucide-pencil size-4" /></Button><Button v-if="studentCapabilities.remove" aria-label="Удалить из курса" title="Удалить из курса" :disabled="removing" @click="removeStudent(row)"><span class="lucide-x size-4" /></Button></div></td>
						</tr></tbody>
					</table>
					<p v-if="studentsLoading" class="p-3">Загрузка учеников…</p><p v-else-if="!studentRows.length && !studentsError" class="p-3">Нет учеников, соответствующих поиску.</p>
				</div>
				<div class="flex flex-wrap justify-between gap-3 items-center"><label class="text-sm">На странице <select v-model.number="pageLength" class="border rounded p-1"><option v-for="size in [25,50,100,200]" :key="size" :value="size">{{ size }}</option></select></label><div class="flex items-center gap-3"><Button :disabled="studentsLoading || page <= 1" @click="page--">Назад</Button><span class="text-sm">{{ page }} / {{ studentPages }}</span><Button :disabled="studentsLoading || page >= studentPages" @click="page++">Далее</Button></div></div>
			</section>
			<div class="space-y-5">
				<div
					v-if="chartDetails.data?.average_progress > 0"
					class="border rounded-lg p-4"
				>
					<div class="text-ink-gray-5 mb-4">
						{{ __('Progress Summary') }}
					</div>
					<div
						class="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-4 items-center justify-between text-ink-gray-9"
					>
						<ul class="flex flex-col space-y-4 flex-1 text-sm list-none">
							<li
								class="flex items-center text-ink-gray-7"
								v-for="row in chartDetails.data?.progress_distribution"
								:key="row.name"
							>
								<div
									class="size-2 rounded"
									:style="{
										backgroundColor: `var(--${
											row.name.startsWith('Just')
												? 'red'
												: row.name.startsWith('In')
												? 'amber'
												: row.name.startsWith('Adv')
												? 'blue'
												: 'green'
										}-400)`,
									}"
								></div>
								<Tooltip :text="row.name.split('(')[1].replace(')', '')">
									<div class="ms-2">
										{{ row.name.split('(')[0] }}
									</div>
								</Tooltip>
								<Tooltip :text="String(row.value)">
									<div class="ms-auto">
										{{
											course.data?.enrollments
												? Math.round(
														(row.value / course.data.enrollments) * 100
												  )
												: 0
										}}%
									</div>
								</Tooltip>
							</li>
						</ul>
						<ECharts
							class="w-40 h-20"
							:options="{
								color: progressColors,
								series: [
									{
										type: 'pie',
										radius: ['50%', '70%'],
										center: ['50%', '50%'],
										label: {
											show: false,
										},
										labelLine: {
											show: false,
										},
										emphasis: {
											label: {
												show: false,
											},
											scale: false,
										},
										legend: {
											show: false,
										},
										data: chartDetails.data?.progress_distribution || [],
									},
								],
								showInlineLabels: false,
							}"
						/>
					</div>
				</div>
				<div
					v-if="lessonProgress.data?.length"
					class="border rounded-lg pt-4 px-4"
				>
					<div class="flex items-center justify-between mb-4">
						<div class="text-ink-gray-5">
							{{ __('Lesson Completion') }}
						</div>
						<Select
							:options="lessonProgressSortingOptions"
							@update:modelValue="
								(value: string) => updateLessonProgress(value)
							"
							:placeholder="__('Sort by')"
							class="!w-32"
						/>
					</div>
					<ul
						class="divide-y sm:max-h-[40vh] divide-outline-elevation-2 text-ink-gray-7 sm:overflow-y-auto list-none"
					>
						<li
							v-for="progress in lessonProgress.data"
							:key="`${progress.chapter_idx}-${progress.idx}`"
							class="flex justify-between text-sm py-2 my-1 text-ink-gray-9"
						>
							<div class="">
								<span class="me-3 text-xs">
									{{ progress.chapter_idx }}.{{ progress.idx }}
								</span>
								<span>
									{{ progress.title }}
								</span>
							</div>
							<Tooltip :text="String(progress.completion_count)">
								<div>
									{{
										course.data?.enrollments
											? Math.ceil(
													(progress.completion_count /
														course.data.enrollments) *
														100
											  )
											: 0
									}}%
								</div>
							</Tooltip>
						</li>
					</ul>
				</div>
			</div>
		</div>
	</div>
	<PersonCourseAccessDialog v-model:open="showAccess" :course="course.data?.name || ''" :member="accessMember" :enrollment="accessEnrollment" @saved="accessSaved" />
	<StudentCourseProgress
		v-if="showProgressModal"
		v-model="showProgressModal"
		:course="course"
		:student="currentStudent"
		:lessons="lessonProgress"
	/>
</template>
<script setup lang="ts">
import {
	Button,
	call,
	toast,
	createResource,
	ECharts,
	FormControl,
	Tooltip,
} from 'frappe-ui'
import Select from '@/components/Controls/Select.vue'
import { computed, inject, ref, watch, onMounted, onUnmounted } from 'vue'
import type dayjsType from 'dayjs'
import { formatAmount } from '@/utils'
import NumberChartGraph from '@/components/NumberChartGraph.vue'
import PersonCourseAccessDialog from '@/components/PersonCourseAccessDialog.vue'
import StudentCourseProgress from '@/pages/Courses/StudentCourseProgress.vue'

import type {
	CourseDetails,
	Resource,
} from '@/types'

const props = defineProps<{
	course: Resource<CourseDetails | null>
}>()

const dayjs = inject<typeof dayjsType>('$dayjs')!
const searchFilter = ref<string | null>(null)

const showProgressModal = ref<boolean>(false)
const currentStudent = ref<Record<string, unknown> | null>(null)
const chartDetails = createResource({
	url: 'lms.lms.api.get_course_progress_distribution',
	makeParams() {
		return {
			course: props.course.data?.name,
		}
	},
	auto: true,
})

const studentRows=ref<any[]>([]),studentTotal=ref(0),studentsLoading=ref(false),studentsError=ref(false)
const studentCapabilities=ref({read:false,write:false,remove:false,contacts_read:false})
const page=ref(1),pageLength=ref(50),sortBy=ref('starts_at'),sortDir=ref<'asc'|'desc'>('desc')
const showAccess=ref(false),accessMember=ref<string|undefined>(),accessEnrollment=ref<string|undefined>(),removing=ref(false)
const studentPages=computed(()=>Math.max(1,Math.ceil(studentTotal.value/pageLength.value)))
const studentColumns=computed(()=>[
 {key:'full_name',label:'ФИО'},
 ...(studentCapabilities.value.contacts_read?[{key:'email',label:'Почта'},{key:'phone',label:'Телефон'}]:[]),
 {key:'enrolled_at',label:'Зачисление'},{key:'starts_at',label:'Открытие доступа'},{key:'ends_at',label:'Окончание доступа'},{key:'progress',label:'Прогресс'},
])
let studentRequest=0
async function loadStudents(){
 const courseName=props.course.data?.name;if(!courseName)return
 const token=++studentRequest;studentsLoading.value=true;studentsError.value=false
 try{const result=await call('lms.lms.course_people.list_students',{course:courseName,page:page.value,page_length:pageLength.value,sort_by:sortBy.value,sort_dir:sortDir.value,search:searchFilter.value||null});if(token!==studentRequest)return
  studentRows.value=result.rows;studentTotal.value=result.total;studentCapabilities.value=result.capabilities
  if(page.value!==result.page)page.value=result.page
 }catch{if(token===studentRequest){studentsError.value=true;studentRows.value=[]}}
 finally{if(token===studentRequest)studentsLoading.value=false}
}
function sortStudents(key:string){if(sortBy.value===key)sortDir.value=sortDir.value==='asc'?'desc':'asc';else{sortBy.value=key;sortDir.value='desc'}}
function openProgress(row:any){currentStudent.value={...row,member_name:row.full_name,member_image:null};showProgressModal.value=true}
function openAccess(row:any){accessMember.value=row.member||undefined;accessEnrollment.value=row.enrollment;showAccess.value=true}
function formatDate(value:string|null){return value?dayjs(value).format('DD.MM.YYYY HH:mm'):'—'}
function accessSaved(){loadStudents();props.course.reload?.()}
async function removeStudent(row:any){
 if(removing.value||!window.confirm('Удалить ученика из этого курса и закрыть все его доступы к нему? Контакт, прогресс и домашние задания сохранятся.'))return
 removing.value=true
 try{await call('lms.lms.course_people.remove_student',{course:props.course.data?.name,enrollment:row.enrollment});await loadStudents();props.course.reload?.();toast.success('Ученик удалён из курса')}
 catch{toast.error('Не удалось удалить ученика из курса. Проверьте состояние перед повторной попыткой.');await loadStudents()}
 finally{removing.value=false}
}
function peopleChanged(event:Event){if((event as CustomEvent).detail?.course===props.course.data?.name)accessSaved()}
onMounted(()=>window.addEventListener('course-people-changed',peopleChanged))
onUnmounted(()=>{++studentRequest;window.removeEventListener('course-people-changed',peopleChanged)})
watch(()=>props.course.data?.name,()=>{++studentRequest;studentRows.value=[];studentTotal.value=0;if(page.value!==1)page.value=1;else loadStudents()},{immediate:true})
watch([searchFilter,pageLength,sortBy,sortDir],()=>{if(page.value!==1)page.value=1;else loadStudents()})
watch(page,loadStudents)

const lessonProgress = createResource({
	url: 'lms.lms.api.get_lesson_completion_stats',
	params: {
		course: props.course.data?.name,
	},
	auto: true,
})

const updateLessonProgress = (value: string) => {
	if (value == 'completion_rate') {
		lessonProgress.data?.sort((a: any, b: any) => {
			const rateA = a.completion_count / (props.course.data?.enrollments || 1)
			const rateB = b.completion_count / (props.course.data?.enrollments || 1)
			return rateB - rateA
		})
	} else if (value == 'index') {
		lessonProgress.data?.sort((a: any, b: any) => {
			return a.chapter_idx - b.chapter_idx || a.idx - b.idx
		})
	}
}

const averageCompletionRate = computed(() => {
	let value = Math.ceil(chartDetails.data?.average_progress) || 0
	return value + '%'
})

const showStudentsEmptyState = computed(
	() =>
		!studentsLoading.value && !studentRows.value.length && !searchFilter.value && !studentsError.value
)

const progressColors = computed(() =>
	['red', 'amber', 'blue', 'green'].map((color) => `var(--${color}-400)`)
)

const lessonProgressSortingOptions = [
	{
		label: __('Lesson Index'),
		value: 'index',
		onClick() {
			updateLessonProgress('index')
		},
	},
	{
		label: __('Completion Rate'),
		value: 'completion_rate',
		onClick() {
			updateLessonProgress('completion_rate')
		},
	},
]
</script>
