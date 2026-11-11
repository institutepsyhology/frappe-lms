import { describe, expect, it } from 'vitest'
import { canOpenSettings } from '@/utils/settingsAccess'

describe('access to settings',() => {
	it('includes system managers even without the moderator role',() => {
		expect(canOpenSettings({name:'manager',is_system_manager:true,is_moderator:false})).toBe(true)
		expect(canOpenSettings({name:'Administrator'})).toBe(true)
		expect(canOpenSettings({name:'moderator',is_moderator:true})).toBe(true)
		expect(canOpenSettings({name:'student'})).toBe(false)
	})
})
