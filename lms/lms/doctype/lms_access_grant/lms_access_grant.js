frappe.ui.form.on('LMS Access Grant', {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role('System Manager')) return
		frm.dashboard.set_headline_alert('Карточка влияет на доступ только после включения индивидуальных правил для сайта и курса.', 'orange')

		const run = (method, args = {}) => frappe.call({
			method: `lms.lms.access_actions.${method}`,
			args: { name: frm.doc.name, ...args },
			freeze: true,
			callback: () => frm.reload_doc(),
		})

		if (frm.doc.status === 'Active') {
			frm.add_custom_button('Заморозить доступ', () => {
				frappe.confirm('Заморозить доступ? Прогресс и домашние задания сохранятся.',
					() => run('freeze_grant'))
			})
		}
		if (frm.doc.status === 'Frozen') {
			frm.add_custom_button('Возобновить доступ', () => {
				frappe.prompt([{
					fieldname: 'extend', fieldtype: 'Select', label: 'Что сделать со сроком доступа?',
					options: ['', 'Продлить на время заморозки', 'Не продлевать'], reqd: 1,
				}], ({ extend }) => run('resume_grant', {
					extend_personal_end: extend === 'Продлить на время заморозки' ? 1 : 0,
				}), 'Возобновить доступ', 'Возобновить')
			})
		}
		if (['Active', 'Frozen', 'Limited'].includes(frm.doc.status)) {
			frm.add_custom_button('Закрыть эту карточку доступа', () => {
				frappe.confirm('Закрыть эту карточку? Прогресс и домашние задания сохранятся. Другие действующие карточки этого ученика не изменятся.',
					() => run('revoke_grant'))
			})
		}
	},
})
