import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const { callMock, errorMock }=vi.hoisted(()=>({callMock:vi.fn(),errorMock:vi.fn()}))
vi.mock('frappe-ui',()=>({
	call:callMock,toast:{success:vi.fn(),error:errorMock},
	createResource:()=>({data:{average_progress:0},reload:vi.fn()}),
	Button:{template:'<button><slot/></button>'},
	FormControl:{props:['modelValue'],emits:['update:modelValue'],template:'<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)" />'},
	ECharts:{template:'<div/>'},Tooltip:{template:'<span><slot/></span>'},
}))
vi.mock('@/utils',()=>({formatAmount:(x:any)=>String(x??0)}))
vi.mock('@/components/Controls/Select.vue',()=>({default:{template:'<div/>'}}))
vi.mock('@/components/NumberChartGraph.vue',()=>({default:{template:'<div/>'}}))
vi.mock('@/pages/Courses/StudentCourseProgress.vue',()=>({default:{template:'<div/>'}}))
vi.mock('@/components/PersonCourseAccessDialog.vue',()=>({default:{props:['open','course','member','enrollment'],template:'<div v-if="open" data-testid="dialog">{{enrollment}}</div>'}}))
import CourseDashboard from '@/pages/Courses/CourseDashboard.vue'
const caps={read:true,write:true,remove:true,contacts_read:true}
const rows=(page=1)=>Array.from({length:50},(_,n)=>({enrollment:'token-'+page+'-'+n,member:'user-'+page+'-'+n,full_name:'Student '+page+'-'+n,email:'real'+n+'@example.test',phone:'123',avo_id:String(n+1),progress:0,grant_count:1}))
const render=()=>mount(CourseDashboard,{props:{course:{data:{name:'course',enrollments:3001},reload:vi.fn()} as any},global:{provide:{$dayjs:(v:any)=>({format:()=>String(v)})},mocks:{__:(x:string)=>x},stubs:{RouterLink:{template:'<a><slot/></a>'}}}})
enableAutoUnmount(afterEach)
beforeEach(()=>{callMock.mockReset();errorMock.mockReset();callMock.mockImplementation(async(method:string,args:any)=>({rows:rows(args.page),total:3001,page:args.page,page_length:args.page_length,capabilities:{...caps}}))})
describe('bounded course learner table',()=>{
	it('requests fifty rows and displays the real total',async()=>{const w=render();await flushPromises();expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.list_students',expect.objectContaining({page:1,page_length:50}));expect(w.findAll('[data-testid="course-student"]')).toHaveLength(50);expect(w.text()).toContain('3001');expect(w.text()).not.toContain('Load More')})
	it('replaces rows when moving to another page',async()=>{const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='Далее')!.trigger('click');await flushPromises();expect(w.findAll('[data-testid="course-student"]')).toHaveLength(50);expect(w.text()).toContain('Student 2-0');expect(w.text()).not.toContain('Student 1-0');expect(callMock.mock.calls.at(-1)?.[1].page).toBe(2)})
	it('sorts the whole query and toggles direction on the same header',async()=>{const w=render();await flushPromises();const th=w.findAll('th').find(t=>t.text().includes('Зачисление'))!;await th.get('button').trigger('click');await flushPromises();expect(callMock.mock.calls.at(-1)?.[1]).toMatchObject({sort_by:'enrolled_at',sort_dir:'desc',page:1});await th.get('button').trigger('click');await flushPromises();expect(callMock.mock.calls.at(-1)?.[1].sort_dir).toBe('asc')})
	it('changing page size resets page and replaces the request',async()=>{const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='Далее')!.trigger('click');await flushPromises();await w.get('select').setValue('100');await flushPromises();expect(callMock.mock.calls.at(-1)?.[1]).toMatchObject({page:1,page_length:100})})
	it('keeps hidden contact identifiers out of links and uses opaque enrollment for the pencil',async()=>{callMock.mockResolvedValue({rows:[{enrollment:'opaque',member:null,full_name:'Ученик 1',progress:0}],total:1,page:1,page_length:50,capabilities:{...caps,contacts_read:false}});const w=render();await flushPromises();expect(w.find('a').exists()).toBe(false);expect(w.findAll('th').map(x=>x.text())).not.toContain('Почта');await w.get('[aria-label="Индивидуальный доступ"]').trigger('click');expect(w.get('[data-testid="dialog"]').text()).toBe('opaque')})
	it('refreshes the exact course after successful enrollment notification',async()=>{const w=render();await flushPromises();const before=callMock.mock.calls.length;window.dispatchEvent(new CustomEvent('course-people-changed',{detail:{course:'other'}}));await flushPromises();expect(callMock.mock.calls.length).toBe(before);window.dispatchEvent(new CustomEvent('course-people-changed',{detail:{course:'course'}}));await flushPromises();expect(callMock.mock.calls.length).toBe(before+1);w.unmount();window.dispatchEvent(new CustomEvent('course-people-changed',{detail:{course:'course'}}));await flushPromises();expect(callMock.mock.calls.length).toBe(before+1)})
})
