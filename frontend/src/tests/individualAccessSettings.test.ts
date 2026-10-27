import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IndividualAccessSettings from '../components/Courses/IndividualAccessSettings.vue'

const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))
vi.mock('frappe-ui', () => ({ call: callMock, toast: { error: vi.fn() } }))

describe('individual access settings', () => {
	beforeEach(() => {
		callMock.mockReset()
		callMock.mockResolvedValue({ release_enabled: false, policy_enabled: false, policy_exists: true,
			grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Frozen' }], truncated: false })
	})
	const render = (manager: boolean) => mount(IndividualAccessSettings, {
		props: { course: 'course-1' },
		global: { provide: { $user: { data: { is_system_manager: manager } } } },
	})

	it('hides the list and makes no request for a non-administrator', async () => {
		const wrapper = render(false)
		await flushPromises()
		expect(wrapper.text()).not.toContain('Индивидуальный доступ')
		expect(callMock).not.toHaveBeenCalled()
	})

	it('warns that rules are off and requires a choice before resuming', async () => {
		const wrapper = render(true)
		await flushPromises()
		expect(wrapper.text()).toContain('Правила пока выключены на сайте')
		expect(wrapper.text()).toContain('student@example.invalid')
		const button = wrapper.findAll('button').find((item) => item.text() === 'Возобновить')!
		expect(button.attributes('disabled')).toBeDefined()
		await wrapper.find('select').setValue('0')
		await button.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.resume_grant',
			{ name: 'grant-1', extend_personal_end: '0' })
	})
})
