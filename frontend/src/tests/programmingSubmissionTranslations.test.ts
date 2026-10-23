import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'

enableAutoUnmount(afterEach)

vi.mock('frappe-ui', async () => {
	const { reactive } = await import('vue')
	return {
		Badge: { props: ['theme'], template: '<span data-testid="status" :data-theme="theme"><slot /></span>' },
		Button: { template: '<button><slot /></button>' },
		Avatar: { template: '<span />' },
		FormControl: { name: 'FormControl', props: ['options'], template: '<input />' },
		call: vi.fn(), toast: { error: vi.fn() }, usePageMeta: vi.fn(),
		createDocumentResource: (options: any) => reactive({
			doc: options.doctype.endsWith('Submission')
				? { owner: 'student', status: 'Passed', code: '', test_cases: [{ input: '1', output: '1', expected_output: '1', status: 'Failed' }] }
				: { language: 'Python', title: 'Exercise', problem_statement: '' },
			reload: vi.fn(),
		}),
		createListResource: () => ({ data: [{ status: 'Passed' }], reload: vi.fn(), update: vi.fn() }),
	}
})
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/stores/settings', () => ({ useSettings: () => ({ settings: { data: {} } }) }))
vi.mock('@/utils', () => ({ openSettings: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ currentRoute: { value: { query: {} } }, push: vi.fn() }) }))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/Controls/Link.vue', () => ({ default: { template: '<input />' } }))
vi.mock('@/components/Layouts/ListPage.vue', () => ({
	default: { name: 'ListPage', props: ['rows'], template: '<div><slot name="filters" /><slot name="cell" :column="{ key: \'status\' }" :row="rows[0]" :value="rows[0].status" /></div>' },
}))

const translate = (message: string) => {
	const text = ({ Passed: 'Сдано', Failed: 'Не сдано' } as Record<string, string>)[message] || message
	return /{\d+}/.test(text) ? { format: (...args: string[]) => text.replace(/{(\d+)}/g, (_, n) => args[n]) } : text
}
vi.stubGlobal('__', translate)
const globals = {
	mocks: { __: translate },
	stubs: { Code: { template: '<div />' } },
	provide: { $user: { data: { name: 'student', is_moderator: true } }, $dayjs: () => ({ fromNow: () => '' }) },
}

describe('programming submission status labels', () => {
	it('translates submission and test-case statuses, retaining status colours', async () => {
		const { default: Submission } = await import('@/pages/ProgrammingExercises/ProgrammingExerciseSubmission.vue')
		const wrapper = mount(Submission, { props: { exerciseID: 'exercise' }, global: globals })
		expect(wrapper.get('[data-testid="status"]').text()).toBe('Сдано')
		expect(wrapper.get('[data-testid="status"]').attributes('data-theme')).toBe('green')
		expect(wrapper.text()).toContain('Не сдано')
		for (const script of document.head.querySelectorAll('script[src$="/static/livecode.js"]')) script.remove()
	})
	it('translates table display values while preserving filter and stored statuses', async () => {
		const { default: Submissions } = await import('@/pages/ProgrammingExercises/ProgrammingExerciseSubmissions.vue')
		const wrapper = mount(Submissions, { global: globals })
		expect(wrapper.get('[data-testid="status"]').text()).toBe('Сдано')
		expect(wrapper.getComponent({ name: 'ListPage' }).props('rows')[0].status).toBe('Passed')
		expect(wrapper.findComponent({ name: 'FormControl' }).props('options')[1]).toEqual({ label: 'Сдано', value: 'Passed' })
	})
})
