type SpacerData = { height: number; width: number; marginTop: number; marginBottom: number; color: string }
type Options = { data?: Record<string, unknown>; readOnly?: boolean; block?: { dispatchChange?: () => void } }

const numberInRange = (value: unknown, fallback: number, max: number): number =>
	typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max ? value : fallback
const safeColor = (value: unknown): string =>
	typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : '#c8c8c8'

/** A visual separator with bounded, explicitly validated CSS values. */
export class LessonSpacer {
	private data: SpacerData
	private readonly readOnly: boolean
	private readonly block?: Options['block']
	constructor({ data = {}, readOnly = false, block }: Options) {
		this.data = { height: numberInRange(data.height, 6, 500), width: numberInRange(data.width, 100, 100),
			marginTop: numberInRange(data.marginTop, 10, 500), marginBottom: numberInRange(data.marginBottom, 10, 500),
			color: safeColor(data.color) }
		this.readOnly = readOnly
		this.block = block
	}
	static get isReadOnlySupported() { return true }
	static get toolbox() { return { title: 'Разделитель', icon: '<svg width="20" height="20" viewBox="0 0 24 24"><path d="M3 12h18" stroke="currentColor" stroke-width="2"/></svg>' } }
	static get sanitize() { return { height: false, width: false, marginTop: false, marginBottom: false, color: false } }
	render() {
		const root = document.createElement('div')
		root.contentEditable = 'false'
		const line = document.createElement('div')
		line.dataset.spacer = 'true'
		const refresh = () => {
			line.style.height = `${this.data.height}px`
			line.style.width = `${this.data.width}%`
			line.style.margin = `${this.data.marginTop}px auto ${this.data.marginBottom}px`
			line.style.backgroundColor = this.data.color
		}
		if (!this.readOnly) {
			const panel = document.createElement('div')
			panel.className = 'flex flex-wrap gap-3 text-sm'
			const fields = [['height', 'Высота, px', 500], ['width', 'Ширина, %', 100],
				['marginTop', 'Отступ сверху, px', 500], ['marginBottom', 'Отступ снизу, px', 500]] as const
			for (const [key, caption, max] of fields) {
				const label = document.createElement('label')
				label.textContent = caption + ' '
				const input = document.createElement('input')
				input.type = 'number'; input.min = '0'; input.max = String(max); input.value = String(this.data[key])
				input.className = 'w-20 rounded border p-1'
				input.addEventListener('input', () => { this.data[key] = numberInRange(input.valueAsNumber, this.data[key], max); refresh(); this.block?.dispatchChange?.() })
				label.append(input); panel.append(label)
			}
			const label = document.createElement('label'); label.textContent = 'Цвет '
			const input = document.createElement('input'); input.type = 'color'; input.value = this.data.color
			input.addEventListener('input', () => { this.data.color = safeColor(input.value); refresh(); this.block?.dispatchChange?.() })
			label.append(input); panel.append(label); root.append(panel)
		}
		refresh(); root.append(line); return root
	}
	save(): SpacerData { return { ...this.data } }
}
