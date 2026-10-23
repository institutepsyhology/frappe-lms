import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock the heavy Plyr dependency: the guard only cares that the constructor
// runs once per element, not what the player does. The settings store is mocked
// too (the seek listener reads it); neither is exercised in this test.
const plyrCtor = vi.hoisted(() =>
	vi.fn(function FakePlyr(this: { on: () => void }, _video: Element, _options: any) {
		this.on = () => {}
	})
)
vi.mock('plyr', () => ({ default: plyrCtor }))
vi.mock('plyr/dist/plyr.css', () => ({}))
vi.mock('@/stores/settings', () => ({
	useSettings: () => ({ settings: { data: {} } }),
}))
const translations = vi.hoisted(() => ({ pending: Promise.resolve() }))
vi.mock('@/translation', () => ({
	waitForTranslations: () => translations.pending,
}))

import { enablePlyr } from '@/utils/plyr'

describe('enablePlyr double-init guard', () => {
	beforeEach(() => {
		plyrCtor.mockClear()
		document.body.innerHTML = ''
		translations.pending = Promise.resolve()
		vi.stubGlobal('__', (message: string) =>
			/{\d+}/.test(message)
				? { format: (...args: string[]) => message.replace(/{(\d+)}/g, (_, n) => args[n]) }
				: message
		)
	})
	afterEach(() => {
		vi.unstubAllGlobals()
		vi.useRealTimers()
	})

	it('still constructs the player when the catalog request never settles', async () => {
		vi.useFakeTimers()
		translations.pending = new Promise(() => {})
		const el = document.createElement('div')
		el.className = 'video-player'
		document.body.appendChild(el)
		const loading = enablePlyr()
		await vi.advanceTimersByTimeAsync(999)
		expect(plyrCtor).not.toHaveBeenCalled()
		await vi.advanceTimersByTimeAsync(1)
		await expect(loading).resolves.toHaveLength(1)
		expect(plyrCtor).toHaveBeenCalledTimes(1)
	})

	it('uses translated controls after a delayed catalog, preserving Plyr placeholders', async () => {
		let resolveTranslations!: () => void
		translations.pending = new Promise((resolve) => { resolveTranslations = resolve })
		let ready = false
		vi.stubGlobal('__', (message: string) => {
			const labels: Record<string, string> = { Play: 'Воспроизвести', Speed: 'Скорость', 'Rewind {0} seconds': 'Назад на {0} с' }
			const text = ready ? labels[message] || message : message
			return /{\d+}/.test(text) ? { format: (...args: string[]) => text.replace(/{(\d+)}/g, (_, n) => args[n]) } : text
		})
		const el = document.createElement('div')
		el.className = 'video-player'
		document.body.appendChild(el)
		const loading = enablePlyr()
		await new Promise((resolve) => setTimeout(resolve, 550))
		expect(plyrCtor).not.toHaveBeenCalled()
		ready = true
		resolveTranslations()
		await loading
		const options = plyrCtor.mock.calls[0][1] as any
		expect(options.i18n.play).toBe('Воспроизвести')
		expect(options.i18n.speed).toBe('Скорость')
		expect(options.i18n.rewind).toBe('Назад на {seektime} с')
		expect(options.youtube.noCookie).toBe(true)
	})

	it('still builds a usable player if the catalog request fails', async () => {
		translations.pending = Promise.reject(new Error('offline'))
		// The caller owns this request before enablePlyr's 500ms delay ends.
		translations.pending.catch(() => {})
		const el = document.createElement('div')
		el.className = 'video-player'
		document.body.appendChild(el)
		await expect(enablePlyr()).resolves.toHaveLength(1)
	})

	it('initialises Plyr once per .video-player even when enablePlyr runs repeatedly', async () => {
		const el = document.createElement('div')
		el.className = 'video-player'
		el.setAttribute('src', 'dQw4w9WgXcQ')
		document.body.appendChild(el)

		const first = await enablePlyr()
		const second = await enablePlyr()

		// The second pass must reuse the instance, not stack a second player
		// (which is what produced the duplicate controls).
		expect(plyrCtor).toHaveBeenCalledTimes(1)
		expect(first).toHaveLength(1)
		expect(second).toHaveLength(1)
		expect(second[0]).toBe(first[0])
	})

	it('initialises each distinct .video-player exactly once', async () => {
		for (const id of ['aaa', 'bbb']) {
			const el = document.createElement('div')
			el.className = 'video-player'
			el.setAttribute('src', id)
			document.body.appendChild(el)
		}

		await enablePlyr()
		await enablePlyr()

		expect(plyrCtor).toHaveBeenCalledTimes(2)
	})
})
