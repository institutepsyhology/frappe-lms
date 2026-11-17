import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))
vi.mock('frappe-ui', () => ({
    call: callMock,
    toast: { success: vi.fn(), error: vi.fn() },
    Button: { template: '<button><slot/></button>' },
    Dialog: { props: ['open'], template: '<div v-if="open"><slot/></div>' },
}))
import PersonCourseAccessDialog from '@/components/PersonCourseAccessDialog.vue'

const token = 'a'.repeat(64)
const access = () => ({
    course: 'course', member: null, archive_only: false,
    release_enabled: true, policy_enabled: true, policy_exists: true,
    timezone: 'Europe/Moscow', blocks: [], enrollment: { name: token },
    capabilities: { read: true, write: true, remove: true },
    grants: [{ name: 'grant', status: 'Active', starts_at: '2026-01-01 10:00:00',
        personal_end_type: 'Unlimited', source: { label: 'Способ выдачи не записан' } }],
})
const assignedLesson = () => ({
    lesson: 'lesson', title: 'Первый урок', assignment: 'assigned',
    opening_type: 'Inherit', prerequisite_state: 'Inherit', manual_open: 0,
    effective_available: false, access_reason: 'Ожидает расписания',
    opens_at_effective: '2026-12-01 09:00:00',
})
const availableLesson = () => ({ ...assignedLesson(), lesson: 'new-lesson', title: 'Новый урок', assignment: null })
const render = () => mount(PersonCourseAccessDialog, { props: { open: true, course: 'course', enrollment: token } })
const button = (wrapper: ReturnType<typeof render>, text: string) => wrapper.findAll('button').find(b => b.text() === text)!
const response = (args: any, rows = [args.assignment_filter === 'available' ? availableLesson() : assignedLesson()]) => ({ rows, total: 1001, page: args.page, page_length: 50 })

enableAutoUnmount(afterEach)
beforeEach(() => {
    vi.restoreAllMocks()
    callMock.mockReset()
    callMock.mockImplementation(async (method: string, args: any) => {
        if (method.endsWith('get_member_access')) return access()
        if (method.endsWith('list_member_lessons')) return response(args)
        return {}
    })
})

describe('one-person course access', () => {
    it('loads the assigned list for one opaque enrollment with bounded pages', async () => {
        const w = render(); await flushPromises()
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.get_member_access', expect.objectContaining({ course: 'course', enrollment: token }))
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.list_member_lessons', expect.objectContaining({ course: 'course', enrollment: token, page_length: 50, assignment_filter: 'assigned' }))
        expect(w.findAll('[data-testid="personal-lesson"]')).toHaveLength(1)
        expect(w.text()).toContain('1001 уроков')
        expect(w.text()).toContain('01.12.2026 09:00:00')
    })

    it('saves a permanent course block using the opaque enrollment', async () => {
        const w = render(); await flushPromises()
        await w.get('input[type=checkbox]').setValue(true)
        await button(w, 'Сохранить блокировку курса').trigger('click'); await flushPromises()
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.set_member_block', expect.objectContaining({ course: 'course', enrollment: token, blocked: 1, until: null, lesson: null }))
        expect(w.emitted('saved')).toHaveLength(1)
    })

    it('shows only unassigned lessons in add mode and saves selected lessons once', async () => {
        const w = render(); await flushPromises()
        await button(w, 'Добавить урок').trigger('click'); await flushPromises()
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.list_member_lessons', expect.objectContaining({ assignment_filter: 'available', page: 1 }))
        expect(w.text()).toContain('Новый урок')
        await w.get('[data-testid="personal-lesson"] input[type=checkbox]').setValue(true)
        expect(callMock.mock.calls.filter(([m]) => m.endsWith('change_lesson_assignments'))).toHaveLength(0)
        await button(w, 'Добавить выбранные').trigger('click'); await flushPromises()
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.change_lesson_assignments', expect.objectContaining({ course: 'course', enrollment: token, grant: 'grant', lessons: ['new-lesson'], assigned: 1 }))
        expect(callMock.mock.calls.filter(([m]) => m.endsWith('change_lesson_assignments'))).toHaveLength(1)
        expect(callMock.mock.calls.some(([m]) => m.endsWith('change_lesson_assignment'))).toBe(false)
    })

    it('removes the selected assigned lessons with one confirmation and one request', async () => {
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
        const w = render(); await flushPromises()
        await w.get('[data-testid="select-lesson-page"]').setValue(true)
        await button(w, 'Удалить выбранные').trigger('click'); await flushPromises()
        expect(confirm).toHaveBeenCalledTimes(1)
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.change_lesson_assignments', expect.objectContaining({ lessons: ['lesson'], assigned: 0 }))
        expect(w.emitted('saved')).toHaveLength(1)
    })

    it('does not change lessons after a cancelled removal', async () => {
        vi.spyOn(window, 'confirm').mockReturnValue(false)
        const w = render(); await flushPromises()
        await w.get('[data-testid="select-lesson-page"]').setValue(true)
        await button(w, 'Удалить выбранные').trigger('click'); await flushPromises()
        expect(callMock.mock.calls.some(([m]) => m.endsWith('change_lesson_assignments'))).toBe(false)
        expect(w.text()).toContain('Выбрано: 1')
    })

    it('clears selection between list modes and pages', async () => {
        const w = render(); await flushPromises()
        await w.get('[data-testid="select-lesson-page"]').setValue(true)
        await button(w, 'Добавить урок').trigger('click'); await flushPromises()
        expect(w.text()).toContain('Выбрано: 0')
        await w.get('[data-testid="select-lesson-page"]').setValue(true)
        await button(w, 'Далее').trigger('click'); await flushPromises()
        expect(w.text()).toContain('Выбрано: 0')
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.list_member_lessons', expect.objectContaining({ assignment_filter: 'available', page: 2 }))
    })

    it('keeps effective availability separate from completion and recorded visits', async () => {
        callMock.mockImplementation(async (method: string, args: any) => {
            if (method.endsWith('get_member_access')) return access()
            if (method.endsWith('list_member_lessons')) return response(args, [{ ...assignedLesson(), effective_available: true, completion_status: 'Complete', first_learner_visit_at: '2026-11-16 10:11:12', last_learner_visit_at: '2026-11-17 13:14:15' }])
            return {}
        })
        const w = render(); await flushPromises()
        const available = w.get('input[aria-label="Урок доступен: Первый урок"]')
        expect((available.element as HTMLInputElement).checked).toBe(true)
        expect((available.element as HTMLInputElement).disabled).toBe(true)
        expect(w.get('[data-testid="first-visit"]').text()).toBe('16.11.2026 10:11:12')
        expect(w.get('[data-testid="last-visit"]').text()).toBe('17.11.2026 13:14:15')
        expect(w.text()).toContain('Пройден')
        expect(button(w, 'Открыть досрочно')).toBeUndefined()
    })

    it('never fills verified visit cells with legacy creation or modified dates', async () => {
        callMock.mockImplementation(async (method: string, args: any) => {
            if (method.endsWith('get_member_access')) return access()
            if (method.endsWith('list_member_lessons')) return response(args, [{ ...assignedLesson(), creation: '2020-01-02 03:04:05', modified: '2025-01-02 03:04:05', first_visited_at: '2020-01-02 03:04:05' }])
            return {}
        })
        const w = render(); await flushPromises()
        expect(w.get('[data-testid="first-visit"]').text()).toBe('Нет подтверждённых данных')
        expect(w.get('[data-testid="last-visit"]').text()).toBe('Нет подтверждённых данных')
        expect(w.text()).not.toContain('2020-01-02')
    })

    it('opens a scheduled lesson early using the bound grant', async () => {
        const w = render(); await flushPromises()
        await button(w, 'Открыть досрочно').trigger('click'); await flushPromises()
        expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.change_member_access', expect.objectContaining({ course: 'course', enrollment: token, grant: 'grant', action: 'manual_open', values: { lesson: 'lesson', enabled: 1 } }))
    })

    it('keeps course blocking authoritative when a lesson could be opened early', async () => {
        callMock.mockImplementation(async (method: string, args: any) => {
            if (method.endsWith('get_member_access')) return { ...access(), blocks: [{ lesson: null, effective: true, blocked_until: null }] }
            if (method.endsWith('list_member_lessons')) return response(args)
            return {}
        })
        const w = render(); await flushPromises()
        expect(w.text()).toContain('Курс закрыт бессрочно')
        expect(button(w, 'Открыть досрочно').attributes('disabled')).toBeDefined()
    })

    it('does not offer lesson mutations to read-only staff', async () => {
        callMock.mockImplementation(async (method: string, args: any) => {
            if (method.endsWith('get_member_access')) return { ...access(), capabilities: { read: true, write: false, remove: false } }
            if (method.endsWith('list_member_lessons')) return response(args)
            return {}
        })
        const w = render(); await flushPromises()
        expect(w.find('[data-testid="select-lesson-page"]').exists()).toBe(false)
        expect(button(w, 'Добавить урок')).toBeUndefined()
        expect(button(w, 'Открыть досрочно')).toBeUndefined()
        expect(w.get('input[aria-label="Урок доступен: Первый урок"]').attributes('disabled')).toBeDefined()
    })

    it('discards stale lesson responses after the selected person changes', async () => {
        let resolveOld!: (value: any) => void
        callMock.mockImplementation(async (method: string, args: any) => {
            if (method.endsWith('get_member_access')) return access()
            if (method.endsWith('list_member_lessons') && args.enrollment === token) return new Promise(resolve => { resolveOld = resolve })
            if (method.endsWith('list_member_lessons')) return response(args, [{ ...assignedLesson(), title: 'Другой ученик' }])
            return {}
        })
        const w = render(); await flushPromises()
        await w.setProps({ enrollment: 'b'.repeat(64) }); await flushPromises()
        resolveOld({ rows: [{ ...assignedLesson(), title: 'Устаревший ответ' }], total: 1, page: 1 }); await flushPromises()
        expect(w.text()).toContain('Другой ученик')
        expect(w.text()).not.toContain('Устаревший ответ')
    })

    it.each(['early', 'block', 'bulk'] as const)('does not refresh or report a saved change for another person after %s finishes', async kind => {
        let finish!: (value: any) => void
        const mutation = kind === 'early' ? 'change_member_access' : kind === 'block' ? 'set_member_block' : 'change_lesson_assignments'
        callMock.mockImplementation(async (method: string, args: any) => {
            if (method.endsWith('get_member_access')) return access()
            if (method.endsWith('list_member_lessons')) return response(args, [{ ...assignedLesson(), title: args.enrollment === token ? 'Первый ученик' : 'Второй ученик' }])
            if (method.endsWith(mutation)) return new Promise(resolve => { finish = resolve })
            return {}
        })
        vi.spyOn(window, 'confirm').mockReturnValue(true)
        const w = render(); await flushPromises()
        if (kind === 'early') await button(w, 'Открыть досрочно').trigger('click')
        else if (kind === 'block') {
            await w.get('input[type=checkbox]').setValue(true)
            await button(w, 'Сохранить блокировку курса').trigger('click')
        } else {
            await w.get('[data-testid="select-lesson-page"]').setValue(true)
            await button(w, 'Удалить выбранные').trigger('click')
        }
        expect(finish).toBeTypeOf('function')
        await w.setProps({ enrollment: 'b'.repeat(64) }); await flushPromises()
        expect(w.text()).toContain('Второй ученик')
        const reads = callMock.mock.calls.filter(([m]) => m.endsWith('get_member_access')).length
        finish({}); await flushPromises()
        expect(callMock.mock.calls.filter(([m]) => m.endsWith('get_member_access'))).toHaveLength(reads)
        expect(w.emitted('saved')).toBeUndefined()
        expect(w.text()).toContain('Второй ученик')
    })

    it('keeps archived contact-only access read-only without loading runtime lessons', async () => {
        callMock.mockResolvedValue({ course: 'course', archive_only: true, notice: 'Архивный доступ', grants: [], capabilities: { read: true, write: false, remove: false } })
        const w = mount(PersonCourseAccessDialog, { props: { open: true, course: 'course', contact: 'contact' } }); await flushPromises()
        expect(w.text()).toContain('Архивный доступ')
        expect(w.find('input').exists()).toBe(false)
        expect(callMock).toHaveBeenCalledTimes(1)
    })

    it('does not invent the original issuer or event time for an untracked grant', async () => {
        const w = render(); await flushPromises()
        expect(w.text()).toContain('Дата и сотрудник первоначальной выдачи не записаны')
        expect(w.text()).not.toContain('Administrator')
    })
})
