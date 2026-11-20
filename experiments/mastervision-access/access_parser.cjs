/* AVO link-card parser: no eval, network, or execution of page scripts. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AwoParser = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  const sensitive = /password|passwd|csrf|cookie|secret|authorization|api.?key|token|personal.?auth/i;
  function clean(v, key) {
    if (sensitive.test(key || '')) return '[REDACTED]';
    if (Array.isArray(v)) return v.map(x => clean(x));
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).filter(([k]) => !['__proto__','prototype','constructor'].includes(k)).map(([k,x]) => [k,clean(x,k)]));
    if (typeof v === 'string') return v.replace(/https?:\/\/[^\s"'<>]*secure-login[^\s"'<>]*/gi,'[REDACTED_LOGIN_URL]').replace(/([?&](?:vc|key|token|password|session|authorization|api_key)=)[^&#\s"'<>]*/gi,'$1[REDACTED]');
    return v;
  }
  function decode(s) {
    return String(s || '').replace(/&#(x[\da-f]+|\d+);/gi,(_,n) => { const x=n[0].toLowerCase()==='x'?parseInt(n.slice(1),16):+n; return x<=0x10ffff?String.fromCodePoint(x):'\ufffd'; }).replace(/&(amp|lt|gt|quot|apos|nbsp);/g,(_,x)=>({amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '})[x]);
  }
  function text(s) { return decode(String(s || '').replace(/<script\b[\s\S]*?<\/script>/gi,'').replace(/<style\b[\s\S]*?<\/style>/gi,'').replace(/<[^>]+>/g,' ')).replace(/\s+/g,' ').trim(); }
  function attrs(s) {
    const a={};
    for (const m of s.matchAll(/([^\s=<>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) a[m[1].toLowerCase()]=decode(m[2]??m[3]??m[4]??'');
    return a;
  }
  // Parse the data literal emitted by PHP, accepting quoted/unquoted keys and escapes.
  function literal(src, offset=0) {
    let i=offset, nodes=0;
    const ws=()=>{while(/\s/.test(src[i]||'') && i<src.length)i++;};
    function str() {
      const q=src[i++]; let v='';
      while(i<src.length) { let c=src[i++]; if(c===q)return v;
        if(c==='\\') { c=src[i++]; if(c==='u'||c==='x'){const n=c==='u'?4:2,h=src.slice(i,i+n); if(!new RegExp('^[0-9a-f]{'+n+'}$','i').test(h))throw Error('escape');v+=String.fromCharCode(parseInt(h,16));i+=n;} else v+=({n:'\n',r:'\r',t:'\t',b:'\b',f:'\f',v:'\v','0':'\0'})[c]??c; }
        else v+=c;
      } throw Error('unterminated string');
    }
    function value(depth) {
      if(depth>100 || ++nodes>1000000)throw Error('literal limit'); ws(); const c=src[i];
      if(c==='"'||c==="'")return str();
      if(c==='{'||c==='['){i++;const obj=c==='{'?{}:[],end=c==='{'?'}':']';ws();while(src[i]!==end){
        if(c==='{'){ws();const key=(src[i]==='"'||src[i]==="'")?str():(src.slice(i).match(/^[A-Za-z_$][\w$]*/)||[])[0];if(key==null)throw Error('key');if(src[i]!=='"'&&src[i]!=="'" && src.slice(i,i+key.length)===key)i+=key.length;ws();if(src[i++]!==':')throw Error('colon');const v=value(depth+1);if(!['__proto__','prototype','constructor'].includes(key))obj[key]=v;}
        else obj.push(value(depth+1));ws();if(src[i]===','){i++;ws();}else if(src[i]!==end)throw Error('separator');
      }i++;return obj;}
      const m=src.slice(i).match(/^(true|false|null|undefined|[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)/);if(!m)throw Error('unsupported literal');i+=m[0].length;return ({true:true,false:false,null:null,undefined:null})[m[0]]??(m[0]==='null'||m[0]==='undefined'?null:Number(m[0]));
    }
    return {value:value(0),end:i};
  }
  function date(v) {
    const raw=v==null?null:String(v).trim();if(!raw || /^0000-00-00/.test(raw))return {raw,iso:null,kind:'unset'};
    if(/^9999-/.test(raw))return {raw,iso:null,kind:'unlimited'};
    const m=raw.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}:\d{2}))?$/);let iso=m?m[1]+'T'+(m[2]||'00:00:00')+'+03:00':null;
    if(m){const [y,mo,d]=m[1].split('-').map(Number),[h,mi,se]=(m[2]||'00:00:00').split(':').map(Number),cal=new Date(0);cal.setUTCFullYear(y,mo-1,d);if(mo<1||mo>12||d<1||cal.getUTCMonth()!==mo-1||cal.getUTCDate()!==d||h>23||mi>59||se>59)iso=null;}
    return {raw,iso,kind:iso&&Number.isFinite(Date.parse(iso))?'datetime':'invalid'};
  }
  const bool=v=>v==null?null:(v===true||v===1||v==='1'?true:v===false||v===0||v==='0'?false:null);
  function accessTerms(access, courseEnd) {
    const personal=access.closes_at||{},course=courseEnd||{};
    const known=x=>x.kind==='unlimited'||(x.kind==='datetime'&&x.iso&&Number.isFinite(Date.parse(x.iso)));
    const personal_term=personal.kind==='unlimited'?'unlimited':personal.kind==='datetime'?'until_date':personal.kind==='unset'&&personal.raw!=null?'unset':'unknown';
    let effective_closes_at={raw:null,iso:null,kind:'unknown'};
    if(access.ignore_course_end===true&&known(personal))effective_closes_at={...personal};
    else if(access.ignore_course_end===false&&known(personal)&&known(course)){
      if(personal.kind==='unlimited')effective_closes_at={...course};
      else if(course.kind==='unlimited')effective_closes_at={...personal};
      else effective_closes_at={...(Date.parse(personal.iso)<=Date.parse(course.iso)?personal:course)};
    }
    let derived_status='unknown';
    if(access.as_of&&Number.isFinite(Date.parse(access.as_of))){
      const now=Date.parse(access.as_of),expired=x=>x.kind==='datetime'&&x.iso&&now>=Date.parse(x.iso);
      if(access.frozen===true)derived_status='frozen';
      else if(access.opens_at?.kind==='datetime'&&now<Date.parse(access.opens_at.iso))derived_status='scheduled';
      else if(expired(personal)||(access.ignore_course_end===false&&expired(course)))derived_status='expired';
    }
    return {personal_term,effective_closes_at,derived_status};
  }
  function parse(html, meta={}) {
    const warnings=[];const source=clean(meta.source&&typeof meta.source==='object'?meta.source:{path:meta.source??null});
    if(meta.url)source.url=clean(meta.url);if(meta.fetchedAt)source.fetched_at=meta.fetchedAt;
    if(meta.origin)source.origin=clean(meta.origin);else if(meta.url){try{source.origin=new URL(meta.url).origin;}catch{}}
    const baseUrl=meta.url||meta.origin||null;
    function fullUrl(h){try{return baseUrl?new URL(h,baseUrl).href:decode(h);}catch{return decode(h);}}
    const out={schema_version:1,page_status:'unknown',record_kind:'unknown',link_id:null,contact:{id:null},course:{id:null,title:null,source_url:null,status:null,start_at:date(null),end_at:{raw:null,iso:null,kind:'unknown'}},access:{},lessons:[],raw_fields:[],warnings,source};
    const form=String(html).match(/<form\b([^>]*\bid=["']contact-training-link-form["'][^>]*)>([\s\S]*?)<\/form>/i);
    const fields=form?form[2]:String(html); const labels={};
    for(const m of fields.matchAll(/<label\b([^>]*)>([\s\S]*?)<\/label>/gi)){const a=attrs(m[1]);if(a.for)labels[a.for]=text(m[2]);}
    for(const m of fields.matchAll(/<input\b([^>]*)>|<(select|textarea)\b([^>]*)>([\s\S]*?)<\/\2>/gi)){
      const a=attrs(m[1]||m[3]),type=(m[2]||a.type||'text').toLowerCase(); if(!a.name||sensitive.test(a.name)||/^(?:yt\d+)$/.test(a.name)||['submit','button','reset'].includes(type))continue;
      const f={name:a.name,id:a.id||null,type,value:a.value??'',label:labels[a.id]||null};
      if(type==='checkbox'||type==='radio'){f.checked='checked' in a;f.value=f.checked?(a.value??'1'):'0';}
      if(type==='textarea')f.value=decode(m[4]);
      if(type==='select'){f.options=[...m[4].matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/gi)].map(x=>{const b=attrs(x[1]);return {value:b.value??text(x[2]),label:text(x[2]),selected:'selected' in b};});f.value=f.options.filter(x=>x.selected).map(x=>x.value);}
      out.raw_fields.push(clean(f));
    }
    const get=n=>out.raw_fields.filter(f=>f.name===n||f.name.endsWith('['+n+']')).at(-1)?.value;
    const links=[...fields.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi)].map(m=>({a:attrs(m[1]),title:text(m[2])}));
    function linkId(h){return +(String(h).match(/[?&]id=(\d+)/)||[])[1]||null;}
    const contact=links.find(x=>/\/contact\/admin\/update\?/.test(x.a.href||''));if(contact)out.contact.id=linkId(contact.a.href);
    if(!form){
      const contactForm=String(html).match(/<form\b([^>]*\bid=["']contact-form["'][^>]*)>/i);
      if(contactForm){
        out.record_kind='contact';out.contact.id=linkId(attrs(contactForm[1]).action);out.page_status=out.contact.id?'ok':'unknown';
        out.links_list=[];
        const grid=String(html).match(/<div\b[^>]*\bid=["']training-access-grid["'][^>]*>([\s\S]*?<\/table>)/i)?.[1]||'';
        for(const row of grid.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)){
          const cells=[...row[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(x=>x[1]);
          const anchor=cells[0]?.match(/<a\b([^>]*)>([\s\S]*?)<\/a>/i);if(!anchor)continue;
          const href=attrs(anchor[1]).href;if(!/\/contacttraining\/admin\/update\?/.test(href||''))continue;
          out.links_list.push({link_id:linkId(href),title:text(anchor[2]),source_url:clean(fullUrl(href)),opens_at:date(text(cells[1])),closes_at:date(text(cells[2])),access_type:text(cells[3])});
        }
        warnings.push('Contact page lists access links; lesson and course configuration require the linked cards.');return out;
      }
      if(/type\s*=\s*["']password["']|\bid=["']login-form["']/i.test(html))out.page_status='login';else if(/(?:Error\s*404|404\s*(?:Not Found|Страница)|Page not found|Страница не найдена|Запись не найдена)/i.test(text(html)))out.page_status='not_found';warnings.push('Expected access-link form was not found; no access record inferred.');return out;
    }
    out.record_kind='access_link';
    out.link_id=+(get('id')||linkId(attrs(form[1]).action)||meta.id)||null;
    const course=links.find(x=>/training\/admin\/update\?/.test(x.a.href||''));if(course){out.course.id=linkId(course.a.href);out.course.title=course.title;out.course.source_url=clean(fullUrl(course.a.href));}
    let cfg={};const at=String(html).search(/\bContactLessonsList\s*\(/);if(at>=0){try{const begin=String(html).indexOf('{',at);if(begin<0)throw Error('missing data');cfg=literal(String(html),begin).value;}catch{warnings.push('Lesson configuration could not be parsed completely.');}}
    else warnings.push('Lesson configuration is absent.');
    const all=Array.isArray(cfg.allLessons)?cfg.allLessons:[],assigned=Array.isArray(cfg.availableLessons)?cfg.availableLessons:[];const byId=new Map();
    for(const l of all)byId.set(String(l.id),{all:l,assigned:null});for(const l of assigned){const e=byId.get(String(l.id))||{all:null};e.assigned=l;byId.set(String(l.id),e);}
    for(const e of byId.values()){const a=e.all||{},b=e.assigned||{},raw={...a,...b};out.lessons.push({id:raw.id,title:raw.title??null,assigned:e.assigned!=null,hidden:bool(raw.hidden),accessible:bool(raw.accessible),can_edit_accessible:bool(raw.canEditAccessible),day_access:raw.day_access??null,number:raw.number??null,category_id:raw.id_category??null,category:raw.category??null,raw:clean(raw),source_all:clean(e.all),source_assigned:clean(e.assigned)});}
    out.lesson_config=clean(Object.fromEntries(Object.entries(cfg).filter(([k])=>k!=='allLessons'&&k!=='availableLessons')));
    const visibleArea=fields.split(/<div\b[^>]*class=["'][^"']*modal\b/i)[0];
    const freeze=/href=["'][^"']*\/freezeaccess\?/.test(visibleArea),unfreeze=/href=["'][^"']*\/unfreezeaccess\?/.test(visibleArea);
    const shift=String(html).match(/\b(?:var|let|const)\s+dayAccessShift\s*=\s*(-?\d+)/),start=String(html).match(/\b(?:var|let|const)\s+trainingStartDate\s*=\s*(["'])([^"']*)\1/);
    const a=out.access={opens_at:date(get('creation_date')),closes_at:date(get('date_of_end_training')),report_check_ends_at:date(get('date_of_end_check_report')),ignore_course_end:bool(get('not_use_training_end_date')),frozen:freeze?false:unfreeze?true:null,day_access_shift:shift?Number(shift[1]):null,training_start_at:date(start?.[2]),derived_status:'unknown',as_of:meta.asOf??null};
    const alert=text(fields.match(/<div\b[^>]*class=["'][^"']*alert[^"']*["'][^>]*>([\s\S]*?)<\/div>/i)?.[1]);
    const dates=alert.match(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/g)||[];if(dates.length && /окончани[яе]\s+курса/i.test(alert))out.course.end_at=date(dates[0]);
    out.notices=[...fields.matchAll(/<(?:div|p)\b[^>]*class=["'][^"']*(?:alert|muted)[^"']*["'][^>]*>([\s\S]*?)<\/(?:div|p)>/gi)].map(m=>clean(text(m[1])));
    Object.assign(a,accessTerms(a,out.course.end_at));
    if(a.effective_closes_at.kind==='unknown')warnings.push('Overall access end is unknown: one of the applicable end-date settings has not been verified. The personal term is preserved separately.');
    warnings.push('Course state and completion rules are not present in this link card; accessible is a lesson flag, not a complete effective-access decision.');
    out.page_status=out.link_id && Array.isArray(cfg.allLessons)&&Array.isArray(cfg.availableLessons)?'ok':'unknown';return out;
  }
  return {parse,parseLiteral:literal,date,accessTerms,sanitize:clean};
});
