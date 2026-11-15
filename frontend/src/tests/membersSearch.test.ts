import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {enableAutoUnmount,flushPromises,mount} from '@vue/test-utils'
enableAutoUnmount(afterEach)
const {callMock,pending,routeMock}=vi.hoisted(()=>({callMock:vi.fn(),pending:[] as ((value:any)=>void)[],routeMock:vi.fn()}))
vi.mock('frappe-ui',()=>({call:callMock,Button:{props:['disabled'],emits:['click'],template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot/></button>'},FormControl:{props:['modelValue','label'],emits:['update:modelValue'],template:'<label>{{ label }}<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)" /></label>'}}))
vi.mock('vue-router',()=>({useRouter:()=>({})}))
vi.mock('@/composables/useFormRoute',()=>({openFormRoute:routeMock}))
import Members from '@/components/Settings/Members.vue'
const row=(id:string,kind='User')=>({kind,name:id+'@example.test',full_name:id,email:id+'@example.test',source_id:id,mobile_no:null})
async function land(rows:any[],total=120){pending.shift()?.({rows,total,can_create:true});await flushPromises()}
describe('unified contact list pagination and search',()=>{
	beforeEach(()=>{vi.useFakeTimers({toFake:['setTimeout','clearTimeout']});callMock.mockReset();pending.length=0;routeMock.mockClear();callMock.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)))})
	afterEach(()=>vi.useRealTimers())
	it('requests 50 contacts and replaces rows instead of appending a next page',async()=>{
		const w=mount(Members);expect(callMock).toHaveBeenCalledWith('lms.lms.contact_workspace.list_people',expect.objectContaining({page:1,page_size:50}))
		await land([row('41')]);await w.findAll('button').find(b=>b.text()==='Далее')!.trigger('click');await land([row('42')])
		expect(w.findAll('tbody tr')).toHaveLength(1);expect(w.text()).toContain('42@example.test');expect(w.text()).not.toContain('41@example.test')
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_people',expect.objectContaining({page:2,page_size:50}))
	})
	it('sends searches to the server and rejects stale responses',async()=>{
		const w=mount(Members);await w.find('input').setValue('new term');await vi.advanceTimersByTimeAsync(260)
		await land([row('old')]);expect(w.text()).not.toContain('old@example.test')
		await land([row('new')]);expect(w.text()).toContain('new@example.test')
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_people',expect.objectContaining({search:'new term',page:1}))
	})
	it('sorts emails in both directions and opens either record kind through its source ID',async()=>{
		const w=mount(Members);await land([row('42','Contact')])
		await w.findAll('th button').find(b=>b.text()==='Email')!.trigger('click');await land([row('42','Contact')])
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_people',expect.objectContaining({sort:'email',direction:'asc'}))
		await w.findAll('th button').find(b=>b.text().startsWith('Email'))!.trigger('click');await land([row('42','Contact')])
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_people',expect.objectContaining({sort:'email',direction:'desc'}))
		await w.findAll('tbody button')[0].trigger('click');expect(routeMock).toHaveBeenCalledWith(expect.anything(),{name:'AvoContactById',params:{avoId:'42'}})
		expect(w.text()).not.toContain('Roles');expect(w.text()).not.toContain('Delete user')
	})
})
