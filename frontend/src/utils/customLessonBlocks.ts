import { safeUrl } from '@/utils/safeUrl'

type Options = { data?: Record<string, any>; readOnly?: boolean; block?: { dispatchChange?: () => void } }

function encode(text: string): string {
	const bytes = new TextEncoder().encode(text)
	let binary = ''
	for (const byte of bytes) binary += String.fromCharCode(byte)
	return btoa(binary)
}

function decode(value: unknown): string {
	if (typeof value !== 'string' || value.length > 280000) return ''
	try {
		const binary = atob(value)
		return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)))
	} catch { return '' }
}

function label(text: string, input: HTMLElement): HTMLLabelElement {
	const element = document.createElement('label')
	element.className = 'block text-sm space-y-1'
	const title = document.createElement('span')
	title.className = 'block font-medium'
	title.textContent = text
	element.append(title, input)
	return element
}

function input(type: string, value: string): HTMLInputElement {
	const element = document.createElement('input')
	element.type = type
	element.value = value
	element.className = 'w-full rounded border border-outline-gray-2 bg-surface-base px-3 py-2 text-sm'
	return element
}

export class HtmlBlock {
	private code: string
	private height: number
	private readonly readOnly: boolean
	private readonly block?: Options['block']
	constructor({ data = {}, readOnly = false, block }: Options) {
		this.code = decode(data.encodedHtml)
		this.height = Math.min(1600, Math.max(100, Number(data.height) || 400))
		this.readOnly = readOnly
		this.block = block
	}
	static get isReadOnlySupported() { return true }
	static get toolbox() { return { title: 'HTML-код', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m8 5-6 7 6 7M16 5l6 7-6 7M14 3l-4 18"/></svg>' } }
	static get sanitize() { return { encodedHtml: false, height: false } }
	render() {
		const wrapper = document.createElement('div')
		wrapper.className = 'not-prose my-4'
		wrapper.contentEditable = 'false'
		if (this.readOnly) {
			if (this.code) {
				const frame = document.createElement('iframe')
				frame.title = 'HTML-блок урока'
				frame.setAttribute('sandbox', 'allow-scripts allow-popups')
				frame.setAttribute('referrerpolicy', 'no-referrer')
				frame.style.cssText = `width:100%;height:${this.height}px;border:0;`
				frame.srcdoc = this.code
				wrapper.append(frame)
			}
		} else {
			const area = document.createElement('textarea')
			area.value = this.code
			area.rows = 8
			area.maxLength = 40000
			area.placeholder = '<div>Вставьте HTML-код</div>'
			area.className = 'w-full rounded border border-outline-gray-2 bg-surface-base p-3 font-mono text-sm'
			area.addEventListener('input', () => { this.code = area.value; this.block?.dispatchChange?.() })
			const height = input('number', String(this.height))
			height.min = '100'; height.max = '1600'
			height.addEventListener('input', () => { this.height = Math.min(1600, Math.max(100, Number(height.value) || 400)); this.block?.dispatchChange?.() })
			wrapper.append(label('HTML-код', area), label('Высота блока, пикселей', height))
			const note = document.createElement('p')
			note.textContent = 'Код выполняется в отдельном окне внутри урока. Некоторые сторонние виджеты могут требовать специальных разрешений.'
			note.className = 'text-sm text-ink-gray-5 mt-2'
			wrapper.append(note)
		}
		return wrapper
	}
	save() { return { encodedHtml: encode(this.code), height: this.height } }
}

type ButtonData = { text: string; url: string; size: string; background: string; color: string; newTab: boolean }
const color = (value: unknown, fallback: string) => typeof value === 'string' && /^#[\da-f]{6}$/i.test(value) ? value : fallback

export class LessonButton {
	private data: ButtonData
	private readonly readOnly: boolean
	private readonly block?: Options['block']
	constructor({ data = {}, readOnly = false, block }: Options) {
		this.data = { text: typeof data.text === 'string' ? data.text : '', url: typeof data.url === 'string' ? data.url : '',
			size: ['small', 'medium', 'large'].includes(data.size) ? data.size : 'medium',
			background: color(data.background, '#2563eb'), color: color(data.color, '#ffffff'), newTab: data.newTab !== false }
		this.readOnly = readOnly; this.block = block
	}
	static get isReadOnlySupported() { return true }
	static get toolbox() { return { title: 'Кнопка-ссылка', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="M7 12h10"/></svg>' } }
	static get sanitize() { return { text: false, url: false, size: false, background: false, color: false, newTab: false } }
	render() {
		const wrapper = document.createElement('div')
		wrapper.className = 'not-prose my-4 space-y-3'; wrapper.contentEditable = 'false'
		const preview = document.createElement('a')
		const refresh = () => {
			preview.textContent = this.data.text || 'Кнопка'
			const url = safeUrl(this.data.url)
			if (this.readOnly && url) preview.href = url; else preview.removeAttribute('href')
			if (this.data.newTab) { preview.target = '_blank'; preview.rel = 'noopener noreferrer' }
			else { preview.removeAttribute('target'); preview.removeAttribute('rel') }
			const sizes: Record<string, string> = { small: '8px 14px; font-size:14px', medium: '12px 20px; font-size:16px', large: '16px 28px; font-size:20px' }
			preview.style.cssText = `display:inline-block;border-radius:8px;text-decoration:none;background:${this.data.background};color:${this.data.color};padding:${sizes[this.data.size]};`
		}
		if (!this.readOnly) {
			const fields = document.createElement('div'); fields.className = 'rounded-lg border p-3 space-y-3'
			for (const [key, title, type] of [['text', 'Текст кнопки', 'text'], ['url', 'Ссылка', 'url'], ['background', 'Цвет кнопки', 'color'], ['color', 'Цвет текста', 'color']] as const) {
				const field = input(type, this.data[key])
				field.addEventListener('input', () => { this.data[key] = field.value; refresh(); this.block?.dispatchChange?.() })
				fields.append(label(title, field))
			}
			const size = document.createElement('select'); size.className = 'rounded border p-2'
			for (const [value, title] of [['small', 'Маленькая'], ['medium', 'Средняя'], ['large', 'Большая']]) { const option = document.createElement('option'); option.value = value; option.textContent = title; size.append(option) }
			size.value = this.data.size
			size.addEventListener('change', () => { this.data.size = size.value; refresh(); this.block?.dispatchChange?.() })
			const newTab = input('checkbox', ''); newTab.checked = this.data.newTab; newTab.className = 'mr-2'
			newTab.addEventListener('change', () => { this.data.newTab = newTab.checked; refresh(); this.block?.dispatchChange?.() })
			fields.append(label('Размер', size), label('Открывать в новом окне', newTab)); wrapper.append(fields)
		}
		refresh(); wrapper.append(preview); return wrapper
	}
	save() { return { ...this.data, url: safeUrl(this.data.url) || '' } }
}
