import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { computed, defineComponent, nextTick } from 'vue'

enableAutoUnmount(afterEach)

const { requests } = vi.hoisted(() => ({ requests: [] as any[] }))

vi.mock('frappe-ui', () => ({
	createResource: vi.fn((options) => {
		if (options.url === 'lms.lms.api.get_translations') {
			requests.push(options)
			return { data: null }
		}
		return { data: options.transform?.([]) || [] }
	}),
	Dropdown: {
		props: ['options'],
		template: `<div><slot :open="false" /><div v-for="group in options"><div v-for="item in group.items">{{ item.label }}<span v-for="app in item.submenu">{{ app.label }}</span></div></div></div>`,
	},
	call: vi.fn(),
	toast: { error: vi.fn(), success: vi.fn() },
	Button: { template: '<button><slot /></button>' },
	FormControl: { template: '<input />' },
	LoadingIndicator: { template: '<span />' },
	ListFooter: { template: '<div><slot name="right" /></div>' },
}))
vi.mock('@/stores/session', () => ({
	sessionStore: () => ({
		branding: { data: null },
		isLoggedIn: true,
		logout: { submit: vi.fn() },
	}),
}))
vi.mock('@/stores/user', () => ({
	usersStore: () => ({ userResource: { data: { username: 'student' } } }),
}))
vi.mock('@/stores/settings', () => ({
	useSettings: () => ({ isSettingsOpen: false, settings: { data: {} } }),
}))
vi.mock('@/utils', () => ({ convertToTitleCase: (value) => value }))
vi.mock('@/utils/theme', () => ({ theme: { value: 'light' }, toggleTheme: vi.fn() }))
vi.mock('@/utils/dialogs', () => ({ createDialog: vi.fn() }))
vi.mock('@/components/Settings/Settings.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/components/Layouts/SettingsLayout.vue', () => ({ default: { template: '<div><slot /><slot name="header-actions" /></div>' } }))
vi.mock('@/components/Layouts/SettingsTable.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/Layouts/PageBody.vue', () => ({ default: { template: '<div><slot /><slot name="footer" /></div>' } }))
vi.mock('@/components/ResponsiveListView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/SkeletonLoader.vue', () => ({ default: { template: '<div />' } }))

const browser = window as Window & {
	translatedMessages?: Record<string, string>
	__?: (message: string) => any
}
let previousMessages: typeof browser.translatedMessages
let previousTranslate: typeof browser.__

beforeEach(() => {
	previousMessages = browser.translatedMessages
	previousTranslate = browser.__
	delete browser.translatedMessages
	requests.length = 0
	vi.resetModules()
})

afterEach(() => {
	browser.translatedMessages = previousMessages
	browser.__ = previousTranslate
	vi.useRealTimers()
})

describe('asynchronous translations', () => {
	it('updates an already mounted template and computed label after the catalog arrives', async () => {
		const { default: plugin } = await import('@/translation')
		const Menu = defineComponent({
			setup: () => ({ title: computed(() => browser.__!('Courses')) }),
			template: '<div>{{ title }} {{ __("Learning") }}</div>',
		})
		const wrapper = mount(Menu, { global: { plugins: [plugin] } })
		expect(wrapper.text()).toBe('Courses Learning')
		expect(requests[0]).toMatchObject({ cache: 'translations', auto: true })
		requests[0].transform({ Courses: 'Курсы', Learning: 'Обучение' })
		await nextTick()
		expect(wrapper.text()).toBe('Курсы Обучение')
	})

	it('shares the late catalog with independently mounted EditorJS sub-apps', async () => {
		const { default: plugin } = await import('@/translation')
		const Block = { template: '<div>{{ __("Courses") }}</div>' }
		const main = mount(Block, { global: { plugins: [plugin] } })
		const editor = mount(Block, { global: { plugins: [plugin] } })
		requests[0].transform({ Courses: 'Курсы' })
		await nextTick()
		expect(main.text()).toBe('Курсы')
		expect(editor.text()).toBe('Курсы')
	})

	it.each([undefined, {}])('renders fallback copy when the catalog is missing or empty (%s)', async (catalog) => {
		const { default: plugin } = await import('@/translation')
		const wrapper = mount({ template: '<div>{{ __("Courses") }}</div>' }, { global: { plugins: [plugin] } })
		if (catalog) requests[0].transform(catalog)
		await nextTick()
		expect(wrapper.text()).toBe('Courses')
		expect(browser.__!('Showing {0} of {1}').format(2, 5)).toBe('Showing 2 of 5')
	})

	it('uses a preloaded catalog immediately and preserves numbered placeholders', async () => {
		browser.translatedMessages = { 'Showing {0} of {1}': 'Показано {0} из {1}' }
		const { default: plugin } = await import('@/translation')
		const wrapper = mount({ template: '<div>{{ __("Showing {0} of {1}").format(2, 5) }}</div>' }, { global: { plugins: [plugin] } })
		expect(wrapper.text()).toBe('Показано 2 из 5')
		expect(browser.__!('Showing {0} of {1}').format(2)).toBe('Показано 2 из {1}')
		expect(requests).toHaveLength(0)
	})

	it('updates user-menu and app-menu labels mounted before the catalog', async () => {
		const { default: plugin } = await import('@/translation')
		const { default: UserDropdown } = await import('@/components/Sidebar/UserDropdown.vue')
		const wrapper = mount(UserDropdown, { global: { plugins: [plugin] } })
		requests[0].transform({
			Learning: 'Обучение',
			'My Profile': 'Мой профиль',
			'Toggle Theme': 'Сменить тему',
			Settings: 'Настройки',
			'Log out': 'Выйти',
			Desk: 'Рабочий стол',
		})
		await nextTick()
		for (const text of ['Обучение', 'Мой профиль', 'Сменить тему', 'Настройки', 'Выйти', 'Рабочий стол']) {
			expect(wrapper.text()).toContain(text)
		}
	})

	it('translates plural names inside shared empty-state copy', async () => {
		const { default: plugin } = await import('@/translation')
		const { default: EmptyState } = await import('@/components/Layouts/EmptyStateLayout.vue')
		const wrapper = mount(EmptyState, { props: { name: 'Courses' }, global: { plugins: [plugin] } })
		requests[0].transform({
			Courses: 'Курсы',
			'No {0} Found': 'Пока нет: {0}',
			'There are no {0} currently. Keep an eye out, fresh learning experiences are on the way!': 'Пока нет: {0}. Новые материалы скоро появятся!',
		})
		await nextTick()
		expect(wrapper.text()).toContain('Пока нет: Курсы')
		expect(wrapper.text()).toContain('Пока нет: курсы. Новые материалы скоро появятся!')
	})

	it.each([{ search: 'zzz' }, { filtered: true }])('translates the noun in filtered settings lists (%s)', async (filter) => {
		const { default: plugin } = await import('@/translation')
		const { default: SettingsList } = await import('@/components/Layouts/SettingsList.vue')
		const wrapper = mount(SettingsList, {
			props: { title: 'Courses', emptyName: 'Courses', columns: [], rows: [], ...filter },
			global: { plugins: [plugin] },
		})
		requests[0].transform({
			Courses: 'Курсы',
			'No {0} match {1}': 'Нет результатов в разделе «{0}» по запросу «{1}»',
			'No {0} match this filter': 'Нет результатов в разделе «{0}» с этим фильтром',
		})
		await nextTick()
		expect(wrapper.text()).toContain('в разделе «курсы»')
		expect(wrapper.text()).not.toContain('courses')
	})

	it('announces an empty list with its translated noun', async () => {
		vi.useFakeTimers()
		const { default: plugin } = await import('@/translation')
		const { default: ListPage } = await import('@/components/Layouts/ListPage.vue')
		const wrapper = mount(ListPage, {
			props: { breadcrumbs: [], emptyName: 'Courses', rows: [], loading: true },
			global: { plugins: [plugin] },
		})
		requests[0].transform({ Courses: 'Курсы', 'No {0} Found': 'Раздел «{0}» пока пуст' })
		await wrapper.setProps({ loading: false })
		await vi.advanceTimersByTimeAsync(500)
		expect(wrapper.get('[role="status"]').text()).toBe('Раздел «Курсы» пока пуст')
	})
})
