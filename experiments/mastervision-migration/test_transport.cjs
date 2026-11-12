'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const path = require('node:path');
const { Readable, Writable } = require('node:stream');
const { spawnSync } = require('node:child_process');
const { ORIGIN, HOST, PROFILE, MAX_BYTES, TIMEOUT_MS, sourceURL, boundDomain,
  decodeCookieRows, cookieHeader, getHtml, serve } = require('./transport.cjs');
const { isCatalog, loadPlaywright } = require('./login.cjs');

const URL = ORIGIN + '/shop/training/admin/admin?lg=ru';
const NOW = Date.parse('2026-11-12T12:00:00Z');
const KEY = Buffer.alloc(32, 17);
const SECRET = 'private_cookie_value_must_not_be_logged';
const cookies = () => [{ name: 'auth', value: SECRET, domain: HOST, path: '/', secure: true, expiresAt: null }];

function encryptedRow({ domain = HOST, value = SECRET, version = 24, expiresAt = null } = {}) {
  const nonce = Buffer.alloc(12, 29);
  const cipher = crypto.createCipheriv('aes-256-gcm', KEY, nonce);
  const raw = Buffer.concat([...(version >= 24 ? [crypto.createHash('sha256').update(domain).digest()] : []), Buffer.from(value)]);
  return { host_key: domain, name: 'auth', path: '/', is_secure: 1n,
    expires_utc: expiresAt === null ? 0n : BigInt(expiresAt) * 1000n + 11644473600000000n,
    encrypted_value: Buffer.concat([Buffer.from('v10'), nonce, cipher.update(raw), cipher.final(), cipher.getAuthTag()]) };
}

function response({ status = 200, type = 'text/html; charset=UTF-8', length = null, chunks = [Buffer.from('<p>source</p>')] } = {}) {
  return { status, headers: { get: name => name === 'content-type' ? type : length },
    body: (async function* () { yield* chunks; })() };
}

function outputPipe() {
  let text = '';
  const output = new Writable({ write(chunk, _encoding, done) { text += chunk.toString(); done(); } });
  return { output, read: () => text };
}

test('source identity permits only Master Vision read endpoints', () => {
  assert.equal(sourceURL(URL).origin, ORIGIN);
  for (const url of [
    'http://shop.mastervision.su/shop/training/admin/admin',
    'https://shop.mv-centr.ru/shop/training/admin/admin',
    'https://shop.iomp.ru/shop/training/admin/admin',
    'https://shop.mastervision.su.evil.test/shop/training/admin/admin',
    'https://user:password@shop.mastervision.su/shop/training/admin/admin',
    URL + '#fragment', 'https://shop.mastervision.su:8443/shop/training/admin/admin',
  ]) assert.throws(() => sourceURL(url), /wrong_origin/);
  assert.throws(() => sourceURL(ORIGIN + '/shop/training/admin/delete?id=1'), /unsupported_path/);
});

test('profile belongs only to the new Master Vision collector', () => {
  assert.equal(PROFILE, path.resolve(__dirname, '../../../exports/lesson-content/private-browser-profiles/mastervision'));
  assert.equal(boundDomain(HOST), true);
  assert.equal(boundDomain('.mastervision.su'), true);
  assert.equal(boundDomain('.shop.mastervision.su'), true);
  assert.equal(boundDomain('mastervision.su'), false);
  assert.equal(boundDomain('.mv-centr.ru'), false);
  assert.equal(boundDomain('.mastervision.su.evil.test'), false);
});

test('v10 decoding validates host binding and retains private metadata in memory', () => {
  const [cookie] = decodeCookieRows([encryptedRow()], 24, KEY, NOW);
  assert.deepEqual(cookie, { name: 'auth', value: SECRET, domain: HOST, path: '/', secure: true, expiresAt: null });
  assert.equal(decodeCookieRows([encryptedRow({ version: 23 })], 23, KEY, NOW)[0].value, SECRET);
  const foreign = encryptedRow({ domain: 'shop.mv-centr.ru' });
  foreign.encrypted_value = Buffer.from('unsupported'); // Never decrypted for this source.
  assert.equal(decodeCookieRows([foreign, encryptedRow()], 24, KEY, NOW).length, 1);
  const mismatch = encryptedRow();
  mismatch.host_key = '.mastervision.su';
  assert.throws(() => decodeCookieRows([mismatch], 24, KEY, NOW), /cookie_host_mismatch/);
});

test('unsupported encryption, malformed metadata and header injection fail closed', () => {
  const unsupported = encryptedRow(); unsupported.encrypted_value[1] = '2'.charCodeAt(0);
  assert.throws(() => decodeCookieRows([unsupported], 24, KEY, NOW), /cookie_format_unavailable/);
  assert.throws(() => decodeCookieRows([{ ...encryptedRow(), is_secure: 7n }], 24, KEY, NOW), /invalid_cookie/);
  assert.throws(() => decodeCookieRows([encryptedRow({ value: 'x; other=stolen' })], 24, KEY, NOW), /invalid_cookie/);
  assert.throws(() => cookieHeader([{ ...cookies()[0], domain: 'shop.iomp.ru' }], '/'), /invalid_cookie/);
});

test('expired sessions fail immediately and do not create request headers', () => {
  assert.throws(() => decodeCookieRows([encryptedRow({ expiresAt: NOW - 1 })], 24, KEY, NOW), /session_expired/);
  assert.throws(() => cookieHeader([{ ...cookies()[0], expiresAt: NOW }], '/', NOW), /session_expired/);
  assert.throws(() => decodeCookieRows([], 24, KEY, NOW), /session_not_found/);
});

test('cookie path boundaries and ordering match the browser', () => {
  const values = [...cookies(), { ...cookies()[0], name: 'admin', path: '/shop/training', value: 'narrow' }];
  assert.equal(cookieHeader(values, '/shop/training/admin/admin'), `admin=narrow; auth=${SECRET}`);
  assert.equal(cookieHeader(values, '/shop/training-other'), `auth=${SECRET}`);
});

test('HTTP transport uses GET, manual redirects and a bounded timeout', async () => {
  assert.equal(TIMEOUT_MS, 45000);
  let requests = 0;
  const result = await getHtml(URL, cookies(), async (url, options) => {
    requests++;
    assert.equal(url.origin, ORIGIN);
    assert.equal(options.method, 'GET');
    assert.equal(options.redirect, 'manual');
    assert.equal(options.headers.cookie, `auth=${SECRET}`);
    assert.equal(options.signal.aborted, false);
    return response();
  });
  assert.equal(requests, 1);
  assert.equal(result, '<p>source</p>');
});

test('redirects and unauthorized responses are fatal without a retry', async () => {
  for (const status of [301, 302, 303, 307, 308, 401, 403]) {
    let calls = 0;
    await assert.rejects(getHtml(URL, cookies(), async () => { calls++; return response({ status }); }), /source_auth_error/);
    assert.equal(calls, 1);
  }
});

test('HTTP errors and non-HTML responses cannot be mistaken for an empty lesson', async () => {
  await assert.rejects(getHtml(URL, cookies(), async () => response({ status: 500 })), /source_http_error/);
  await assert.rejects(getHtml(URL, cookies(), async () => response({ type: 'application/json' })), /unexpected_content_type/);
});

test('both declared and streamed source size are bounded to 32 MiB', async () => {
  assert.equal(MAX_BYTES, 32 * 1024 * 1024);
  await assert.rejects(getHtml(URL, cookies(), async () => response({ length: String(MAX_BYTES + 1) })), /source_size/);
  await assert.rejects(getHtml(URL, cookies(), async () => response({ chunks: [Buffer.alloc(MAX_BYTES), Buffer.from('x')] })), /source_size/);
});

test('JSONL reuses one in-memory session and preserves request order', async () => {
  let reads = 0;
  const pipe = outputPipe();
  const input = Readable.from([JSON.stringify({ url: URL }) + '\n' + JSON.stringify({ url: URL }) + '\n']);
  assert.equal(await serve(input, pipe.output, { readCookies: () => { reads++; return cookies(); }, fetcher: async () => response() }), 0);
  assert.equal(reads, 1);
  assert.deepEqual(pipe.read().trim().split('\n').map(line => JSON.parse(line)), [
    { ok: true, html: '<p>source</p>' }, { ok: true, html: '<p>source</p>' },
  ]);
  assert.equal(pipe.read().includes(SECRET), false);
});

test('JSONL errors contain fixed codes only and stop before subsequent requests', async () => {
  let requests = 0;
  const pipe = outputPipe();
  const input = Readable.from([`${JSON.stringify({ url: URL })}\n${JSON.stringify({ url: URL })}\n`]);
  assert.equal(await serve(input, pipe.output, { readCookies: cookies, fetcher: async () => { requests++; throw new Error(SECRET); } }), 1);
  assert.equal(requests, 1);
  assert.equal(pipe.read(), '{"ok":false,"error":"source_transport_error"}\n');
  assert.equal(pipe.read().includes(SECRET), false);
});

test('wrong identities are rejected before reading any local secret', async () => {
  const pipe = outputPipe();
  let reads = 0;
  const input = Readable.from(['{"url":"https://shop.mv-centr.ru/shop/training/admin/admin"}\n']);
  assert.equal(await serve(input, pipe.output, { readCookies: () => { reads++; throw new Error(SECRET); } }), 1);
  assert.equal(reads, 0);
  assert.equal(pipe.read(), '{"ok":false,"error":"wrong_origin"}\n');
});

test('CLI rejects unknown fields without exposing exceptions or launching a browser', () => {
  const result = spawnSync(process.execPath, [path.join(__dirname, 'transport.cjs')], {
    input: JSON.stringify({ url: URL, cookie: SECRET }) + '\n', encoding: 'utf8', windowsHide: true,
  });
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '{"ok":false,"error":"invalid_request"}\n');
  assert.equal(result.stderr, '');
});

test('login confirmation requires the exact authenticated catalog', () => {
  const grid = '<div id="training-grid"><table></table></div>';
  assert.equal(isCatalog(URL, 200, grid), true);
  assert.equal(isCatalog(URL, 302, grid), false);
  assert.equal(isCatalog(URL, 200, '<form id="login-form"></form>'), false);
  assert.equal(isCatalog('https://shop.mv-centr.ru/shop/training/admin/admin', 200, grid), false);
  assert.equal(isCatalog(ORIGIN + '/login', 200, grid), false);
});

test('installed Playwright resolver is available without opening Edge', () => {
  assert.equal(typeof loadPlaywright().chromium.launchPersistentContext, 'function');
});
