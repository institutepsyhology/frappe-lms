type SettingsUser = { name?:string; is_moderator?:boolean; is_system_manager?:boolean; staff_capabilities?:Record<string,Record<string,boolean>> } | null | undefined

export function canOpenSettings(user:SettingsUser):boolean {
	return Boolean(user?.name === 'Administrator' || user?.is_system_manager || user?.is_moderator ||
		['contacts', 'staff', 'positions'].some(resource => user?.staff_capabilities?.[resource]?.read))
}
