import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {enableAutoUnmount,flushPromises,mount} from '@vue/test-utils'
enableAutoUnmount(afterEach)
const {callMock}=vi.hoisted(()=>({callMock:vi.fn()}))
vi.mock('frappe-ui',()=>({call:callMock}))
vi.mock('@/pages/Forms/MemberForm.vue',()=>({default:{props:['memberID'],template:'<div data-testid="member">{{ memberID }}</div>'}}))
import AvoContactById from '@/pages/Forms/AvoContactById.vue'
describe('contact numeric URL',()=>{
	beforeEach(()=>callMock.mockReset())
	it('opens either kind through the contact-read resolver without a credential gate',async()=>{
		callMock.mockResolvedValueOnce({kind:'User',name:'person@example.test'})
		const w=mount(AvoContactById,{props:{avoId:'123'}});await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.contact_workspace.resolve_source_id',{source_id:'123'})
		expect(w.get('[data-testid=member]').text()).toBe('person@example.test')
		callMock.mockResolvedValueOnce({kind:'Contact',name:'contact-one'})
		await w.setProps({avoId:'124'});await flushPromises()
		expect(w.get('[data-testid=member]').text()).toBe('avo-contact:contact-one')
	})
	it('fails closed for unknown or ambiguous identities',async()=>{
		callMock.mockRejectedValueOnce(new Error('ambiguous'))
		const w=mount(AvoContactById,{props:{avoId:'123'}});await flushPromises()
		expect(w.find('[data-testid=member]').exists()).toBe(false)
		expect(w.get('[role=alert]').text()).toContain('Не удалось открыть')
	})
	it('never replaces a newly selected contact with a stale resolver response',async()=>{
		let oldResolve:(v:any)=>void=()=>{}
		callMock.mockImplementationOnce(()=>new Promise(resolve=>{oldResolve=resolve}))
		const w=mount(AvoContactById,{props:{avoId:'123'}})
		callMock.mockResolvedValueOnce({kind:'Contact',name:'new-contact'})
		await w.setProps({avoId:'124'});await flushPromises()
		oldResolve({kind:'User',name:'old@example.test'});await flushPromises()
		expect(w.get('[data-testid=member]').text()).toBe('avo-contact:new-contact')
	})
})
