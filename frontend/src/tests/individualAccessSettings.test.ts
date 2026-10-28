import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IndividualAccessSettings from '../components/Courses/IndividualAccessSettings.vue'

const { callMock, errorMock } = vi.hoisted(() => ({ callMock: vi.fn(), errorMock: vi.fn() }))
vi.mock('frappe-ui', () => ({ call: callMock, toast: { error: errorMock } }))

describe('individual access settings', () => {
	beforeEach(() => {
		callMock.mockReset()
		errorMock.mockReset()
		callMock.mockResolvedValue({ release_enabled: false, policy_enabled: false, policy_exists: true,
			grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Frozen', starts_at: '2026-10-28 10:30:00',
				personal_end_type: 'Unlimited', personal_end_days: 0, ignore_course_end: 1 }], truncated: false,
			lessons: [{name: 'lesson-1', title: 'Урок 1'}], lessons_truncated: false })
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
		await wrapper.findAll('select').find((item) => item.text().includes('Не продлевать'))!.setValue('0')
		await button.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.resume_grant',
			{ name: 'grant-1', extend_personal_end: '0' })
	})

	it('creates a grant with an explicit start and selected lesson', async () => {
		const wrapper = render(true)
		await flushPromises()
		await wrapper.find('input[type=email]').setValue('new@example.invalid')
		await wrapper.find('input[type=datetime-local]').setValue('2026-10-28T10:30')
		await wrapper.find('input[type=checkbox]').setValue(true)
		await wrapper.findAll('button').find((item) => item.text() === 'Создать карточку')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.create_grant_for_enrolled_student', {
			course: 'course-1', member: 'new@example.invalid', starts_at: '2026-10-28T10:30', lessons: ['lesson-1'],
		})
	})

	it('creates an unconfigured course policy on request', async () => {
		callMock.mockResolvedValueOnce({ release_enabled: false, policy_enabled: false, policy_exists: false,
			grants: [], truncated: false, lessons: [], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		await wrapper.findAll('button').find((item) => item.text() === 'Создать настройки доступа')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.create_course_access_policy', { course: 'course-1' })
	})

	it('asks for confirmation before enabling an empty course policy', async () => {
		callMock.mockResolvedValue({ release_enabled: true, policy_enabled: false, policy_exists: true,
			grants: [], truncated: false, lessons: [], lessons_truncated: false })
		const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
		const wrapper = render(true)
		await flushPromises()
		await wrapper.findAll('button').find((item) => item.text() === 'Включить правила для курса')!.trigger('click')
		await flushPromises()
		expect(confirm).toHaveBeenCalledOnce()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.enable_empty_course_policy', { course: 'course-1' })
		confirm.mockRestore()
	})

	it('saves explicit defaults without enabling the policy', async () => {
		callMock.mockResolvedValueOnce({ release_enabled: false, policy_enabled: false, policy_exists: true,
			policy: { default_personal_end_type: 'After Start', default_personal_end_at: null,
				default_personal_end_days: 30, global_end_type: 'Unlimited', global_end_at: null,
				completed_retention_type: 'Days', completed_retention_days: 14, visited_retention_type: 'None', visited_retention_days: 0 },
			grants: [], truncated: false, lessons: [], lessons_truncated: false, timezone: 'Europe/Moscow' })
		const wrapper = render(true)
		await flushPromises()
		await wrapper.findAll('button').find((item) => item.text() === 'Сохранить общие сроки')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.update_course_access_defaults', {
			course: 'course-1', defaults: { default_personal_end_type: 'After Start', default_personal_end_at: null,
				default_personal_end_days: 30, global_end_type: 'Unlimited', global_end_at: null,
				completed_retention_type: 'Days', completed_retention_days: 14, visited_retention_type: 'None', visited_retention_days: 0 },
		})
	})

	it('saves a lesson opening rule with a delay', async () => {
		const wrapper = render(true)
		await flushPromises()
		await wrapper.findAll('select').find((item) => item.text().includes('Выберите урок'))!.setValue('lesson-1')
		await wrapper.findAll('select').find((item) => item.text().includes('Через дни после начала курса'))!.setValue('After Start')
		await wrapper.find('input[type=number]').setValue(3)
		await wrapper.findAll('select').find((item) => item.text().includes('Без условия'))!.setValue('None')
		await wrapper.findAll('button').find((item) => item.text() === 'Сохранить правило урока')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.update_course_lesson_rule', {
			course: 'course-1', lesson: 'lesson-1', rule: { opening_type: 'After Start', opens_at: null,
				delay_days: 3, prerequisite_type: 'None', prerequisite_lesson: null, prerequisite_assignment: null },
		})
	})

	it('saves an individual start and end rule', async () => {
		const wrapper = render(true)
		await flushPromises()
		await wrapper.findAll('button').find((item) => item.text() === 'Сохранить персональные сроки')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.update_grant_timing', {
			name: 'grant-1', starts_at: '2026-10-28T10:30:00', personal_end_type: 'Unlimited', ends_at: null,
			personal_end_days: 0, ignore_course_end: 1,
		})
	})

	it('shows actual assignments for the prerequisite lesson', async () => {
		callMock.mockImplementation(async (method: string) => method.endsWith('get_lesson_assignments')
			? [{ name: 'homework-1', title: 'Домашняя работа' }]
			: { release_enabled: false, policy_enabled: false, policy_exists: true, grants: [], truncated: false,
				lessons: [{name: 'lesson-1', title: 'Урок 1'}, {name: 'lesson-2', title: 'Урок 2'}], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		await wrapper.findAll('select').find((item) => item.text().includes('Выберите урок'))!.setValue('lesson-2')
		await wrapper.findAll('select').find((item) => item.text().includes('Задание принято'))!.setValue('Assignment Passed')
		const prior = wrapper.findAll('select').find((item) => item.text().includes('Урок 1') && !item.text().includes('Урок 2'))!
		await prior.setValue('lesson-1')
		await flushPromises()
		expect(wrapper.text()).toContain('Домашняя работа')
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.get_lesson_assignments',
			{ course: 'course-1', lesson: 'lesson-1' })
	})

	it('opens an assigned lesson early for the selected grant', async () => {
		callMock.mockImplementation(async (method: string) => method.endsWith('get_grant_lessons')
			? [{ lesson: 'lesson-1', title: 'Урок 1', manual_open: false, retain_when_limited: false }]
			: { release_enabled: false, policy_enabled: false, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Active' }], truncated: false,
				lessons: [{name: 'lesson-1', title: 'Урок 1'}], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Уроки этого ученика'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		await wrapper.findAll('button').find((item) => item.text() === 'Открыть досрочно')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.set_grant_lesson_manual_open',
			{ name: 'grant-1', lesson: 'lesson-1', enabled: 1 })
	})

	it('limits one grant to the explicitly selected lessons', async () => {
		const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
		callMock.mockImplementation(async (method: string) => method.endsWith('get_grant_lessons')
			? [{ lesson: 'lesson-1', title: 'Урок 1', manual_open: false, retain_when_limited: false }]
			: { release_enabled: false, policy_enabled: false, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Active' }], truncated: false,
				lessons: [{name: 'lesson-1', title: 'Урок 1'}], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Уроки этого ученика'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		await details.findAll('input[type=checkbox]').at(-1)!.setValue(true)
		await details.findAll('select').find((item) => item.text().includes('Выберите срок оставленных уроков'))!.setValue('Unlimited')
		await details.findAll('button').find((item) => item.text() === 'Ограничить доступ')!.trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.limit_grant', {
			name: 'grant-1', retained_lessons: ['lesson-1'], retention_end_type: 'Unlimited', retention_ends_at: null,
		})
		confirm.mockRestore()
	})

	it('changes assigned lessons without deleting learning records', async () => {
		const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
		callMock.mockImplementation(async (method: string) => method.endsWith('get_grant_lessons')
			? [{ lesson: 'lesson-1', title: 'Урок 1', manual_open: false, retain_when_limited: false }]
			: { release_enabled: false, policy_enabled: false, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Active' }], truncated: false,
				lessons: [{name: 'lesson-1', title: 'Урок 1'}, {name: 'lesson-2', title: 'Урок 2'}], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Уроки этого ученика'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		const assign = details.findAll('details').find((item) => item.text().includes('Изменить назначенные уроки'))!
		await assign.findAll('input[type=checkbox]')[1].setValue(true)
		await assign.find('button').trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.set_grant_assigned_lessons',
			{ name: 'grant-1', lessons: ['lesson-1', 'lesson-2'] })
		confirm.mockRestore()
	})

	it('saves a personal rule for one assigned lesson', async () => {
		callMock.mockImplementation(async (method: string) => method.endsWith('get_grant_lessons')
			? [{ lesson: 'lesson-1', title: 'Урок 1', manual_open: false, retain_when_limited: false,
				opening_type: 'Inherit', opens_at: null, delay_days: 0, prerequisite_state: 'Inherit' }]
			: { release_enabled: false, policy_enabled: false, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Active' }], truncated: false,
				lessons: [{name: 'lesson-1', title: 'Урок 1'}], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Уроки этого ученика'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		const editor = details.findAll('details').find((item) => item.text().includes('Персональное правило этого урока'))!
		await editor.findAll('select')[0].setValue('After Start')
		await editor.find('input[type=number]').setValue(4)
		await editor.find('button').trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.update_grant_lesson_rule', {
			name: 'grant-1', lesson: 'lesson-1', rule: { opening_type: 'After Start', opens_at: null,
				delay_days: 4, prerequisite_state: 'Inherit' },
		})
	})

	it('shows a read-only restart preview', async () => {
		callMock.mockImplementation(async (method: string) => method.endsWith('preview_course_restart')
			? { progress: 2, homework: 1, quiz_submissions: 0, video_progress: 1, visits: 3, other_grants: 0, enrolled: true }
			: { release_enabled: false, policy_enabled: false, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Active' }], truncated: false,
				lessons: [], lessons_truncated: false })
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Проверить данные перед перезапуском'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		expect(details.text()).toContain('Записей прогресса: 2')
		expect(details.text()).toContain('Данные не удаляются')
	})

	it('requires an explicit selection and confirmation for a partial reset', async () => {
		callMock.mockImplementation(async (method: string) => {
			if (method.endsWith('preview_course_restart')) return { progress: 1, homework: 1, quiz_submissions: 1, video_progress: 0, visits: 0, other_grants: 0, enrolled: true }
			if (method.endsWith('preview_learning_record_reset')) return { counts: { progress: 1, homework: 1, video: 0, visits: 0 }, token: 'snapshot', other_grants: 0 }
			if (method.endsWith('reset_learning_records')) return { deleted: { progress: 1 } }
			return { release_enabled: true, policy_enabled: true, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Revoked' }], truncated: false,
				lessons: [], lessons_truncated: false }
		})
		const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Проверить данные перед перезапуском'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		await details.findAll('button').find((item) => item.text() === 'Подготовить выбор данных')!.trigger('click')
		await flushPromises()
		const reset = details.findAll('button').find((item) => item.text() === 'Удалить выбранные данные')!
		expect(reset.attributes('disabled')).toBeDefined()
		await details.find('input[type=checkbox]').setValue(true)
		await reset.trigger('click')
		await flushPromises()
		expect(confirm).toHaveBeenCalledOnce()
		expect(callMock).toHaveBeenCalledWith('lms.lms.access_actions.reset_learning_records', {
			name: 'grant-1', token: 'snapshot', choices: { progress: true, homework: false, video: false, visits: false },
		})
		confirm.mockRestore()
	})

	it('reports a failed refresh separately from an already completed reset', async () => {
		let previews = 0
		callMock.mockImplementation(async (method: string) => {
			if (method.endsWith('preview_course_restart')) {
				if (++previews > 1) throw new Error('refresh failed')
				return { progress: 1, homework: 0, quiz_submissions: 0, video_progress: 0, visits: 0, other_grants: 0, enrolled: true }
			}
			if (method.endsWith('preview_learning_record_reset')) return { counts: { progress: 1, homework: 0, video: 0, visits: 0 }, token: 'snapshot', other_grants: 0 }
			if (method.endsWith('reset_learning_records')) return { deleted: { progress: 1 } }
			return { release_enabled: true, policy_enabled: true, policy_exists: true,
				grants: [{ name: 'grant-1', member: 'student@example.invalid', status: 'Revoked' }], truncated: false,
				lessons: [], lessons_truncated: false }
		})
		const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
		const wrapper = render(true)
		await flushPromises()
		const details = wrapper.findAll('details').find((item) => item.text().includes('Проверить данные перед перезапуском'))!
		;(details.element as HTMLDetailsElement).open = true
		await details.trigger('toggle')
		await flushPromises()
		await details.findAll('button').find((item) => item.text() === 'Подготовить выбор данных')!.trigger('click')
		await flushPromises()
		await details.find('input[type=checkbox]').setValue(true)
		await details.findAll('button').find((item) => item.text() === 'Удалить выбранные данные')!.trigger('click')
		await flushPromises()
		expect(errorMock).toHaveBeenCalledWith('Очистка выполнена, но обновить сведения не удалось. Откройте проверку данных заново.')
		confirm.mockRestore()
	})
})
