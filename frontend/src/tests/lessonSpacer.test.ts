import { describe, expect, it } from 'vitest'
import { LessonSpacer } from '../utils/lessonSpacer'

describe('lesson spacer', () => {
	it('renders the stored dimensions and colour and round-trips them', () => {
		const data = { height: 6, width: 100, marginTop: 10, marginBottom: 10, color: '#c8c8c8' }
		const tool = new LessonSpacer({ data, readOnly: true })
		const line = tool.render().querySelector('[data-spacer]') as HTMLElement
		expect(line.style.height).toBe('6px')
		expect(line.style.width).toBe('100%')
		expect(line.style.marginTop).toBe('10px')
		expect(line.style.marginBottom).toBe('10px')
		expect(line.style.backgroundColor).toBe('rgb(200, 200, 200)')
		expect(tool.save()).toEqual(data)
	})

	it('never inserts unsafe CSS from imported or hand-edited data', () => {
		const tool = new LessonSpacer({ data: { height: '1px;display:none', color: 'url(https://bad.test)' }, readOnly: true })
		const line = tool.render().querySelector('[data-spacer]') as HTMLElement
		expect(line.getAttribute('style')).not.toContain('bad.test')
		expect(tool.save().height).toBe(6)
	})
})
