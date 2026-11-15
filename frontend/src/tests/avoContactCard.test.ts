import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
enableAutoUnmount(afterEach)

const { callMock, toastMock } = vi.hoisted(() => ({callMock:vi.fn(),toastMock:{success:vi.fn(),error:vi.fn()}}))
vi.mock('frappe-ui',()=>({call:callMock,toast:toastMock,
	Button:{props:['disabled'],emits:['click'],template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>'},
	FormControl:{props:['modelValue','label','disabled'],emits:['update:modelValue'],template:'<label>{{ label }}<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\',$event.target.value)" /></label>'},
}))
vi.mock('@/components/PersonCourseAccessDialog.vue',()=>({default:{name:'PersonCourseAccessDialog',props:['open','course','member','contact'],template:'<div v-if="open" data-testid="access-dialog">{{ course }}|{{ member }}|{{ contact }}</div>'}}))
import Card from '@/components/Settings/AvoContactCard.vue'

let caps:Record<string,boolean>, kind:'User'|'Contact'
const course={course:'course-one',title:'Course One',starts_at:'2026-01-01',ends_at:null,end_unknown:false,status:'Active',archive_only:false,source_label:'Способ выдачи не записан',source_actor:null,source_event_at:null,imported_at:null,imported_by:null}
const make=()=>mount(Card,{props:{memberId:kind==='User'?'member@example.test':'contact-42',kind}})
const button=(wrapper:ReturnType<typeof mount>,text:string)=>wrapper.findAll('button').find(b=>b.text()===text)!
describe('unified contact card',()=>{
	beforeEach(()=>{
		kind='User';caps={read:true,write:true,credential_read:false,credential_write:false,credential_send:false}
		callMock.mockReset();window.read_only_mode=false
		callMock.mockImplementation(async(url:string,args:any)=>{
			if(url.endsWith('get_card')||url.endsWith('save_card'))return {kind,name:kind==='User'?'member@example.test':'contact-42',email:kind==='User'?'member@example.test':null,custom_avo_contact_id:'42',custom_avo_account:'mv-centr',capabilities:{...caps}}
			if(url.endsWith('list_person_courses'))return {rows:[course],total:76,page:args.page,page_size:args.page_size}
			if(url.endsWith('reveal'))return {password:'synthetic-test-secret'}
			return {queued:true}
		})
	})
	it('uses the same profile and paged course section for a no-login contact',async()=>{
		kind='Contact';const w=make();await flushPromises()
		expect(w.text()).toContain('Контакт без связанной учётной записи')
		expect(w.text()).toContain('Курсы контакта')
		expect(callMock).toHaveBeenCalledWith('lms.lms.contact_workspace.list_person_courses',expect.objectContaining({kind:'Contact',name:'contact-42',page:1,page_size:50}))
		expect(callMock.mock.calls.some(([url])=>url.endsWith('reveal'))).toBe(false)
	})
	it('saves basic data and opt-out without a password permission or any role mutation',async()=>{
		const w=make();await flushPromises();await w.find('input[type=checkbox]').setValue(true)
		await button(w,'Сохранить данные').trigger('click');await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.contact_workspace.save_card',expect.objectContaining({values:expect.objectContaining({custom_no_marketing_email:true})}))
		expect(callMock.mock.calls.some(([url])=>url.endsWith('save_role'))).toBe(false)
		expect(w.text()).not.toContain('Модератор')
	})
	it('disables data mutation for read-only card access',async()=>{
		caps.write=false;const w=make();await flushPromises()
		expect(w.findAll('input').every(input=>input.attributes('disabled')!==undefined)).toBe(true)
		expect(w.text()).not.toContain('Сохранить данные')
		expect(callMock.mock.calls.some(([url])=>url.endsWith('reveal'))).toBe(false)
	})
	it('separates credential read from write and sending',async()=>{
		caps.credential_read=true;const w=make();await flushPromises()
		expect(w.get('[data-testid=revealed-password]').text()).toBe('synthetic-test-secret')
		expect(w.text()).toContain('Показать пароль')
		expect(w.text()).not.toContain('Отправить пароль на почту')
		expect(w.text()).not.toContain('Установить новый пароль')
		expect(w.text()).not.toContain('Отправить ссылку для смены пароля')
	})
	it('loads only the selected course page and opens the shared person-course dialog',async()=>{
		const w=make();await flushPromises();await button(w,'Далее').trigger('click');await flushPromises()
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_person_courses',expect.objectContaining({page:2,page_size:50}))
		expect(w.findAll('tbody tr')).toHaveLength(1)
		await button(w,'Course One').trigger('click');await flushPromises()
		expect(w.get('[data-testid=access-dialog]').text()).toContain('course-one|member@example.test')
	})
	it('sorts course dates on the server in both directions',async()=>{
		const w=make();await flushPromises()
		const header=w.findAll('th button').find(b=>b.text().startsWith('Открытие доступа'))!
		await header.trigger('click');await flushPromises()
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_person_courses',expect.objectContaining({sort:'starts_at',direction:'asc',page:1}))
		await header.trigger('click');await flushPromises()
		expect(callMock).toHaveBeenLastCalledWith('lms.lms.contact_workspace.list_person_courses',expect.objectContaining({sort:'starts_at',direction:'desc'}))
	})
	it('does not overwrite the next opened card with a late save response',async()=>{
		const w=make();await flushPromises()
		let finish:(value:any)=>void=()=>{}
		const implementation=callMock.getMockImplementation()!
		callMock.mockImplementation((url:string,args:any)=>url.endsWith('save_card')?new Promise(resolve=>{finish=resolve}):implementation(url,args))
		await button(w,'Сохранить данные').trigger('click')
		await w.setProps({memberId:'next@example.test'});await flushPromises()
		finish({kind:'User',name:'old@example.test',capabilities:{...caps}});await flushPromises()
		await button(w,'Course One').trigger('click');await flushPromises()
		expect(w.get('[data-testid=access-dialog]').text()).not.toContain('old@example.test')
	})
})
