type VideoProvider = 'rutube' | 'youtube'

interface VideoChoiceData {
	rutube: string
	youtube: string
	defaultProvider: VideoProvider
}

interface VideoChoiceOptions {
	data?: Partial<VideoChoiceData>
	readOnly?: boolean
	api?: unknown
	block?: { dispatchChange?: () => void }
}

const PROVIDERS: VideoProvider[] = ['rutube', 'youtube']
const LABELS: Record<VideoProvider, string> = { rutube: 'Rutube', youtube: 'YouTube' }
const PROVIDER_PREFERENCE_KEY = 'lms-video-provider-preference'

// Source pages are accepted while authoring, but only exact, known player URLs
// ever reach an iframe. Drop unrelated query parameters; retain a private Rutube
// video's access key without exposing it in labels, errors, or outgoing links.
export function normalizeVideoUrl(provider: VideoProvider, source?: string): string {
	if (typeof source !== 'string') return ''
	const value = source.trim()
	if (!value || value.length > 4096 || /[\u0000-\u0020\u007f\\]/.test(value)) return ''
	let url: URL
	try {
		url = new URL(value)
	} catch {
		return ''
	}
	if (url.protocol !== 'https:' || url.username || url.password || url.port) return ''
	const host = url.hostname.toLowerCase()
	if (provider === 'youtube') {
		let id = ''
		if (host === 'youtu.be') {
			id = url.pathname.match(/^\/([A-Za-z0-9_-]{11})\/?$/)?.[1] ?? ''
		} else if (['youtube.com', 'www.youtube.com', 'm.youtube.com'].includes(host)) {
			if (url.pathname === '/watch' && url.searchParams.getAll('v').length === 1) {
				id = url.searchParams.get('v') ?? ''
			} else {
				id = url.pathname.match(/^\/(?:embed|shorts|v)\/([A-Za-z0-9_-]{11})\/?$/)?.[1] ?? ''
			}
		} else if (['youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(host)) {
			id = url.pathname.match(/^\/embed\/([A-Za-z0-9_-]{11})\/?$/)?.[1] ?? ''
		}
		return /^[A-Za-z0-9_-]{11}$/.test(id) ? `https://www.youtube.com/embed/${id}` : ''
	}
	if (provider !== 'rutube' || !['rutube.ru', 'www.rutube.ru'].includes(host)) return ''
	const match = url.pathname.match(/^\/(?:video\/(private\/)?|play\/embed\/)([a-f0-9]{32})\/?$/i)
	if (!match || url.searchParams.getAll('p').length > 1) return ''
	const key = url.searchParams.get('p')
	if ((match[1] && !key) || (key !== null && !/^[A-Za-z0-9_-]+$/.test(key))) return ''
	return `https://rutube.ru/play/embed/${match[2].toLowerCase()}/${key ? `?p=${encodeURIComponent(key)}` : ''}`
}

// EditorJS tools build DOM outside Vue. Use textContent/DOM attributes throughout
// so the author-supplied URLs never become markup.
export class VideoChoice {
	private data: VideoChoiceData
	private readonly readOnly: boolean
	private readonly block?: VideoChoiceOptions['block']
	private wrapper?: HTMLDivElement
	private playerHost?: HTMLDivElement
	private frame?: HTMLIFrameElement
	private cleanupPlayer?: () => void
	private displayedSource: string | undefined
	private activeProvider: VideoProvider
	private buttons = new Map<VideoProvider, HTMLButtonElement>()
	private inputs = new Map<VideoProvider, HTMLInputElement>()
	private errors = new Map<VideoProvider, HTMLDivElement>()

	constructor({ data = {}, readOnly = false, block }: VideoChoiceOptions) {
		this.data = {
			rutube: typeof data.rutube === 'string' ? data.rutube : '',
			youtube: typeof data.youtube === 'string' ? data.youtube : '',
			defaultProvider: data.defaultProvider === 'youtube' ? 'youtube' : 'rutube',
		}
		this.readOnly = readOnly
		this.block = block
		this.activeProvider = this.data.defaultProvider
		if (readOnly) {
			try {
				const preferred = localStorage.getItem(PROVIDER_PREFERENCE_KEY)
				if (preferred === 'youtube' || preferred === 'rutube') this.activeProvider = preferred
			} catch { /* Browser storage may be unavailable. */ }
		}
	}

	static get isReadOnlySupported() {
		return true
	}

	static get toolbox() {
		return {
			title: __('Видео с выбором источника'),
			icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m10 8 6 4-6 4V8Z"/></svg>',
		}
	}

	// Only plain strings are stored. URL validation is applied again both on
// save and immediately before rendering, including for hand-authored payloads.
	static get sanitize() {
		return { rutube: false, youtube: false, defaultProvider: false }
	}

	render() {
		if (this.wrapper) return this.wrapper
		this.wrapper = document.createElement('div')
		this.wrapper.className = 'video-choice not-prose mb-5'
		this.wrapper.contentEditable = 'false'
		if (!this.readOnly) this.renderFields()
		const label = document.createElement('div')
		label.textContent = __('Выберите, где смотреть видео')
		label.className = 'text-sm font-medium mb-2'
		this.wrapper.append(label)
		const choices = document.createElement('div')
		choices.className = 'flex flex-wrap gap-2 mb-3'
		choices.setAttribute('role', 'group')
		choices.setAttribute('aria-label', __('Источник видео'))
		for (const provider of PROVIDERS) {
			const button = document.createElement('button')
			button.type = 'button'
			button.textContent = LABELS[provider]
			button.dataset.provider = provider
			button.addEventListener('click', () => {
				this.activeProvider = provider
				if (this.readOnly) {
					try { localStorage.setItem(PROVIDER_PREFERENCE_KEY, provider) } catch { /* Playback remains available. */ }
				}
				this.refreshPlayer()
			})
			this.buttons.set(provider, button)
			choices.append(button)
		}
		this.wrapper.append(choices)
		this.playerHost = document.createElement('div')
		this.playerHost.className = 'video-choice-player overflow-hidden rounded-lg bg-black'
		this.playerHost.style.aspectRatio = '16 / 9'
		this.wrapper.append(this.playerHost)
		this.refreshPlayer()
		return this.wrapper
	}

	private renderFields() {
		const fields = document.createElement('div')
		fields.className = 'rounded-lg border p-3 mb-4 space-y-3 bg-surface-gray-1'
		for (const provider of PROVIDERS) {
			const label = document.createElement('label')
			label.className = 'block text-sm'
			const title = document.createElement('span')
			title.textContent = `${__('Ссылка на видео')} ${LABELS[provider]}`
			title.className = 'block font-medium mb-1'
			const input = document.createElement('input')
			input.type = 'url'
			input.value = this.data[provider]
			input.placeholder = provider === 'rutube' ? 'https://rutube.ru/video/…' : 'https://youtu.be/…'
			input.className = 'w-full rounded border border-outline-gray-2 bg-surface-base px-3 py-2 text-sm'
			input.autocomplete = 'off'
			input.spellcheck = false
			input.dataset.provider = provider
			const error = document.createElement('div')
			error.className = 'text-sm text-ink-red-3 mt-1'
			error.setAttribute('role', 'status')
			input.addEventListener('input', () => {
				this.data[provider] = input.value
				this.refreshPlayer()
				this.block?.dispatchChange?.()
			})
			this.inputs.set(provider, input)
			this.errors.set(provider, error)
			label.append(title, input, error)
			fields.append(label)
		}
		const defaultLabel = document.createElement('label')
		defaultLabel.className = 'block text-sm'
		const defaultText = document.createElement('span')
		defaultText.textContent = __('Источник по умолчанию')
		defaultText.className = 'block font-medium mb-1'
		const select = document.createElement('select')
		select.className = 'rounded border border-outline-gray-2 bg-surface-base px-3 py-2 text-sm'
		for (const provider of PROVIDERS) {
			const option = document.createElement('option')
			option.value = provider
			option.textContent = LABELS[provider]
			select.append(option)
		}
		select.value = this.data.defaultProvider
		select.addEventListener('change', () => {
			this.data.defaultProvider = select.value === 'youtube' ? 'youtube' : 'rutube'
			this.activeProvider = this.data.defaultProvider
			this.refreshPlayer()
			this.block?.dispatchChange?.()
		})
		defaultLabel.append(defaultText, select)
		fields.append(defaultLabel)
		this.wrapper!.append(fields)
	}

	private refreshPlayer() {
		const sources = this.save()
		if (!sources[this.activeProvider]) {
			this.activeProvider = PROVIDERS.find((provider) => sources[provider]) ?? this.data.defaultProvider
		}
		for (const provider of PROVIDERS) {
			const available = Boolean(sources[provider])
			const selected = available && this.activeProvider === provider
			const button = this.buttons.get(provider)
			if (button) {
				button.disabled = !available
				button.setAttribute('aria-pressed', String(selected))
				button.className = selected
					? 'rounded-md border px-4 py-2 text-sm font-medium'
					: 'rounded-md border border-outline-gray-2 bg-surface-base text-ink-gray-9 px-4 py-2 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed'
				button.style.backgroundColor = selected ? '#111827' : ''
				button.style.borderColor = selected ? '#111827' : ''
				button.style.color = selected ? '#ffffff' : ''
			}
			const invalid = Boolean(this.data[provider].trim()) && !available
			this.inputs.get(provider)?.setAttribute('aria-invalid', String(invalid))
			const error = this.errors.get(provider)
			if (error) {
				error.textContent = invalid
					? provider === 'rutube'
						? __('Проверьте ссылку Rutube. Для закрытого видео сохраните параметр p.')
						: __('Проверьте ссылку YouTube на отдельное видео.')
					: ''
			}
		}
		const source = sources[this.activeProvider]
		if (!this.playerHost || this.displayedSource === source) return
		this.displayedSource = source
		this.cleanupPlayer?.()
		this.cleanupPlayer = undefined
		// Removing the old browsing context stops its playback before the next
		// source is loaded; hiding two live players would leave sound playing.
		this.frame?.remove()
		this.frame = undefined
		this.playerHost.replaceChildren()
		if (!source) {
			const message = document.createElement('div')
			message.className = 'flex items-center justify-center h-full p-5 text-sm text-white'
			message.textContent = __('Видео пока недоступно.')
			this.playerHost.append(message)
			return
		}
		const frame = document.createElement('iframe')
		frame.src = source
		if (this.readOnly) this.attachResume(frame, source, this.activeProvider)
		frame.title = `${__('Видео')} — ${LABELS[this.activeProvider]}`
		frame.className = 'w-full h-full border-0'
		frame.setAttribute('width', '100%')
		frame.setAttribute('height', '100%')
		frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation')
		frame.setAttribute('allow', 'autoplay; fullscreen; picture-in-picture; encrypted-media')
		frame.setAttribute('allowfullscreen', '')
		frame.referrerPolicy = 'strict-origin-when-cross-origin'
		frame.loading = 'lazy'
		this.frame = frame
		if (!this.readOnly || this.activeProvider === 'rutube') {
			this.playerHost.append(frame)
			return
		}
		this.attachProtectedPlayer(frame, this.activeProvider)
	}



	private attachResume(frame: HTMLIFrameElement, source: string, provider: VideoProvider) {
		const url = new URL(source)
		const id = url.pathname.split('/').filter(Boolean).pop()
		if (!id) return
		const key = `lms-video-position:${provider}:${id}`
		let saved = 0
		try { saved = Number(localStorage.getItem(key)) || 0 } catch { /* storage may be unavailable */ }
		if (Number.isFinite(saved) && saved >= 10) {
			url.searchParams.set(provider === 'youtube' ? 'start' : 't', String(Math.floor(saved)))
			frame.src = url.toString()
		}
		const origin = provider === 'youtube' ? 'https://www.youtube.com' : 'https://rutube.ru'
		let readyToSave = saved < 10
		const onMessage = (event: MessageEvent) => {
			if (event.origin !== origin || event.source !== frame.contentWindow) return
			let message = event.data
			if (typeof message === 'string') { try { message = JSON.parse(message) } catch { return } }
			if (!message || typeof message !== 'object') return
			const time = provider === 'youtube' && message.event === 'infoDelivery'
				? message.info?.currentTime : provider === 'rutube' && message.type === 'player:currentTime'
					? message.data?.time : undefined
			if (typeof time !== 'number' || !Number.isFinite(time) || time < 0) return
			// Ignore early pre-seek events until the saved position is reached.
			if (!readyToSave) {
				if (Math.abs(time - saved) > 5) return
				readyToSave = true
			}
			try { localStorage.setItem(key, String(Math.floor(time))) } catch { /* playback still works */ }
		}
		window.addEventListener('message', onMessage)
		this.cleanupPlayer = () => window.removeEventListener('message', onMessage)
	}

	private attachProtectedPlayer(frame: HTMLIFrameElement, provider: VideoProvider) {
		const host = this.playerHost!
		const url = new URL(frame.src)
		if (provider === 'youtube') {
			url.searchParams.set('enablejsapi', '1')
			url.searchParams.set('origin', window.location.origin)
			url.searchParams.set('controls', '0')
			url.searchParams.set('rel', '0')
		}
		frame.src = url.toString()
		frame.tabIndex = -1
		host.style.position = 'relative'
		const cover = document.createElement('button')
		cover.type = 'button'
		cover.setAttribute('aria-label', 'Воспроизвести или приостановить видео')
		cover.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;background:transparent;border:0;cursor:pointer'
		const controls = document.createElement('div')
		controls.style.cssText = 'position:absolute;bottom:0;left:0;right:0;display:flex;align-items:center;gap:8px;background:#111;color:white;padding:8px;z-index:2'
		let playing = false, current = 0, duration = 0
		const origin = provider === 'youtube' ? 'https://www.youtube.com' : 'https://rutube.ru'
		const send = (command: string, data: Record<string, unknown> = {}, args: unknown[] = []) => {
			const payload = provider === 'youtube' ? {event: 'command', func: command, args} : {type: command, data}
			frame.contentWindow?.postMessage(JSON.stringify(payload), origin)
		}
		const button = (title: string, action: () => void) => {
			const el = document.createElement('button'); el.type = 'button'; el.textContent = title
			el.setAttribute('aria-label', title); el.style.cssText = 'color:white;white-space:nowrap;padding:4px'
			el.addEventListener('click', action); controls.append(el); return el
		}
		const play = button('▶', () => toggle())
		const toggle = () => { send(provider === 'youtube' ? (playing ? 'pauseVideo' : 'playVideo') : (playing ? 'player:pause' : 'player:play')); playing = !playing; play.textContent = playing ? '❚❚' : '▶'; play.setAttribute('aria-label', playing ? 'Пауза' : 'Воспроизвести') }
		cover.addEventListener('click', toggle)
		const seek = (time: number) => send(provider === 'youtube' ? 'seekTo' : 'player:setCurrentTime', {time}, [time, true])
		button('−10 с', () => provider === 'rutube' ? send('player:relativelySeek', {time: -10}) : seek(Math.max(0, current - 10)))
		button('+10 с', () => provider === 'rutube' ? send('player:relativelySeek', {time: 10}) : seek(Math.min(duration || Infinity, current + 10)))
		const progress = document.createElement('input'); progress.type = 'range'; progress.min = '0'; progress.max = '100'; progress.value = '0'; progress.style.cssText = 'appearance:auto;-webkit-appearance:auto;flex:1;min-width:60px;height:16px;accent-color:#f97316;cursor:pointer'; progress.setAttribute('aria-label', 'Позиция видео')
		progress.addEventListener('change', () => { if (duration) seek(Number(progress.value) * duration / 100) }); controls.append(progress)
		const clock = document.createElement('span'); clock.style.cssText = 'font-size:12px;white-space:nowrap'; clock.textContent = '0:00 / 0:00'; controls.append(clock)
		const formatTime = (seconds: number) => { const total = Math.max(0, Math.floor(seconds)); const h = Math.floor(total / 3600); const m = Math.floor(total / 60) % 60; const sec = String(total % 60).padStart(2, '0'); return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}` }
		const volume = document.createElement('input'); volume.type = 'range'; volume.min = '0'; volume.max = '100'; volume.value = '100'; volume.style.width = '65px'; volume.setAttribute('aria-label', 'Громкость')
		volume.addEventListener('input', () => send(provider === 'youtube' ? 'setVolume' : 'player:setVolume', {volume: Number(volume.value) / 100}, [Number(volume.value)])); controls.append(volume)
		if (provider === 'youtube') {
			const speed = document.createElement('select'); speed.setAttribute('aria-label', 'Скорость воспроизведения'); speed.style.cssText = 'background:#111;color:white'
			for (const rate of [0.5, 0.75, 1, 1.25, 1.5, 2]) { const option = document.createElement('option'); option.value = String(rate); option.textContent = `${rate}x`; speed.append(option) }
			speed.value = '1'; speed.addEventListener('change', () => send('setPlaybackRate', {}, [Number(speed.value)])); controls.append(speed)
		}
		button('⛶', () => { void host.requestFullscreen?.() })
		const onMessage = (event: MessageEvent) => {
			if (event.source !== frame.contentWindow || event.origin !== origin) return
			let message = event.data
			if (typeof message === 'string') { try { message = JSON.parse(message) } catch { return } }
			if (!message || typeof message !== 'object') return
			if (provider === 'rutube') {
				if (message.type === 'player:changeState' && ['playing', 'paused', 'stopped'].includes(message.data?.state)) playing = message.data.state === 'playing'
				if (message.type === 'player:currentTime') current = Number(message.data?.time) || 0
				if (message.type === 'player:durationChange') duration = Number(message.data?.duration) || 0
			} else if (message.event === 'infoDelivery') {
				const info = message.info || {}; if ([0, 1, 2].includes(info.playerState)) playing = info.playerState === 1
				if (typeof info.currentTime === 'number') current = info.currentTime
				if (typeof info.duration === 'number') duration = info.duration
			}
			play.textContent = playing ? '❚❚' : '▶'; play.setAttribute('aria-label', playing ? 'Пауза' : 'Воспроизвести')
			if (duration) progress.value = String(current / duration * 100)
			clock.textContent = `${formatTime(current)} / ${formatTime(duration)}`
		}
		window.addEventListener('message', onMessage)
		frame.addEventListener('load', () => { if (provider === 'youtube') frame.contentWindow?.postMessage(JSON.stringify({event:'listening', id: 1}), origin) })
		host.append(frame, cover, controls)
		const cleanupResume = this.cleanupPlayer
		this.cleanupPlayer = () => { cleanupResume?.(); window.removeEventListener('message', onMessage) }
	}

	save(): VideoChoiceData {
		return {
			rutube: normalizeVideoUrl('rutube', this.data.rutube),
			youtube: normalizeVideoUrl('youtube', this.data.youtube),
			defaultProvider: this.data.defaultProvider,
		}
	}

	destroy() {
		this.cleanupPlayer?.()
		this.frame?.remove()
		this.frame = undefined
		this.playerHost?.replaceChildren()
	}
}
