'use strict';
// Access cards are fetched by the signed-in browser. Only the extracted source
// records cross the SSH pipe; the AVO session stays in its own local profile.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');
const readline = require('node:readline');
const zlib = require('node:zlib');
const { parse, parseLiteral, sanitize } = require('./access_parser.cjs');
const { loadPlaywright, PROFILE } = require('../mastervision-migration/login.cjs');

const ORIGIN = 'https://shop.mastervision.su';
const END = 446858;
const CONTROL = [446462, END];
const ROUTE = '/shop/contact/contacttraining/admin/update';
const SERVER = '/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private/mv-course-access';
const ROOT = path.resolve(__dirname, '../../..');
const MAX_BODY = 12 * 1024 * 1024;
const timeout = ms => new Promise(resolve => setTimeout(resolve, ms));
const utc = () => new Date().toISOString();
function check(ok, code) { if (!ok) throw Error(code); }
function num(x) {
  check((typeof x === 'number' || typeof x === 'string' && /^[1-9]\d{0,15}$/.test(x))
    && Number.isSafeInteger(Number(x)) && Number(x) > 0, 'bad_id');
  return Number(x);
}
function snapshot(id, html, at) {
  const url = ORIGIN + ROUTE + '?id=' + id + '&lg=ru';
  const form = html.match(/<form\b(?=[^>]*\bid="contact-training-link-form")([^>]*)>/i);
  const action = form?.[1].match(/\baction="([^"]+)"/i)?.[1].replace(/&amp;/gi, '&');
  check(action, 'missing_card_form');
  const dst = new URL(action, ORIGIN);
  check(dst.origin === ORIGIN && dst.pathname === ROUTE && dst.searchParams.get('id') === String(id), 'wrong_card');
  const parsed = parse(html, {url});
  check(parsed.page_status === 'ok' && parsed.link_id === id && parsed.record_kind === 'access_link', 'invalid_card');
  num(parsed.contact.id); num(parsed.course.id);
  check(new URL(parsed.course.source_url, ORIGIN).origin === ORIGIN, 'wrong_course_origin');
  const calls = [...html.matchAll(/\bContactLessonsList\s*\(\s*['"]#lessonListWrap['"]\s*,\s*/g)];
  check(calls.length === 1, 'unexpected_lesson_config');
  const config = parseLiteral(html, calls[0].index + calls[0][0].length).value;
  function lessons(key) {
    const src = config[key];
    check(Array.isArray(src) && src.length <= 5000, 'bad_lesson_list');
    const rows = src.map(x => {
      check(x && typeof x === 'object' && !Array.isArray(x), 'bad_lesson');
      return {...sanitize(x), id:num(x.id)};
    });
    check(new Set(rows.map(row => row.id)).size === rows.length, 'duplicate_lesson');
    return rows;
  }
  const all = lessons('allLessons'), available = lessons('availableLessons');
  const allIds = new Set(all.map(r => r.id));
  check(available.every(row => allIds.has(row.id)), 'assigned_lesson_not_in_course');
  const fields = parsed.raw_fields.filter(f => f.name === 'id' || f.name.startsWith('ContactTrainingLinkUpdateForm['));
  check(fields.some(f => f.name.endsWith('[creation_date]')) && fields.some(f => f.name.endsWith('[date_of_end_training]'))
    && parsed.access.closes_at.kind !== 'invalid' && parsed.access.opens_at.kind !== 'invalid', 'unknown_access_dates');
  return {status:'card', origin:ORIGIN, id, captured_at:at, contact_id:parsed.contact.id,
    course_id:parsed.course.id, allLessons:all, detail:{availableLessons:available,
      access:parsed.access, course:{id:parsed.course.id, end_at:parsed.course.end_at},
      fields, lesson_options:parsed.lesson_config, notices:parsed.notices}};
}

async function card(browser, id) {
  const url = ORIGIN + ROUTE + '?id=' + id + '&lg=ru';
  for (let attempt=0; attempt<4; attempt++) {
    if (attempt) await timeout(1200 * 2 ** attempt);
    let response;
    try {
      response = await browser.request.get(url, {maxRedirects:0, timeout:30000, failOnStatusCode:false});
      const status = response.status();
      check(response.url() === url, 'unexpected_origin');
      if ([401,403].includes(status) || status >= 300 && status < 400) throw Error('login_required');
      if ([408,429,500,502,503,504].includes(status)) {
        if (attempt < 3) continue;
        throw Error('source_temporarily_unavailable');
      }
      const headers = response.headers();
      check(!headers['content-length'] || Number(headers['content-length']) <= MAX_BODY, 'oversize_card');
      const data = await response.body();
      check(data.length > 0 && data.length <= MAX_BODY, 'oversize_card');
      const html = data.toString('utf8');
      check(!/\bid=['"]login-form['"]|<input[^>]+type=['"]password['"]/i.test(html), 'login_required');
      if (status === 404) {
        // A real absent link and a gateway error can both return HTTP 404.
        // Pin the observed shop's own error template, with a positive-card
        // session control below before marking any part of the range absent.
        check(/<h[12]\b[^>]*>\s*404\s*<\/h[12]>/i.test(html)
          && /СТРАНИЦА\s+НЕ\s+НАЙДЕНА!/iu.test(html)
          && /<title>[^<]*АвтоВебОфис[^<]*<\/title>/iu.test(html), 'unknown_not_found');
        return {id, status:'missing', origin:ORIGIN, captured_at:utc()};
      }
      check(status === 200 && /^text\/html\b/i.test(headers['content-type'] || ''), 'unexpected_card_response');
      return snapshot(id, html, utc());
    } catch (error) {
      if (/^[a-z_]+$/.test(error.message)) throw error;
      if (attempt === 3) throw Error('source_connection_failed');
    } finally {
      if (response) await response.dispose();
    }
  }
}

function server() {
  const ssh = process.platform === 'win32' ? path.join(process.env.SystemRoot,'System32/OpenSSH/ssh.exe') : 'ssh';
  const child=spawn(ssh,['-o','BatchMode=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=15',
    '-o','ServerAliveCountMax=3','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
    '-o','UserKnownHostsFile='+path.join(ROOT,'frappe-deploy/known_hosts'),
    '-i',path.join(os.homedir(),'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',
    'docker exec -i -u frappe company-lms-backend-1 /home/frappe/frappe-bench/env/bin/python -B '+SERVER+'/archive_store.py'],
    {windowsHide:true,stdio:['pipe','pipe','ignore']});
  const lines=readline.createInterface({input:child.stdout})[Symbol.asyncIterator]();
  child.on('error',()=>{}); // The pipe/error and the closing iterator report a failed SSH start.
  child.stdin.on('error',()=>{});
  return {async call(data) {
    if (child.exitCode !== null || child.stdin.destroyed) throw Error('receiver_disconnected');
    const sent=JSON.stringify(data)+'\n';
    if (Buffer.byteLength(sent)>24*1024*1024) throw Error('packet_limit');
    check(await new Promise(resolve=>child.stdin.write(sent,err=>resolve(!err))), 'receiver_disconnected');
    const result=await lines.next();
    check(!result.done,'receiver_disconnected');
    const reply=JSON.parse(result.value);
    check(!reply.error, reply.error || 'receiver_error');
    return reply;
  }, close() {child.stdin.end();child.kill();}};
}

async function transmit(sink,records) {
  const raw=Buffer.from(JSON.stringify(records));
  if (raw.length>48*1024*1024 && records.length>1) {
    const half=Math.floor(records.length/2);
    await transmit(sink,records.slice(0,half));
    await transmit(sink,records.slice(half));
    return;
  }
  const data=zlib.deflateSync(raw,{level:2}).toString('base64');
  check((await sink.call({op:'batch',data})).stored,'batch_unconfirmed');
}

async function collect(browser,sink,options={}) {
  const {inventory,workers=4}=options;
  const progress=await sink.call({op:'resume'});
  if (progress.state==='complete') return progress;
  if (inventory) {
    check(inventory.origin===ORIGIN && inventory.through===END && inventory.verified===true
      && Array.isArray(inventory.first) && Array.isArray(inventory.second)
      && new Date(inventory.captured_at).getTime()>=new Date('2026-11-20T00:00:00+03:00').getTime(),
      'unverified_inventory');
    await sink.call({op:'inventory',first:inventory.first,second:inventory.second});
  } else check(progress.scope==='range','inventory_required');
  const controls=await Promise.all(CONTROL.map(id=>card(browser,id)));
  check(controls.every(r=>r.status==='card') && controls[0].course_id===598,'controls_not_verified');
  await transmit(sink,controls);
  if (options.pilot) return sink.call({op:'status'});
  const done=new Uint8Array(END+1);
  for (const [lo,hi] of progress.ranges) done.fill(1,lo,hi+1);
  for (const id of CONTROL) done[id]=1;
  const ids=inventory ? [...inventory.first].reverse() : Array.from({length:END},(_,i)=>END-i);
  let checked=0,errors=0,last=0,pending=[];
  for (let pos=0;pos<ids.length;) {
    const batch=[];
    while(pos<ids.length && batch.length<workers) {
      const id=ids[pos++]; if (!done[id]) batch.push(id);
    }
    if (!batch.length) continue;
    const records=await Promise.all(batch.map(async id=>{
      try { return await card(browser,id); }
      catch(e) {return {id,status:'error',code:/^[a-z_]+$/.test(e.message)?e.message:'unexpected_response'};}
    }));
    if (records.some(r=>r.status==='missing') && (!last || Date.now()-last>30000)) {
      // Generic 404s from an expired session must never become a completed range.
      const reference=await card(browser,END);
      check(reference.status==='card','login_required');last=Date.now();
    }
    pending.push(...records);
    checked+=records.length;
    for(const r of records) {
      errors=r.status==='error'?errors+1:0;
      if (['login_required','unexpected_origin','wrong_card','receiver_disconnected'].includes(r.code) || errors>=10) {
        await transmit(sink,pending);
        throw Error(r.code || 'ten_consecutive_errors');
      }
    }
    if (pending.length >= 32) {
      await transmit(sink,pending);
      pending=[];
    }
    if (checked%1000<records.length)
      console.log(JSON.stringify({at:utc(),processed:checked,link_id:batch.at(-1)}));
  }
  if (pending.length) await transmit(sink,pending);
  check((await card(browser,END)).status==='card','login_required');
  return sink.call({op:'finish'});
}

async function main(args) {
  let inventory, pilot=false, workers=4;
  for(let i=0;i<args.length;i++) {
    if(args[i]==='--pilot') pilot=true;
    else if(args[i]==='--inventory') inventory=JSON.parse(fs.readFileSync(args[++i],'utf8'));
    else if(args[i]==='--workers') {workers=Number(args[++i]);check(Number.isInteger(workers)&&workers>0&&workers<=10,'workers');}
    else throw Error('unknown_argument');
  }
  const browser=await loadPlaywright().chromium.launchPersistentContext(PROFILE,
    {channel:'msedge',headless:true,chromiumSandbox:true,args:['--disk-cache-size=1048576']});
  try {
    // Persisted IDs make retries idempotent. Login or an unfamiliar source
    // schema is surfaced immediately and cannot silently become a missing ID.
    const delays=[15000,30000,60000,120000,300000];
    for (let attempt=0;;attempt++) {
      const sink=server();
      try {
        const result=await collect(browser,sink,{inventory,pilot,workers});
        console.log(JSON.stringify(result));
        return;
      } catch(error) {
        const transient=['source_connection_failed','source_temporarily_unavailable','receiver_disconnected'];
        if (attempt>=delays.length || !transient.includes(error.message)) throw error;
        console.log(JSON.stringify({at:utc(),status:'retrying',code:error.message,
          next_attempt_seconds:delays[attempt]/1000}));
      } finally {sink.close();}
      await timeout(delays[attempt]);
    }
  } finally {await browser.close();}
}

if(require.main===module) main(process.argv.slice(2)).catch(e=>{
  console.error(JSON.stringify({status:'stopped',code:/^[a-z_]+$/.test(e.message)?e.message:'collector_failed'}));
  process.exitCode=1;
});
module.exports={snapshot,collect,card,server,transmit,END,ORIGIN};
