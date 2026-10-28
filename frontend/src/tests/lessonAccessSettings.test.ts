import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LessonAccessSettings from '@/components/Courses/LessonAccessSettings.vue'

const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))
vi.mock('frappe-ui', () => ({ call: callMock, toast: { error: vi.fn() } }))

describe('access settings in a lesson', () => {
	beforeEach(() => {
		callMock.mockReset()
		callMock.mockResolvedValue({ release_enabled: true, policy_enabled: true, policy_exists: true, timezone: 'Europe/Moscow',
			lessons: [{ name: 'one', title: 'Первый' }, { name: 'two', title: 'Второй' }], lessons_truncated: false,
			schedule: [{ lesson: 'one', opening_type: 'After Start', opens_at: null, delay_days: 0, prerequisite_type: 'None', prerequisite_lesson: null, prerequisite_assignment: null }] })
	})
	it('loads and saves the selected lesson without changing another lesson', async () => {
		const wrapper = mount(LessonAccessSettings, { props: { course: 'course', lesson: 'one' }, global: { provide: { $user: { data: { is_system_manager: true } } } } })
		await flushPromises()
		expect(wrapper.text()).toContain('Настройки доступа к этому уроку')
		await wrapper.find('input[type=number]').setValue(5)
		await wrapper.find('button').trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.update_course_lesson_rule', { course: 'course', lesson: 'one', rule: {
			opening_type: 'After Start', opens_at: null, delay_days: 5, prerequisite_type: 'None', prerequisite_lesson: null, prerequisite_assignment: null,
		} })
	})
	it('hides settings from users without the administrator role', async () => {
		const wrapper = mount(LessonAccessSettings, { props: { course: 'course', lesson: 'one' }, global: { provide: { $user: { data: { is_system_manager: false } } } } })
		await flushPromises()
		expect(wrapper.text()).toBe('')
		expect(callMock).not.toHaveBeenCalled()
	})
})
