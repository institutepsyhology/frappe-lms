import { describe, expect, it, vi } from 'vitest'
import { HtmlBlock, LessonButton } from '@/utils/customLessonBlocks'

describe('lesson HTML and button blocks', () => {
	it('preserves Unicode HTML and runs it in an isolated iframe', () => {
		const changed = vi.fn()
		const editor = new HtmlBlock({ block: { dispatchChange: changed } })
		const fields = editor.render()
		const area = fields.querySelector('textarea')!
		area.value = '<h1>Привет</h1><script>document.body.dataset.ready="yes"</script>'
		area.dispatchEvent(new Event('input'))
		const saved = editor.save()
		expect(saved.encodedHtml).not.toContain('<script>')
		expect(changed).toHaveBeenCalled()
		const frame = new HtmlBlock({ data: saved, readOnly: true }).render().querySelector('iframe')!
		expect(frame.srcdoc).toContain('<h1>Привет</h1>')
		expect(frame.getAttribute('sandbox')).toContain('allow-scripts')
		expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin')
	})

	it('renders a configured button and rejects unsafe links', () => {
		const data = { text: 'Скачать', url: 'https://example.org/audio.mp3', size: 'large', background: '#123456', color: '#ffffff', newTab: true }
		const link = new LessonButton({ data, readOnly: true }).render().querySelector('a')!
		expect(link.textContent).toBe('Скачать')
		expect(link.getAttribute('href')).toBe(data.url)
		expect(link.target).toBe('_blank')
		expect(link.rel).toContain('noopener')
		expect(link.style.background).toBe('rgb(18, 52, 86)')
		const unsafe = new LessonButton({ data: { ...data, url: 'javascript:alert(1)' }, readOnly: true }).render().querySelector('a')!
		expect(unsafe.hasAttribute('href')).toBe(false)
	})
})
