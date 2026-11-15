import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {enableAutoUnmount,flushPromises,mount} from '@vue/test-utils'
enableAutoUnmount(afterEach)
const {callMock,replaceMock}=vi.hoisted(()=>({callMock:vi.fn(),replaceMock:vi.fn()}))
vi.mock('frappe-ui',()=>({call:callMock,toast:{success:vi.fn(),error:vi.fn()},FormControl:{props:['modelValue','label'],emits:['update:modelValue'],template:'<label>{{ label }}<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)" /></label>'}}))
vi.mock('vue-router',()=>({useRouter:()=>({replace:replaceMock})}))
vi.mock('@/utils',()=>({cleanError:(s:string)=>s}))
vi.mock('@/composables/useFormRoute',()=>({useFormRoute:()=>({close:vi.fn()})}))
vi.mock('@/components/FormShell.vue',()=>({default:{props:['title'],template:'<div><h2>{{ title }}</h2><slot/><slot name="actions"/></div>'}}))
vi.mock('@/components/HeaderButton.vue',()=>({default:{props:['label'],emits:['click'],template:'<button @click="$emit(\'click\')">{{ label }}</button>'}}))
vi.mock('@/components/Settings/AvoContactCard.vue',()=>({default:{props:['kind','memberId'],template:'<div data-testid="card">{{ kind }}|{{ memberId }}</div>'}}))
import MemberForm from '@/pages/Forms/MemberForm.vue'
describe('contact form route',()=>{
	beforeEach(()=>{callMock.mockReset();replaceMock.mockReset();window.read_only_mode=false})
	it('opens a User or Contact with the same card and has no role controls',async()=>{
		const w=mount(MemberForm,{props:{memberID:'person@example.test'}});await flushPromises()
		expect(w.get('[data-testid=card]').text()).toBe('User|person@example.test')
		await w.setProps({memberID:'avo-contact:internal-contact'});await flushPromises()
		expect(w.get('[data-testid=card]').text()).toBe('Contact|internal-contact')
		expect(w.find('[data-testid=member-save]').exists()).toBe(false)
		expect(w.text()).not.toContain('Roles')
		expect(callMock).not.toHaveBeenCalled()
	})
	it('creates only a Contact from a social identity with no required email',async()=>{
		callMock.mockImplementation(async(url:string)=>url.endsWith('get_capabilities')?{create:true}:{kind:'Contact',name:'new-contact'})
		const w=mount(MemberForm,{props:{memberID:'new'}});await flushPromises()
		await w.findAll('label').find(l=>l.text()==='Telegram ID')!.find('input').setValue('123456')
		await w.get('[data-testid=contact-create]').trigger('click');await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.contact_workspace.create_contact',expect.objectContaining({values:expect.objectContaining({email:'',custom_avo_telegram_id:'123456'})}))
		expect(callMock.mock.calls.some(([url])=>url==='frappe.client.insert'||url.endsWith('save_role'))).toBe(false)
		expect(replaceMock).toHaveBeenCalledWith({name:'MemberForm',params:{memberID:'avo-contact:new-contact'}})
	})
	it('does not expose contact creation when the server denies it',async()=>{
		callMock.mockResolvedValue({create:false});const w=mount(MemberForm,{props:{memberID:'new'}});await flushPromises()
		expect(w.find('[data-testid=new-contact-fields]').exists()).toBe(false)
		expect(w.find('[data-testid=contact-create]').exists()).toBe(false)
		expect(w.text()).toContain('Нет права создавать контакты')
	})
})
