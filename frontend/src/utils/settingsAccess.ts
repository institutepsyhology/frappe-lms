type SettingsUser = { name?:string; is_moderator?:boolean; is_system_manager?:boolean } | null | undefined

export function canOpenSettings(user:SettingsUser):boolean {
	return Boolean(user?.name === 'Administrator' || user?.is_system_manager || user?.is_moderator)
}
