import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { canonicalAvoCourseRoute, courseCardRoute } from '@/utils/avoCourseRoutes'
import { routes, getSiteRoutes } from '@/routes'

const { callMock } = vi.hoisted(() => ({ callMock:vi.fn() }))
vi.mock('frappe-ui', () => ({ call:callMock }))
vi.mock('@/pages/Courses/CourseDetail.vue', () => ({ default: { props:['courseName'], template:'<div data-testid="course">{{ courseName }}</div>' } }))
vi.mock('@/pages/Lesson.vue', () => ({ default: { props:['courseName','chapterNumber','lessonNumber'], template:'<div data-testid="lesson">{{ courseName }}:{{ chapterNumber }}-{{ lessonNumber }}</div>' } }))
vi.mock('@/pages/LessonForm.vue', () => ({ default: { props:['courseName','avoCourseId','avoLessonId'], template:'<div data-testid="editor">{{ courseName }}:{{ avoCourseId }}-{{ avoLessonId }}</div>' } }))
import AvoCourseRoute from '@/pages/Courses/AvoCourseRoute.vue'
import AvoLessonEditor from '@/pages/Courses/AvoLessonEditor.vue'
import AvoCourseStart from '@/pages/Courses/AvoCourseStart.vue'

const stubRouteViews = (rows:any[]):any[] => rows.map(row => ({ ...row,
	...(row.component ? {component:{}} : {}),
	...(row.children ? {children:stubRouteViews(row.children)} : {}),
}))

describe('AVO course and lesson URLs', () => {
	it('resumes a course-only AVO link at the permitted lesson without adding a history entry', async () => {
		const router=createRouter({history:createMemoryHistory(),routes:[
			{path:'/personal/training/:avoCourseId',name:'AvoCourseStart',component:{}},
			{path:'/personal/training/:avoCourseId/view/:avoLessonId',name:'AvoLesson',component:{}},
		]})
		await router.push('/personal/training/11?lg=ru')
		callMock.mockResolvedValueOnce({course_id:'11',lesson_id:'26'})
		mount(AvoCourseStart,{props:{avoCourseId:'11'},global:{plugins:[router]}})
		await flushPromises()
		expect(router.currentRoute.value.fullPath).toBe('/personal/training/11/view/26?lg=ru')
	})
	it('uses literal AVO root paths and keeps native routes under the LMS prefix', () => {
		const router=createRouter({history:createMemoryHistory(),routes:getSiteRoutes('lms')})
		expect(router.resolve({name:'AvoLesson',params:{avoCourseId:'837',avoLessonId:'7642'}}).href).toBe('/personal/training/837/view/7642')
		expect(router.resolve({name:'AvoLessonEdit',query:{id:'7642',lg:'ru'}}).href).toBe('/shop/training/traininglessons/admin/update?id=7642&lg=ru')
		expect(router.resolve({name:'Courses'}).href).toBe('/lms/courses')
		expect(router.resolve({name:'CourseDetail',params:{courseName:'native'}}).href).toBe('/lms/courses/native')
		const edit=router.resolve('/shop/training/traininglessons/admin/update?id=7642&lg=ru')
		expect(edit.name).toBe('AvoLessonEdit')
		expect(edit.meta.requiresAuth).toBe(true)
		expect(router.resolve('/personal/training/837').meta.requiresAuth).toBe(true)
		expect(router.resolve('/personal/training/837/view/7642').meta.requiresAuth).toBe(true)
		expect(router.resolve('/lms/courses').meta.requiresAuth).toBeUndefined()
		expect((edit.matched[0].props.default as Function)(edit)).toEqual({avoLessonId:'7642'})
		const ambiguous=router.resolve('/shop/training/traininglessons/admin/update?id=7642&id=26')
		expect((ambiguous.matched[0].props.default as Function)(ambiguous)).toEqual({avoLessonId:''})
	})
	it('keeps the previous ID URLs working and respects a custom native prefix', async () => {
		const router=createRouter({history:createMemoryHistory(),routes:stubRouteViews(getSiteRoutes('academy'))})
		await router.push('/academy/courses/avo/11/lessons/26?lg=ru#part')
		expect(router.currentRoute.value.fullPath).toBe('/personal/training/11/view/26?lg=ru#part')
		await router.push('/academy/courses/avo/11/lessons/26/edit')
		expect(router.currentRoute.value.fullPath).toBe('/academy/courses/avo/11/lessons/26/edit')
		expect(router.currentRoute.value.params).toEqual({avoCourseId:'11',avoLessonId:'26'})
		await router.push('/academy/batches/details/batch-a')
		expect(router.currentRoute.value.path).toBe('/academy/batches/batch-a')
		await router.push('/academy/quizzes/quiz-a')
		expect(router.currentRoute.value.path).toBe('/academy/quizzes/edit/quiz-a')
	})
	it('resolves the query-only editor link without guessing a course', async () => {
		callMock.mockResolvedValueOnce({course_name:'course-a',course_id:'11',lesson_name:'lesson-a',chapter_number:2,lesson_number:3})
		const wrapper=mount(AvoLessonEditor,{props:{avoLessonId:'26'},global:{stubs:{RouterLink:true}}})
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.avo_course_routes.resolve_editor_by_lesson',{lesson_id:'26'})
		expect(wrapper.get('[data-testid=editor]').text()).toBe('course-a:11-26')
		await wrapper.setProps({avoLessonId:''});await flushPromises()
		expect(wrapper.find('[data-testid=editor]').exists()).toBe(false)
		expect(wrapper.find('[role=alert]').exists()).toBe(true)
	})
	it('generates a directly copyable course URL with the AVO ID', () => {
		const router=createRouter({history:createMemoryHistory(),routes:getSiteRoutes()})
		expect(router.resolve(courseCardRoute({name:'xr',avo_course_id:'206'})).href).toBe('/personal/training/206')
		expect(router.resolve(courseCardRoute({name:'native'})).href).toContain('/courses/native')
	})
	it('matches the actual routes using both source IDs', () => {
		const router=createRouter({ history:createMemoryHistory(), routes })
		expect(router.resolve('/courses/avo/11').name).toBe('AvoCourse')
		expect(router.resolve('/courses/avo/11/lessons/26').name).toBe('AvoLesson')
		expect(router.resolve('/courses/avo/11/lessons/26/edit').name).toBe('AvoLessonEdit')
	})
	it('opens the editor only for the verified source lesson', async () => {
		callMock.mockResolvedValueOnce({course_name:'course-a',lesson_name:'lesson-a',chapter_number:2,lesson_number:3})
		const wrapper=mount(AvoLessonEditor,{props:{avoCourseId:'11',avoLessonId:'26'},global:{stubs:{RouterLink:true}}})
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('lms.lms.avo_course_routes.resolve_editor',{course_id:'11',lesson_id:'26'})
		expect(wrapper.get('[data-testid=editor]').text()).toBe('course-a:11-26')
		callMock.mockResolvedValueOnce(null)
		await wrapper.setProps({avoLessonId:'27'});await flushPromises()
		expect(wrapper.find('[data-testid=editor]').exists()).toBe(false)
		expect(wrapper.get('[role=alert]').text()).toContain('нет прав')
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
