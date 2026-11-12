import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { canonicalAvoCourseRoute } from '@/utils/avoCourseRoutes'
import { routes } from '@/routes'

const { callMock } = vi.hoisted(() => ({ callMock:vi.fn() }))
vi.mock('frappe-ui', () => ({ call:callMock }))
vi.mock('@/pages/Courses/CourseDetail.vue', () => ({ default: { props:['courseName'], template:'<div data-testid="course">{{ courseName }}</div>' } }))
vi.mock('@/pages/Lesson.vue', () => ({ default: { props:['courseName','chapterNumber','lessonNumber'], template:'<div data-testid="lesson">{{ courseName }}:{{ chapterNumber }}-{{ lessonNumber }}</div>' } }))
import AvoCourseRoute from '@/pages/Courses/AvoCourseRoute.vue'

describe('AVO course and lesson URLs', () => {
	it('matches the actual routes using both source IDs', () => {
		const router=createRouter({ history:createMemoryHistory(), routes })
		expect(router.resolve('/courses/avo/11').name).toBe('AvoCourse')
		expect(router.resolve('/courses/avo/11/lessons/26').name).toBe('AvoLesson')
	})
	it('resolves a direct lesson URL and reloads on another ID', async () => {
		callMock.mockResolvedValueOnce({course_name:'course-a',chapter_number:2,lesson_number:3})
		const wrapper=mount(AvoCourseRoute,{props:{avoCourseId:'11',avoLessonId:'26'}})
		await flushPromises()
		expect(wrapper.get('[data-testid=lesson]').text()).toBe('course-a:2-3')
		callMock.mockResolvedValueOnce(null)
		await wrapper.setProps({avoLessonId:'27'});await flushPromises()
		expect(wrapper.find('[data-testid=lesson]').exists()).toBe(false)
		expect(wrapper.get('[role=alert]').text()).toContain('нет доступа')
	})
	it('canonicalises old lesson links while retaining query and editor hash', async () => {
		const to:any={name:'Lesson',params:{courseName:'course-a',chapterNumber:'2',lessonNumber:'3'},query:{studentView:'1'},hash:'#editor'}
		const call=vi.fn().mockResolvedValue({course_id:'11',lesson_id:'26'})
		expect(await canonicalAvoCourseRoute(to,call)).toEqual({name:'AvoLesson',params:{avoCourseId:'11',avoLessonId:'26'},query:to.query,hash:'#editor'})
		expect(call).toHaveBeenCalledWith('lms.lms.avo_course_routes.canonical',{course_name:'course-a',chapter_number:'2',lesson_number:'3'})
	})
	it('preserves old or non-AVO links on errors and ignores unrelated routes', async () => {
		const call=vi.fn().mockRejectedValue(new Error('offline'))
		const course:any={name:'CourseDetail',params:{courseName:'normal-course'},query:{},hash:''}
		expect(await canonicalAvoCourseRoute(course,call)).toBeNull()
		expect(await canonicalAvoCourseRoute({...course,name:'ChapterForm'},call)).toBeNull()
		expect(call).toHaveBeenCalledTimes(1)
	})
	it('keeps the catalogue in browser history after canonicalisation', async () => {
		const router=createRouter({history:createMemoryHistory(),routes:[
			{path:'/catalog',name:'Courses',component:{}},
			{path:'/courses/:courseName',name:'CourseDetail',component:{}},
			{path:'/courses/avo/:avoCourseId',name:'AvoCourse',component:{}},
		]})
		router.beforeEach(async to => (await canonicalAvoCourseRoute(to,vi.fn().mockResolvedValue({course_id:'11'}))) || undefined)
		await router.push('/catalog');await router.isReady();await router.push('/courses/legacy')
		expect(router.currentRoute.value.path).toBe('/courses/avo/11')
		const arrived=new Promise<void>(resolve => { const off=router.afterEach(() => { off();resolve() }) })
		router.back();await arrived
		expect(router.currentRoute.value.path).toBe('/catalog')
	})
})
