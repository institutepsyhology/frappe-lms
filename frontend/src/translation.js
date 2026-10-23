import { createResource } from 'frappe-ui'
import { shallowRef } from 'vue'

// EditorJS blocks mount their own Vue apps. Keep one reactive catalog so both
// those apps and the main app update when the asynchronous request completes.
const translatedMessages = shallowRef(window.translatedMessages || {})
let translationsResource

// Imperative widgets cannot react to Vue's catalog ref. Let them use the
// already-started request before constructing their controls, with source copy
// still available when the request fails. This does not delay the Vue app.
export async function waitForTranslations() {
	try {
		await translationsResource?.promise
	} catch {
		// The translator already falls back to the original message.
	}
}

export default function translationPlugin(app) {
	app.config.globalProperties.__ = translate
	window.__ = translate
	if (window.translatedMessages) {
		translatedMessages.value = window.translatedMessages
	} else {
		fetchTranslations()
	}
}

function translate(message) {
	let translatedMessage = translatedMessages.value[message] || message

	const hasPlaceholders = /{\d+}/.test(message)
	if (!hasPlaceholders) {
		return translatedMessage
	}
	return {
		format: function (...args) {
			return translatedMessage.replace(
				/{(\d+)}/g,
				function (match, number) {
					return typeof args[number] != 'undefined'
						? args[number]
						: match
				}
			)
		},
	}
}

function fetchTranslations() {
	translationsResource = createResource({
		url: 'lms.lms.api.get_translations',
		cache: 'translations',
		auto: true,
		transform: (data) => {
			const catalog =
				data && typeof data === 'object' && !Array.isArray(data) ? data : {}
			translatedMessages.value = catalog
			window.translatedMessages = catalog
			return catalog
		},
	})
}
