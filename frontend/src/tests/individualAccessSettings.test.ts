import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IndividualAccessSettings from '@/components/Courses/IndividualAccessSettings.vue'
const { callMock }=vi.hoisted(()=>({callMock:vi.fn()}))
vi.mock('frappe-ui',()=>({call:callMock,toast:{error:vi.fn()}}))
const overview=()=>({release_enabled:true,policy_enabled:true,policy_exists:true,policy:{default_personal_end_type:'Unlimited',global_end_type:'Unlimited'},lessons:[{name:'L1',title:'Lesson'}],schedule:[],capabilities:{read:true,write:true},grants:[{member:'should-not-render@example.test'}]})
const render=(data:any={name:'staff'})=>mount(IndividualAccessSettings,{props:{course:'course'},global:{provide:{$user:{data}}}})
beforeEach(()=>{callMock.mockReset();callMock.mockImplementation(async()=>overview())})
describe('course-wide access settings',()=>{
 it('loads defaults without requesting or displaying a learner roster',async()=>{const w=render();await flushPromises();expect(callMock).toHaveBeenCalledWith('lms.lms.course_people.get_course_defaults',{course:'course'});expect(w.text()).toContain('Общие правила доступа курса');expect(w.text()).not.toContain('should-not-render');expect(w.find('input[type=email]').exists()).toBe(false)})
 it('makes no request for a guest',async()=>{render(null);await flushPromises();expect(callMock).not.toHaveBeenCalled()})
 it('honours server read-only capabilities independently of native staff role flags',async()=>{callMock.mockResolvedValue({...overview(),capabilities:{read:true,write:false}});const w=render();await flushPromises();expect(w.get('fieldset').attributes('disabled')).toBeDefined()})
 it('keeps global schedules in course settings',async()=>{const w=render();await flushPromises();expect(w.text()).toContain('Расписание отдельных уроков');expect(w.text()).toContain('Личные сроки и уроки ученика открываются по карандашу')})
 it('sends only course defaults when saving',async()=>{const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='Сохранить общие сроки')!.trigger('click');await flushPromises();const args=callMock.mock.calls.find(c=>c[0].endsWith('update_course_access_defaults'))?.[1];expect(args.course).toBe('course');expect(args).not.toHaveProperty('member');expect(args.defaults.default_personal_end_type).toBe('Unlimited')})
})
