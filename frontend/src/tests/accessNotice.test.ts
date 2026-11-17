import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const { instances, ready } = vi.hoisted(() => ({ instances: [] as any[], ready: { next: null as Promise<void> | null } }))
vi.mock('@editorjs/editorjs', () => ({ default: class {
  isReady = Promise.resolve(); destroy = vi.fn()
  constructor(public options: any) { this.isReady = ready.next || Promise.resolve(); ready.next = null; instances.push(this) }
} }))
vi.mock('@/utils', () => ({ getEditorTools: vi.fn(() => ({})) }))
vi.mock('@/utils/lessonForm', () => ({ parseStoredEditorJs: (raw: string) => { try { return JSON.parse(raw) } catch { return null } } }))
import AccessNotice from '@/components/AccessNotice.vue'
beforeEach(() => { instances.splice(0); ready.next = null })
describe('closed access notice', () => {
  it('shows the Russian reason without creating a learner progress component', () => {
    const w = mount(AccessNotice, { props: { message: 'Урок станет доступен 23.11.2026 06:13.' } })
    expect(w.get('[role=status]').text()).toContain('23.11.2026 06:13')
    expect(instances).toHaveLength(0)
    w.unmount()
  })
  it('escapes the access reason rather than inserting markup into the notice', async () => {
    const w = mount(AccessNotice, { props: { message: '<img src=x onerror=alert(1)>' } })
    await flushPromises()
    expect(w.text()).toContain('<img src=x onerror=alert(1)>')
    expect(w.find('img').exists()).toBe(false)
    expect(instances).toHaveLength(0)
    w.unmount()
  })
  it('replaces rapid notice changes only after the previous editor is released', async () => {
    const content = (text: string) => JSON.stringify({ blocks: [{ type: 'paragraph', data: { text } }] })
    let finish!: () => void
    ready.next = new Promise<void>(resolve => { finish = resolve })
    const w = mount(AccessNotice, { props: { content: content('old') } })
    await flushPromises()
    const previous = instances[0]
    await w.setProps({ content: content('intermediate') }); await flushPromises()
    await w.setProps({ content: content('latest') }); await flushPromises()
    expect(instances).toHaveLength(1)
    finish(); await flushPromises()
    expect(previous.destroy).toHaveBeenCalledOnce()
    expect(instances).toHaveLength(2)
    expect(instances[1].options.data.blocks[0].data.text).toBe('latest')
    expect(instances[1].destroy).not.toHaveBeenCalled()
    w.unmount(); await flushPromises()
    expect(instances[1].destroy).toHaveBeenCalledOnce()
  })
  it('does not construct another editor after unmounting during a notice change', async () => {
    const content = JSON.stringify({ blocks: [{ type: 'paragraph', data: { text: 'notice' } }] })
    let finish!: () => void
    ready.next = new Promise<void>(resolve => { finish = resolve })
    const w = mount(AccessNotice, { props: { content } }); await flushPromises()
    await w.setProps({ content: content.replace('notice', 'new notice') }); await flushPromises()
    w.unmount(); finish(); await flushPromises()
    expect(instances).toHaveLength(1)
    expect(instances[0].destroy).toHaveBeenCalledOnce()
  })
  it('renders separately authored blocks read-only and destroys the editor', async () => {
    const content = JSON.stringify({ blocks: [{ type: 'paragraph', data: { text: 'Продлить доступ' } }] })
    const w = mount(AccessNotice, { props: { message: 'Доступ закрыт.', content } })
    await flushPromises()
    expect(instances).toHaveLength(1)
    expect(instances[0].options.readOnly).toBe(true)
    expect(instances[0].options.data).toEqual(JSON.parse(content))
    w.unmount(); await flushPromises()
    expect(instances[0].destroy).toHaveBeenCalledOnce()
  })
})
