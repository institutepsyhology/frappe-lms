import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'

const { createResourceMock, pushMock } = vi.hoisted(() => ({
	createResourceMock: vi.fn(),
	pushMock: vi.fn(),
}))

vi.stubGlobal('__', (text: string) => text)
vi.mock('frappe-ui', () => ({
	createResource: createResourceMock,
	usePageMeta: vi.fn(),
	toast: { success: vi.fn(), error: vi.fn() },
	Badge: { template: '<span />' },
	Button: { template: '<button />' },
	Dropdown: { template: '<div />' },
	Tooltip: { template: '<div />' },
}))
vi.mock('vue-router', () => ({
	useRouter: () => ({ push: pushMock }),
	useRoute: () => ({ hash: '', query: {} }),
}))
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/utils/composables', () => ({
	useScreenSize: () => ({ isMobile: { value: false } }),
}))
vi.mock('@/directives/safeHtmlLevels', () => ({
	titleText: (value: unknown) => typeof value === 'string' ? value : '',
}))
vi.mock('@/components/Layouts/TabbedDetailPage.vue', () => ({
	default: { template: '<div><slot name="solo" /></div>' },
}))
vi.mock('@/pages/Courses/CourseOverview.vue', () => ({
	default: { template: '<div data-testid="course-overview" />' },
}))
vi.mock('@/components/SkeletonLoader.vue', () => ({
	default: { template: '<div data-testid="course-loading" />' },
}))
vi.mock('@/pages/Courses/CourseDashboard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/pages/Courses/CourseEditor.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/pages/Courses/CourseForm.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/LessonHelp.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/ShortcutTooltip.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/HeaderButton.vue', () => ({ default: { template: '<button />' } }))
vi.mock('@/composables/useFormRoute', () => ({ openFormRoute: vi.fn() }))

import CourseDetail from '@/pages/Courses/CourseDetail.vue'

let course: { data: Record<string, unknown> | null; loading: boolean; reload: ReturnType<typeof vi.fn> }
const student = { name: 'student@example.test', is_moderator: false }
const membership = { name: 'enrollment-1', member: student.name, course: 'private-course' }
const details = (overrides: Record<string, unknown> = {}) => ({
	name: 'private-course',
	title: 'Private course',
	published: 0,
	upcoming: 0,
	instructors: [{ name: 'teacher@example.test' }],
	membership: false,
	...overrides,
})

function mountPage(user: typeof student | null = student) {
	return mount(CourseDetail, {
		props: { courseName: 'private-course' },
		global: {
			provide: { $user: reactive({ data: user }) },
			stubs: { RouterView: true, RouterLink: true },
		},
	})
}

async function receive(value: Record<string, unknown>) {
	course.data = value
	course.loading = false
	await nextTick()
	await flushPromises()
}

beforeEach(() => {
	vi.clearAllMocks()
	course = reactive({ data: null, loading: true, reload: vi.fn() })
	createResourceMock.mockImplementation(({ url }: { url: string }) =>
		url === 'lms.lms.utils.get_course_details'
			? course
			: reactive({ submit: vi.fn(), loading: false })
	)
})

describe('course page visibility for assigned learners', () => {
	it('keeps an enrolled learner on their unpublished course', async () => {
		const wrapper = mountPage()
		await receive(details({ membership }))
		expect(wrapper.find('[data-testid="course-overview"]').exists()).toBe(true)
		expect(pushMock).not.toHaveBeenCalled()
	})

	it.each([false, null, 0, undefined])('redirects an unassigned learner with membership=%s', async membership => {
		mountPage()
		await receive(details({ membership }))
		expect(pushMock).toHaveBeenCalledWith({ name: 'Courses' })
	})

	it('redirects a guest away from an unpublished course', async () => {
		mountPage(null)
		await receive(details())
		expect(pushMock).toHaveBeenCalledWith({ name: 'Courses' })
	})

	it('preserves moderator and instructor visibility', async () => {
		const moderator = mountPage({ ...student, is_moderator: true })
		await receive(details())
		expect(pushMock).not.toHaveBeenCalled()
		moderator.unmount()

		mountPage({ name: 'teacher@example.test', is_moderator: false })
		await receive(details())
		expect(pushMock).not.toHaveBeenCalled()
	})

	it('does not redirect an unassigned visitor from a published course', async () => {
		mountPage()
		await receive(details({ published: 1 }))
		expect(pushMock).not.toHaveBeenCalled()
	})

	it('keeps loading private and handles the empty response for a denied course', async () => {
		const wrapper = mountPage()
		course.loading = false
		await nextTick()
		expect(wrapper.find('[data-testid="course-overview"]').exists()).toBe(false)
		expect(wrapper.find('[data-testid="course-loading"]').exists()).toBe(true)
		expect(pushMock).not.toHaveBeenCalled()

		await receive({})
		expect(pushMock).toHaveBeenCalledWith({ name: 'Courses' })
	})

	it('redirects if an unpublished course loses its membership', async () => {
		mountPage()
		await receive(details({ membership }))
		expect(pushMock).not.toHaveBeenCalled()

		course.data!.membership = false
		await nextTick()
		expect(pushMock).toHaveBeenCalledWith({ name: 'Courses' })
	})
})
