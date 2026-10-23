import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import Statistics from '@/pages/Statistics.vue'
import translationPlugin from '@/translation'

enableAutoUnmount(afterEach)

const { completed } = vi.hoisted(() => ({ completed: { value: 3 } }))

vi.mock('frappe-ui', () => {
	const chart = (name: string) => ({
		name,
		props: ['config'],
		template: '<div>{{ config.title }}</div>',
	})
	return {
		AxisChart: chart('AxisChart'),
		DonutChart: chart('DonutChart'),
		NumberChart: chart('NumberChart'),
		LoadingIndicator: { template: '<span />' },
		Tooltip: { template: '<div><slot /></div>' },
		usePageMeta: vi.fn(),
		createResource: (options: any) => {
			if (options.url.endsWith('get_chart_details')) {
				return { data: { courses: 1, users: 5, enrollments: 4, completions: 3, certifications: 2 } }
			}
			if (options.url.endsWith('get_course_completion_data')) {
				return { data: [{ label: 'Completed', value: completed.value }, { label: 'Incomplete', value: 1 }] }
			}
			return { data: options.transform([{ date: '2026-10-24', count: 2 }]) }
		},
	}
})
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ brand: {} }) }))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({ default: { template: '<div />' } }))

const browser = window as Window & {
	translatedMessages?: Record<string, string>
	__?: (message: string) => unknown
}
const originalMessages = browser.translatedMessages
const originalTranslate = browser.__
afterEach(() => {
	browser.translatedMessages = originalMessages
	browser.__ = originalTranslate
	completed.value = 3
})

const openStatistics = () => {
	browser.translatedMessages = {
		Courses: 'Курсы', Signups: 'Регистрации', Enrollments: 'Зачисления',
		Completions: 'Завершения', Certifications: 'Сертификаты',
		'Signups per day': 'Регистрации по дням', Date: 'Дата',
		Completed: 'Завершено', Incomplete: 'Не завершено',
	}
	return mount(Statistics, { global: { plugins: [translationPlugin] } })
}

describe('statistics translations', () => {
	it('translates chart labels while preserving data keys and completion visibility', () => {
		const wrapper = openStatistics()
		expect(wrapper.findAllComponents({ name: 'NumberChart' }).map((chart) => chart.props('config').title))
			.toEqual(['Курсы', 'Регистрации', 'Зачисления', 'Завершения', 'Сертификаты'])
		const signups = wrapper.findAllComponents({ name: 'AxisChart' })[0].props('config')
		expect(signups.subtitle).toBe('Регистрации по дням')
		expect(signups.xAxis.title).toBe('Дата')
		expect(signups.series[0].name).toBe('signups')
		expect(signups.data[0].signups).toBe(2)
		const completion = wrapper.getComponent({ name: 'DonutChart' }).props('config')
		expect(completion.data).toEqual([
			{ label: 'Завершено', value: 3 }, { label: 'Не завершено', value: 1 },
		])
	})

	it('still hides the donut when the untranslated completion count is zero', () => {
		completed.value = 0
		expect(openStatistics().findComponent({ name: 'DonutChart' }).exists()).toBe(false)
	})
})
