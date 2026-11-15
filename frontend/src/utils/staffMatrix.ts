export type StaffPermission = { resource: string; action: string }

export const staffResources: Record<string, string> = {
	contacts: 'Карточки контактов', course_access: 'Доступы к курсам и урокам',
	staff: 'Сотрудники', positions: 'Должности', credentials: 'Пароли и письма с доступом',
}
export const staffActions: Record<string, string> = {
	read: 'Просмотр', create: 'Создание', write: 'Редактирование', delete: 'Удаление',
	remove: 'Закрытие доступа', send: 'Отправка письма с доступом',
}
export const staffNativeRoles: Record<string, string> = {
	'LMS Student': 'Ученик', 'Course Creator': 'Автор курсов',
	'Batch Evaluator': 'Проверяющий задания', Moderator: 'Модератор обучения',
}

export function toggleStaffPermission(rows: StaffPermission[], resource: string, action: string, enabled: boolean) {
	const selected = rows.filter(row => !(row.resource === resource && row.action === action))
	if (enabled) selected.push({ resource, action })
	if (resource !== 'credentials' && action !== 'read' && enabled &&
		!selected.some(row => row.resource === resource && row.action === 'read')) {
		selected.push({ resource, action: 'read' })
	}
	if (resource !== 'credentials' && action === 'read' && !enabled) {
		return selected.filter(row => row.resource !== resource)
	}
	return selected
}
