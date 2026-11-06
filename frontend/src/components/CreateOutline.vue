<template>
	<div v-if="course">
		<div v-safe-html:titlelabel="course.title" class="text-2xl-semibold" />
		<div v-if="course.chapters.length">
			{{ course.chapters }}
		</div>
		<div v-else class="border bg-surface-base rounded-md p-5 text-center mt-4">
			<div>
				{{
					__(
						'There are no chapters in this course. Create and manage chapters from here.'
					)
				}}
			</div>
			<Button class="mt-4">
				{{ __('Add Chapter') }}
			</Button>
		</div>
	</div>
</template>
<script setup>
const props = defineProps({
	course: {
		type: Object,
		default: {},
	},
})
</script>
