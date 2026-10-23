import { afterEach, describe, expect, it, vi } from 'vitest'

const browser = window as Window & { lang?: string }
const originalLanguage = browser.lang
const originalDirection = document.documentElement.dir
const originalHtmlLanguage = document.documentElement.lang

afterEach(() => {
	browser.lang = originalLanguage
	document.documentElement.dir = originalDirection
	document.documentElement.lang = originalHtmlLanguage
	vi.restoreAllMocks()
})

async function loadDayjs(language?: string, htmlLanguage = '', browserLanguage = 'en-US', direction = 'ltr') {
	vi.resetModules()
	browser.lang = language
	document.documentElement.lang = htmlLanguage
	document.documentElement.dir = direction
	vi.spyOn(navigator, 'language', 'get').mockReturnValue(browserLanguage)
	return (await import('@/utils/dayjs')).default
}

describe('date language', () => {
	it('uses the boot Russian locale for month names and relative dates', async () => {
		const dayjs = await loadDayjs('ru')
		expect(dayjs('2026-10-24').format('MMM')).toBe('окт.')
		expect(dayjs('2026-10-24T09:00').from(dayjs('2026-10-24T10:00'))).toBe('час назад')
	})
	it.each(['ru-RU', 'ru_RU'])('accepts regional Russian locale %s', async (language) => {
		expect((await loadDayjs(language)).locale()).toBe('ru')
	})
	it('uses the document language before the browser language', async () => {
		expect((await loadDayjs(undefined, 'ru', 'en-US')).locale()).toBe('ru')
	})
	it('uses the browser Russian locale when boot and document languages are absent', async () => {
		expect((await loadDayjs(undefined, '', 'ru-RU')).locale()).toBe('ru')
	})
	it('keeps the existing RTL locale', async () => {
		expect((await loadDayjs('he', '', 'ru-RU', 'rtl')).locale()).toBe('he')
	})
	it('keeps an explicit English boot language ahead of browser Russian', async () => {
		expect((await loadDayjs('en', '', 'ru-RU')).locale()).toBe('en')
	})
})
