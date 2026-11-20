'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {snapshot,card,ORIGIN} = require('./capture_worker.cjs');
const ROUTE='/shop/contact/contacttraining/admin/update?id=8&lg=ru';
const source = `<form id="contact-training-link-form" action="${ROUTE}">
  <input name="id" value="8">
  <input name="ContactTrainingLinkUpdateForm[creation_date]" value="2026-01-01 00:00:00">
  <input name="ContactTrainingLinkUpdateForm[date_of_end_training]" value="2026-01-31 23:59:59">
  <a href="/shop/contact/admin/update?id=20">Contact</a>
  <a href="/shop/training/admin/update?id=598">Course</a>
  </form><script>ContactLessonsList('#lessonListWrap',
  {allLessons:[{id:14},{id:15}],availableLessons:[{id:14}]})</script>`;
function answer(status,html) {
  const response={url:()=>ORIGIN+ROUTE,status:()=>status,headers:()=>({'content-type':'text/html'}),
    body:async()=>Buffer.from(html),dispose:async()=>{response.disposed=true;}};
  return {request:{get:async()=>response},response};
}

test('retains an expired relationship with only one assigned lesson',()=>{
  const result=snapshot(8,source,'2026-11-20T14:00:00Z');
  assert.equal(result.contact_id,20);
  assert.equal(result.course_id,598);
  assert.deepEqual(result.detail.availableLessons,[{id:14}]);
  assert.equal(result.detail.access.closes_at.iso,'2026-01-31T23:59:59+03:00');
  assert.throws(()=>snapshot(9,source,''),/wrong_card/);
  assert.throws(()=>snapshot(8,source.replace('availableLessons:[{id:14}]','availableLessons:[{id:42}]'),''),/assigned_lesson_not_in_course/);
});
test('recognizes the tenant 404 and rejects a generic gateway page or login response',async()=>{
  const absent=answer(404,'<title>Ошибка — АвтоВебОфис</title><h1>404</h1><h2>СТРАНИЦА НЕ НАЙДЕНА!</h2>');
  assert.equal((await card(absent,8)).status,'missing');
  assert.equal(absent.response.disposed,true);
  await assert.rejects(card(answer(404,'<h1>404</h1>'),8),/unknown_not_found/);
  await assert.rejects(card(answer(302,''),8),/login_required/);
  await assert.rejects(card(answer(200,'<form id="login-form">'),8),/login_required/);
});
