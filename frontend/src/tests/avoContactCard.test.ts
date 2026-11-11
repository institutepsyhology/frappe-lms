import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { callMock, toastMock } = vi.hoisted(() => ({
	callMock: vi.fn(), toastMock: { success: vi.fn(), error: vi.fn() },
}))
vi.mock('frappe-ui', () => ({
	call: callMock,
	toast: toastMock,
	Button: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
	FormControl: { props: ['modelValue','label','disabled'], emits:['update:modelValue'], template: '<label>{{ label }}<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" /></label>' },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace:vi.fn() }) }))
import Card from '@/components/Settings/AvoContactCard.vue'

const make = (roles: string[], system = false, allowed = false) => mount(Card, {
	props: { memberId:'member@example.invalid' },
	global: { provide: { $user:{ data:{ name:'staff@example.invalid', is_system_manager:system, can_manage_credentials:allowed, roles } } } },
})

describe('AVO contact card', () => {
	beforeEach(() => {
		callMock.mockReset()
		callMock.mockImplementation(async (url: string) => {
			if (url.endsWith('get_card')) return { email:'member@example.invalid', enabled:true, custom_avo_contact_id:'42', custom_avo_account:'mv-centr', credential_manager:false }
			if (url.endsWith('courses_for_user')) return []
			if (url.endsWith('reveal')) return { password:'synthetic-test-secret' }
			return { queued:true }
		})
	})
	it('saves the marketing opt-out separately from transactional mail', async () => {
		const wrapper=make([],true)
		await flushPromises()
		await wrapper.find('input[type="checkbox"]').setValue(true)
		await wrapper.findAll('button').find((button) => button.text()==='Сохранить данные')!.trigger('click')
		await flushPromises()
		const callArgs=callMock.mock.calls.find(([url]) => url.endsWith('save_card'))
		expect(callArgs?.[1].values.custom_no_marketing_email).toBe(true)
		expect(wrapper.text()).toContain('Служебные письма')
	})
	it('does not expose passwords or individual grants without an authorized profile', async () => {
		const wrapper=make(['LMS Credential Manager'])
		await flushPromises()
		expect(wrapper.text()).toContain('ID 42')
		expect(wrapper.text()).not.toContain('Показать пароль')
		expect(wrapper.text()).not.toContain('Дать право работы с паролями')
		expect(callMock.mock.calls.some(([url]) => url.endsWith('reveal'))).toBe(false)
	})
	it('shows the current password to administrators on opening the card', async () => {
		const wrapper=make([],true)
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.support_credentials.reveal',{name:'member@example.invalid'})
		expect(wrapper.find('[data-testid="revealed-password"]').text()).toBe('synthetic-test-secret')
		expect(wrapper.text()).not.toContain('Дать право работы с паролями')
	})
	it('shows the password to an authorized job profile', async () => {
		const wrapper=make([],false,true)
		await flushPromises()
		expect(wrapper.find('[data-testid="revealed-password"]').text()).toBe('synthetic-test-secret')
	})
	it('opens a contact without implying it has a login account', async () => {
		const wrapper=mount(Card, { props:{memberId:'contact-42',kind:'Contact'},
			global:{provide:{ $user:{data:{name:'staff@example.invalid',roles:['LMS Credential Manager']}} }} })
		await flushPromises()
		expect(wrapper.text()).toContain('Контакт без связанной учётной записи')
		expect(wrapper.text()).not.toContain('Показать пароль')
		expect(callMock).toHaveBeenCalledWith('lms.lms.avo_contact_card.get_card',{kind:'Contact',name:'contact-42'})
		expect(callMock.mock.calls.some(([url]) => url.endsWith('courses_for_user'))).toBe(false)
	})
	it('sets a new password only on explicit action and then clears the field', async () => {
		const wrapper=make([],false,true)
		await flushPromises()
		const field=wrapper.findAll('label').find((label) => label.text()==='Новый пароль')!
		await field.find('input').setValue('synthetic-new-password')
		expect(callMock.mock.calls.some(([url]) => url.endsWith('set_new_password'))).toBe(false)
		await wrapper.findAll('button').find((button) => button.text()==='Установить новый пароль')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.support_credentials.set_new_password',{
			name:'member@example.invalid',password:'synthetic-new-password',
		})
		expect((field.find('input').element as HTMLInputElement).value).toBe('')
	})
})
