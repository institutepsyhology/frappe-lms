import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const { courseResource } = vi.hoisted(() => ({ courseResource: { current: null as any } }))

vi.stubGlobal('__', (text: string) => text)
vi.mock('frappe-ui', () => ({
	usePageMeta: vi.fn(),
	createListResource: (options: { url: string }) =>
		options.url.includes('get_course_categories')
			? { data: [] }
			: courseResource.current,
	createResource: () => ({ data: 0, abort: vi.fn(), submit: vi.fn() }),
	Button: { template: '<button />' },
	Dropdown: { template: '<div />' },
	FormControl: { template: '<input />' },
	TabButtons: {
		props: ['options', 'modelValue'],
		emits: ['update:modelValue'],
		template: `<div>
			<button v-for="tab in options" :key="tab.value"
				:data-testid="'tab-' + tab.value" :aria-selected="tab.value === modelValue"
				@click="$emit('update:modelValue', tab.value)">{{ tab.label }}</button>
		</div>`,
	},
}))
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/utils', () => ({ canCreateCourse: () => false }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/components/CourseCard.vue', () => ({ default: { template: '<article />' } }))
vi.mock('@/components/Controls/ClearableCombobox.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/Controls/ToggleFilter.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/Layouts/ListPage.vue', () => ({
	default: { template: '<div><slot name="filters" /></div>' },
}))

import Courses from '@/pages/Courses/Courses.vue'

const student = { name: 'learner@example.test', is_student: true }

async function mountCourses(data: Record<string, unknown> | null, query = '') {
	window.history.replaceState({}, '', `/lms/courses${query}`)
	const wrapper = mount(Courses, {
		global: {
			provide: {
				$user: reactive({ data }),
				$dayjs: () => ({ add: () => ({ format: () => '2026-08-12' }) }),
			},
			mocks: { __: (text: string) => text },
			stubs: { 'router-link': true, 'router-view': true },
		},
	})
	await flushPromises()
	return wrapper
}

const selectedTab = (wrapper: any) =>
	wrapper.find('[aria-selected="true"]').attributes('data-testid')
const sentFilters = () => courseResource.current.update.mock.lastCall[0].filters

beforeEach(() => {
	courseResource.current = reactive({
		data: [],
		hasNextPage: false,
		pageLength: 24,
		list: { loading: false, abort: vi.fn() },
		update: vi.fn(),
		reload: vi.fn().mockResolvedValue(undefined),
		next: vi.fn(),
	})
})

describe('Courses initial tab', () => {
	it('opens a learner’s assigned courses without requiring catalog publication', async () => {
		const wrapper = await mountCourses(student)
		expect(selectedTab(wrapper)).toBe('tab-enrolled')
		expect(sentFilters()).toEqual({ enrolled: 1 })
	})

	it.each(['live', 'upcoming', 'created', 'unpublished'])(
		'keeps a learner’s stale ?tab=%s link on assigned courses', async (tab) => {
			const wrapper = await mountCourses(student, `?tab=${tab}`)
			expect(selectedTab(wrapper)).toBe('tab-enrolled')
			expect(sentFilters()).toEqual({ enrolled: 1 })
		},
	)

	it.each(['is_moderator', 'is_instructor', 'is_evaluator'])(
		'preserves the Published default for staff with %s', async (role) => {
			const wrapper = await mountCourses({ name: 'staff@example.test', [role]: true, is_student: false })
			expect(selectedTab(wrapper)).toBe('tab-live')
			expect(sentFilters()).toEqual({ published: 1, upcoming: 0, live: 1 })
		},
	)

	it('preserves an explicitly linked staff tab', async () => {
		const wrapper = await mountCourses({ is_moderator: true }, '?tab=unpublished')
		expect(selectedTab(wrapper)).toBe('tab-unpublished')
		expect(sentFilters()).toEqual({ published: 0 })
	})

	it('preserves the guest catalog default', async () => {
		const wrapper = await mountCourses(null)
		expect(selectedTab(wrapper)).toBe('tab-live')
		expect(sentFilters()).toEqual({ published: 1, upcoming: 0, live: 1 })
		expect(wrapper.find('[data-testid="tab-enrolled"]').exists()).toBe(false)
	})

	it('only offers assigned courses to a learner', async () => {
		const wrapper = await mountCourses(student)
		expect(wrapper.findAll('[data-testid^="tab-"]')).toHaveLength(1)
		expect(selectedTab(wrapper)).toBe('tab-enrolled')
		expect(sentFilters()).toEqual({ enrolled: 1 })
	})
})
