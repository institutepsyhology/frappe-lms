import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))
vi.mock('frappe-ui', () => ({ call: callMock }))
vi.mock('@/pages/Forms/MemberForm.vue', () => ({ default: { props:['memberID'], template:'<div data-testid="member">{{ memberID }}</div>' } }))
import AvoContactById from '@/pages/Forms/AvoContactById.vue'

describe('AVO contact URL', () => {
	it('resolves a User on a direct ID URL', async () => {
		callMock.mockResolvedValueOnce({kind:'User',name:'user@example.test'})
		const wrapper = mount(AvoContactById, { props:{avoId:'123'} })
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.avo_contact_card.resolve_source_id', {source_id:'123'})
		expect(wrapper.get('[data-testid=member]').text()).toBe('user@example.test')
	})
	it('opens contacts without a User and fails closed on errors', async () => {
		callMock.mockResolvedValueOnce({kind:'Contact',name:'internal-contact'})
		const wrapper = mount(AvoContactById, { props:{avoId:'456'} })
		await flushPromises()
		expect(wrapper.get('[data-testid=member]').text()).toBe('avo-contact:internal-contact')
		callMock.mockRejectedValueOnce(new Error('ambiguous'))
		await wrapper.setProps({avoId:'457'})
		await flushPromises()
		expect(wrapper.find('[data-testid=member]').exists()).toBe(false)
		expect(wrapper.get('[role=alert]').text()).toContain('Не удалось открыть')
	})
})
