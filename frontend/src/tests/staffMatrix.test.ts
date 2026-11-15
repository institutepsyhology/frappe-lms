import { describe, expect, it } from 'vitest'
import { toggleStaffPermission } from '@/utils/staffMatrix'

describe('staff permission dependencies', () => {
	it('adds read when granting a mutation and removes mutations when read is revoked', () => {
		const rows=toggleStaffPermission([], 'staff', 'create', true)
		expect(rows).toEqual([{resource:'staff',action:'create'},{resource:'staff',action:'read'}])
		expect(toggleStaffPermission(rows,'staff','read',false)).toEqual([])
	})
	it('sending access does not automatically reveal the password', () => {
		expect(toggleStaffPermission([],'credentials','send',true)).toEqual([{resource:'credentials',action:'send'}])
	})
	it('does not mutate the previous matrix or duplicate an existing cell', () => {
		const original=[{resource:'contacts',action:'read'}]
		const rows=toggleStaffPermission(original,'contacts','read',true)
		expect(original).toEqual([{resource:'contacts',action:'read'}]);expect(rows).toHaveLength(1)
	})
})
