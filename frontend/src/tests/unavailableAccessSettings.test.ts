import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const { callMock, saveMock } = vi.hoisted(() => ({ callMock: vi.fn(), saveMock: vi.fn() }))
vi.mock('frappe-ui', () => ({ call: callMock, toast: { success: vi.fn(), error: vi.fn() }, Button: { template: '<button><slot /></button>' } }))
vi.mock('@/components/BlockEditor.vue', async () => {
 const { defineComponent, h } = await import('vue')
 return { default: defineComponent({ setup(_, { expose }) { expose({ isReady: () => Promise.resolve(), render: vi.fn(), save: saveMock }); return () => h('div') } }) }
})
vi.mock('@/utils/lessonForm', () => ({ parseStoredEditorJs: () => null }))
import UnavailableAccessSettings from '@/components/Courses/UnavailableAccessSettings.vue'
beforeEach(() => {
 callMock.mockReset(); saveMock.mockResolvedValue({ blocks: [{ type: 'paragraph', data: { text: 'Оплатить урок' } }] })
 callMock.mockResolvedValue({ show_when_unavailable: true, access_notice_content: null })
})
describe('closed access settings', () => {
 it('saves only the selected course and lesson notice', async () => {
  const w = mount(UnavailableAccessSettings, { props: { course: 'course', lesson: 'lesson' }, global: { provide: { $user: { data: { is_moderator: true } } } } })
  await flushPromises()
  await w.get('input').setValue(false); await w.get('button').trigger('click'); await flushPromises()
  expect(callMock).toHaveBeenCalledWith('lms.lms.access_presentation.save_visibility_settings', expect.objectContaining({ course: 'course', lesson: 'lesson', show_when_unavailable: 0, access_notice_content: JSON.stringify(await saveMock()) }))
  w.unmount()
 })
 it('does not save an old notice into a newly selected course', async () => {
  let finish!: (data: any) => void
  saveMock.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const w = mount(UnavailableAccessSettings, { props: { course: 'old' }, global: { provide: { $user: { data: { is_moderator: true } } } } })
  await flushPromises(); await w.get('button').trigger('click')
  await w.setProps({ course: 'new' }); await flushPromises()
  finish({ blocks: [{ type: 'paragraph', data: { text: 'Old private notice' } }] }); await flushPromises()
  expect(callMock.mock.calls.some(([method]) => method.endsWith('save_visibility_settings'))).toBe(false)
  w.unmount()
 })
 it('does not expose editing controls to a learner', async () => {
  const w = mount(UnavailableAccessSettings, { props: { course: 'course' }, global: { provide: { $user: { data: { is_student: true } } } } })
  await flushPromises(); expect(w.find('input').exists()).toBe(false); expect(callMock).not.toHaveBeenCalled(); w.unmount()
 })
})
