import { afterEach, describe, expect, it, vi } from 'vitest'
import { VideoChoice, normalizeVideoUrl } from '../utils/videoChoice'

const youtubeId = 'abcdefghijk'
const rutubeId = '0123456789abcdef0123456789abcdef'
// Deliberately fake access key: real private-video URLs never belong in tests.
const rutubeSource = `https://rutube.ru/video/private/${rutubeId}/?p=fake_test_key`
const rutubeEmbed = `https://rutube.ru/play/embed/${rutubeId}/?p=fake_test_key`
const youtubeEmbed = `https://www.youtube.com/embed/${youtubeId}`
const data = { rutube: rutubeSource, youtube: `https://youtu.be/${youtubeId}`, defaultProvider: 'rutube' as const }

afterEach(() => {
	document.body.replaceChildren()
})

describe('video source URLs', () => {
	it.each([
		`https://youtu.be/${youtubeId}?t=12`,
		`https://www.youtube.com/watch?v=${youtubeId}&list=ignored`,
		`https://www.youtube.com/embed/${youtubeId}`,
		`https://m.youtube.com/watch?v=${youtubeId}`,
	])('normalizes the supported YouTube source %s to a player URL', (source) => {
		expect(normalizeVideoUrl('youtube', source)).toBe(youtubeEmbed)
	})

	it('converts the private Rutube page to an embed and preserves its access key', () => {
		expect(normalizeVideoUrl('rutube', rutubeSource)).toBe(rutubeEmbed)
		expect(normalizeVideoUrl('rutube', rutubeEmbed)).toBe(rutubeEmbed)
		expect(normalizeVideoUrl('rutube', `https://rutube.ru/video/${rutubeId}/`)).toBe(
			`https://rutube.ru/play/embed/${rutubeId}/`
		)
	})

	it.each([
		['youtube', `https://www.youtube.com.attacker.test/embed/${youtubeId}`],
		['youtube', `https://attacker.test/watch?v=${youtubeId}`],
		['youtube', `https://user@www.youtube.com/embed/${youtubeId}`],
		['youtube', `https://www.youtube.com:444/embed/${youtubeId}`],
		['youtube', `http://www.youtube.com/embed/${youtubeId}`],
		['youtube', 'javascript:alert(1)'],
		['youtube', 'https://www.youtube.com/embed/not-an-id'],
		['rutube', `https://rutube.ru.attacker.test/play/embed/${rutubeId}/?p=fake_test_key`],
		['rutube', `https://rutube.ru/video/private/${rutubeId}/`],
		['rutube', `https://rutube.ru/play/embed/${rutubeId}/?p=bad%22key`],
		['rutube', `https://rutube.ru/play/embed/${rutubeId}/?p=one&p=two`],
		['rutube', `https://rutube.ru/video/${rutubeId}/unexpected`],
	])('rejects unsafe or unsupported %s URLs', (provider, source) => {
		expect(normalizeVideoUrl(provider as 'rutube' | 'youtube', source)).toBe('')
	})
})

describe('videoChoice EditorJS block', () => {
	it('shows one Rutube player by default with two source buttons and no outgoing links', () => {
		const tool = new VideoChoice({ data, readOnly: true })
		const root = tool.render()
		document.body.append(root)
		expect(root.querySelectorAll('iframe')).toHaveLength(1)
		expect(root.querySelector('iframe')?.src).toBe(rutubeEmbed)
		expect([...root.querySelectorAll('button[data-provider]')].map((button) => button.textContent)).toEqual(['Rutube', 'YouTube'])
		expect(root.querySelector('button[aria-pressed="true"]')?.textContent).toBe('Rutube')
		const activeButton = root.querySelector('button[aria-pressed="true"]')!
		expect(getComputedStyle(activeButton).backgroundColor).toBe('rgb(17, 24, 39)')
		expect(getComputedStyle(activeButton).color).toBe('rgb(255, 255, 255)')
		expect(root.querySelector('a')).toBeNull()
		expect(root.querySelector('input[type=url]')).toBeNull()
		expect(root.querySelector('iframe')?.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-presentation')
		expect(root.querySelector('iframe')?.getAttribute('allow')).toBe('autoplay; fullscreen; picture-in-picture; encrypted-media')
	})

	it('removes the previous iframe when the learner changes source and leaves the saved default unchanged', () => {
		const tool = new VideoChoice({ data, readOnly: true })
		const root = tool.render()
		document.body.append(root)
		const previous = root.querySelector('iframe')!
		root.querySelectorAll('button')[1].click()
		expect(previous.isConnected).toBe(false)
		expect(root.querySelectorAll('iframe')).toHaveLength(1)
		expect(root.querySelector('iframe')?.src).toContain(youtubeEmbed)
		expect(root.querySelector('button[aria-pressed="true"]')?.textContent).toBe('YouTube')
		expect(tool.save()).toEqual({ rutube: rutubeEmbed, youtube: youtubeEmbed, defaultProvider: 'rutube' })
	})

	it('falls back to the valid provider without creating an empty iframe', () => {
		const tool = new VideoChoice({ data: { ...data, rutube: 'javascript:alert(1)' }, readOnly: true })
		const root = tool.render()
		expect(root.querySelector('iframe')?.src).toContain(youtubeEmbed)
		expect(root.querySelectorAll('button')[0].disabled).toBe(true)
		const empty = new VideoChoice({ data: {}, readOnly: true }).render()
		expect(empty.querySelector('iframe')).toBeNull()
		expect(empty.querySelector('a')).toBeNull()
	})

	it('lets an author paste source URLs, validates them, and saves normalized private embeds', () => {
		const api = { blocks: { getBlockByIndex: vi.fn() } }
		const block = { dispatchChange: vi.fn() }
		const tool = new VideoChoice({ data: {}, readOnly: false, api, block })
		const root = tool.render()
		const inputs = root.querySelectorAll('input')
		expect(inputs).toHaveLength(2)
		inputs[0].value = rutubeSource
		inputs[0].dispatchEvent(new Event('input', { bubbles: true }))
		inputs[1].value = `https://www.youtube.com/watch?v=${youtubeId}`
		inputs[1].dispatchEvent(new Event('input', { bubbles: true }))
		expect(tool.save()).toEqual({ rutube: rutubeEmbed, youtube: youtubeEmbed, defaultProvider: 'rutube' })
		expect(block.dispatchChange).toHaveBeenCalled()
		expect(root.querySelectorAll('iframe')).toHaveLength(1)
		inputs[0].value = 'https://attacker.test/player'
		inputs[0].dispatchEvent(new Event('input', { bubbles: true }))
		expect(inputs[0].getAttribute('aria-invalid')).toBe('true')
		expect(tool.save().rutube).toBe('')
		expect(root.querySelector('iframe')?.src).toBe(youtubeEmbed)
	})

	it('allows an author to change the saved default independently of the preview buttons', () => {
		const tool = new VideoChoice({ data, readOnly: false })
		const root = tool.render()
		const select = root.querySelector('select')!
		select.value = 'youtube'
		select.dispatchEvent(new Event('change', { bubbles: true }))
		expect(tool.save().defaultProvider).toBe('youtube')
		expect(root.querySelector('iframe')?.src).toBe(youtubeEmbed)
		root.querySelectorAll('button')[0].click()
		expect(tool.save().defaultProvider).toBe('youtube')
	})

	it('provides separate playback controls for YouTube and preserves the standard Rutube player', () => {
		const tool = new VideoChoice({ data, readOnly: true })
		const root = tool.render()
		document.body.append(root)
		expect(root.querySelector('[aria-label="Воспроизвести или приостановить видео"]')).toBeNull()
		;(root.querySelector('[data-provider="youtube"]') as HTMLButtonElement).click()
		const frame = root.querySelector('iframe')!
		expect(frame.tabIndex).toBe(-1)
		expect(new URL(frame.src).searchParams.get('controls')).toBe('0')
		const send = vi.spyOn(frame.contentWindow!, 'postMessage')
		;(root.querySelector('[aria-label="▶"]') as HTMLButtonElement).click()
		expect(send).toHaveBeenCalledWith(expect.stringContaining('playVideo'), 'https://www.youtube.com')
		expect(root.textContent).toContain('❚❚')
		;(root.querySelector('[aria-label="Пауза"]') as HTMLButtonElement).click()
		expect(send).toHaveBeenCalledWith(expect.stringContaining('pauseVideo'), 'https://www.youtube.com')
		tool.destroy()
	})

	it('tears down its iframe when the editor removes the block', () => {
		const tool = new VideoChoice({ data, readOnly: true })
		const root = tool.render()
		document.body.append(root)
		const frame = root.querySelector('iframe')!
		tool.destroy()
		expect(frame.isConnected).toBe(false)
		expect(root.querySelector('iframe')).toBeNull()
	})
})

describe('video playback position', () => {
	afterEach(() => localStorage.clear())
	it.each(['rutube', 'youtube'] as const)('saves and restores %s independently', (provider) => {
		const tool = new VideoChoice({ data: { ...data, defaultProvider: provider }, readOnly: true })
		const root = tool.render()
		document.body.append(root)
		const frame = root.querySelector('iframe')!
		const origin = provider === 'rutube' ? 'https://rutube.ru' : 'https://www.youtube.com'
		const message = provider === 'rutube' ? { type: 'player:currentTime', data: { time: 42 } } : { event: 'infoDelivery', info: { currentTime: 42 } }
		window.dispatchEvent(new MessageEvent('message', { origin, source: frame.contentWindow, data: JSON.stringify(message) }))
		tool.destroy()
		const next = new VideoChoice({ data: { ...data, defaultProvider: provider }, readOnly: true }).render()
		expect(new URL(next.querySelector('iframe')!.src).searchParams.get(provider === 'rutube' ? 't' : 'start')).toBe('42')
	})
})

describe('YouTube seeking', () => {
	it('seeks to a chosen point on a long video', () => {
		const tool = new VideoChoice({ data: { ...data, defaultProvider: 'youtube' }, readOnly: true })
		const root = tool.render(); document.body.append(root)
		const frame = root.querySelector('iframe')!
		const send = vi.spyOn(frame.contentWindow!, 'postMessage')
		window.dispatchEvent(new MessageEvent('message', { origin: 'https://www.youtube.com', source: frame.contentWindow, data: JSON.stringify({event:'infoDelivery', info:{duration:7200,currentTime:10}}) }))
		const progress = root.querySelector('[aria-label="Позиция видео"]') as HTMLInputElement
		expect(progress.style.appearance).toBe('auto')
		progress.value = '50'; progress.dispatchEvent(new Event('change'))
		expect(send).toHaveBeenCalledWith(expect.stringContaining('"args":[3600,true]'), 'https://www.youtube.com')
		expect(root.textContent).toContain('0:10 / 2:00:00')
		tool.destroy()
	})
})
