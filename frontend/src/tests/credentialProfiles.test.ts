import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { callMock }=vi.hoisted(() => ({ callMock:vi.fn() }))
vi.mock('frappe-ui',() => ({
	call:callMock, toast:{success:vi.fn(),error:vi.fn()},
	Button:{template:'<button @click="$emit(\'click\')"><slot /></button>'},
}))
vi.mock('@/components/Layouts/SettingsLayout.vue',() => ({default:{template:'<div><slot /></div>'}}))
import Profiles from '@/components/Settings/CredentialProfiles.vue'

describe('password rights by staff role profile',() => {
	beforeEach(() => {
		callMock.mockReset()
		callMock.mockImplementation(async (url:string) => url.endsWith('list_profiles')
			? [{name:'support',role_profile:'Поддержка',custom_can_manage_credentials:0}] : {enabled:true})
	})
	it('saves permission on a profile, not on a contact',async () => {
		const wrapper=mount(Profiles,{global:{provide:{$user:{data:{name:'Administrator',is_system_manager:true}}}}})
		await flushPromises()
		await wrapper.find('input[type="checkbox"]').setValue(true)
		await wrapper.find('button').trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.credential_profiles.set_profile_access',{profile:'support',enabled:1})
		expect(callMock.mock.calls.some(([url]) => url.endsWith('set_credential_role'))).toBe(false)
	})
	it('does not fetch profile settings for other users',async () => {
		const wrapper=mount(Profiles,{global:{provide:{$user:{data:{name:'student@example.invalid'}}}}})
		await flushPromises()
		expect(wrapper.text()).toContain('системному администратору')
		expect(callMock).not.toHaveBeenCalled()
	})
})
