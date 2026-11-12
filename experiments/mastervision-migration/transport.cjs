'use strict';

// Private local transport: source HTML is returned only to its caller's pipe.
// Never print cookies, decrypted keys, server bodies on errors, or raw exceptions.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { execFileSync } = require('node:child_process');
const { once } = require('node:events');

const ORIGIN = 'https://shop.mastervision.su';
const HOST = 'shop.mastervision.su';
const PROFILE = path.resolve(__dirname, '../../../exports/lesson-content/private-browser-profiles/mastervision');
const MAX_BYTES = 32 * 1024 * 1024;
const TIMEOUT_MS = 45000;
const WINDOWS_EPOCH_MICROSECONDS = 11644473600000000n;
const READ_PATHS = new Set([
  '/shop/training/admin/admin',
  '/shop/training/admin/update',
  '/shop/training/traininglessons/admin/update',
]);
const ERRORS = new Set([
  'invalid_request', 'wrong_origin', 'unsupported_path', 'session_not_found',
  'session_expired', 'profile_unavailable', 'key_unavailable', 'cookie_database_unavailable',
  'cookie_format_unavailable', 'cookie_host_mismatch', 'invalid_cookie',
  'source_auth_error', 'source_http_error', 'unexpected_content_type', 'source_size',
  'source_timeout', 'source_transport_error', 'local_or_transport_error',
]);

function failure(code) { throw new Error(code); }
function safeErrorCode(error) {
  return ERRORS.has(error?.message) ? error.message : 'local_or_transport_error';
}

function sourceURL(value) {
  if (typeof value !== 'string' || value.length > 8192) failure('invalid_request');
  let url;
  try { url = new URL(value); } catch (_) { failure('wrong_origin'); }
  if (url.origin !== ORIGIN || url.username || url.password || url.hash || url.port) failure('wrong_origin');
  // Only the three source-reading endpoints are available, never an admin action.
  if (!READ_PATHS.has(url.pathname)) failure('unsupported_path');
  return url;
}

function boundDomain(domain) {
  if (typeof domain !== 'string') return false;
  return domain === HOST || (domain.startsWith('.') &&
    (HOST === domain.slice(1) || HOST.endsWith(domain)));
}

function decryptProfileKey(profile) {
  const script = String.raw`$ErrorActionPreference='Stop'
$state=Get-Content -LiteralPath (Join-Path $env:MASTER_VISION_COLLECTOR_PROFILE 'Local State') -Raw | ConvertFrom-Json
$blob=[Convert]::FromBase64String($state.os_crypt.encrypted_key)
if($blob.Length -lt 6 -or [Text.Encoding]::ASCII.GetString($blob,0,5) -ne 'DPAPI'){throw 'unsupported_key'}
Add-Type -AssemblyName System.Security
$key=[Security.Cryptography.ProtectedData]::Unprotect($blob[5..($blob.Length-1)],$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
[Convert]::ToBase64String($key)`;
  let key;
  try {
    key = Buffer.from(execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', '-'], {
      input: script, encoding: 'utf8', windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, MASTER_VISION_COLLECTOR_PROFILE: profile },
    }).trim(), 'base64');
  } catch (_) { failure('key_unavailable'); }
  if (key.length !== 32) { key.fill(0); failure('key_unavailable'); }
  return key;
}

function decodeCookieRows(rows, version, key, now = Date.now()) {
  if (!Number.isSafeInteger(version) || version < 1 || !Buffer.isBuffer(key) || key.length !== 32) failure('cookie_format_unavailable');
  const cookies = [];
  let expired = false;
  for (const row of rows) {
    if (!boundDomain(row.host_key)) continue;
    if (typeof row.name !== 'string' || !/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(row.name) ||
        typeof row.path !== 'string' || !row.path.startsWith('/') || /[\r\n]/.test(row.path) ||
        ![0, 1, 0n, 1n].includes(row.is_secure)) failure('invalid_cookie');
    let expires;
    try { expires = BigInt(row.expires_utc); } catch (_) { failure('invalid_cookie'); }
    if (expires < 0n) failure('invalid_cookie');
    const expiresAt = expires === 0n ? null : Number((expires - WINDOWS_EPOCH_MICROSECONDS) / 1000n);
    if (expiresAt !== null && expiresAt <= now) { expired = true; continue; }
    const data = Buffer.from(row.encrypted_value);
    if (data.subarray(0, 3).toString('ascii') !== 'v10' || data.length < 31) failure('cookie_format_unavailable');
    let plain;
    try {
      const cipher = crypto.createDecipheriv('aes-256-gcm', key, data.subarray(3, 15));
      cipher.setAuthTag(data.subarray(-16));
      plain = Buffer.concat([cipher.update(data.subarray(15, -16)), cipher.final()]);
    } catch (_) { failure('cookie_format_unavailable'); }
    try {
      let payload = plain;
      if (version >= 24) {
        const expected = crypto.createHash('sha256').update(row.host_key).digest();
        if (plain.length < 32 || !crypto.timingSafeEqual(plain.subarray(0, 32), expected)) failure('cookie_host_mismatch');
        payload = plain.subarray(32);
      }
      const value = payload.toString('utf8');
      if (/[\r\n;]/.test(value)) failure('invalid_cookie');
      cookies.push({ name: row.name, value, domain: row.host_key, path: row.path,
        secure: Boolean(row.is_secure), expiresAt });
    } finally { plain.fill(0); }
  }
  if (!cookies.length) failure(expired ? 'session_expired' : 'session_not_found');
  return cookies;
}

function cookiesForSource() {
  const cookieFile = path.join(PROFILE, 'Default', 'Network', 'Cookies');
  if (!fs.existsSync(cookieFile) || !fs.existsSync(path.join(PROFILE, 'Local State'))) failure('profile_unavailable');
  let key, db;
  try {
    key = decryptProfileKey(PROFILE);
    const { DatabaseSync } = require('node:sqlite');
    try { db = new DatabaseSync(cookieFile, { readOnly: true }); }
    catch (_) { failure('cookie_database_unavailable'); }
    const version = Number(db.prepare("select value from meta where key='version'").get()?.value);
    // Values are read from the isolated profile only. Foreign-domain rows are
    // discarded before any decryption and can never become request headers.
    const statement = db.prepare('select host_key,name,path,is_secure,expires_utc,encrypted_value from cookies');
    statement.setReadBigInts(true);
    return decodeCookieRows(statement.all(), version, key);
  } catch (error) {
    failure(ERRORS.has(error?.message) ? error.message : 'cookie_database_unavailable');
  } finally {
    try { db?.close(); } finally { key?.fill(0); }
  }
}

function cookieHeader(cookies, pathname, now = Date.now()) {
  if (!Array.isArray(cookies) || !cookies.length) failure('session_not_found');
  for (const cookie of cookies) {
    if (!boundDomain(cookie.domain) || typeof cookie.name !== 'string' ||
        !/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(cookie.name) ||
        typeof cookie.value !== 'string' || /[\r\n;]/.test(cookie.value) ||
        typeof cookie.path !== 'string' || !cookie.path.startsWith('/')) failure('invalid_cookie');
    // A session loaded at process start is never silently reused after expiry.
    if (cookie.expiresAt !== null && (!Number.isFinite(cookie.expiresAt) || cookie.expiresAt <= now)) failure('session_expired');
  }
  const applicable = cookies.filter(cookie => pathname === cookie.path ||
    pathname.startsWith(cookie.path.endsWith('/') ? cookie.path : cookie.path + '/'));
  if (!applicable.length) failure('session_not_found');
  return applicable.sort((a, b) => b.path.length - a.path.length).map(cookie => `${cookie.name}=${cookie.value}`).join('; ');
}

async function getHtml(value, cookies, fetcher = globalThis.fetch) {
  const url = sourceURL(value);
  const cookie = cookieHeader(cookies, url.pathname);
  try {
    const response = await fetcher(url, {
      method: 'GET', headers: { cookie }, redirect: 'manual',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if ([401, 403].includes(response.status) || (response.status >= 300 && response.status < 400)) failure('source_auth_error');
    if (response.status !== 200) failure('source_http_error');
    if (!/^text\/html\b/i.test(response.headers.get('content-type') || '')) failure('unexpected_content_type');
    const declared = response.headers.get('content-length');
    if (declared && /^\d+$/.test(declared) && Number(declared) > MAX_BYTES) {
      await response.body?.cancel?.().catch(() => {});
      failure('source_size');
    }
    const chunks = [];
    let size = 0;
    for await (const part of response.body) {
      size += part.length;
      if (size > MAX_BYTES) failure('source_size');
      chunks.push(part);
    }
    return Buffer.concat(chunks).toString('utf8');
  } catch (error) {
    if (ERRORS.has(error?.message)) throw error;
    failure(['AbortError', 'TimeoutError'].includes(error?.name) ? 'source_timeout' : 'source_transport_error');
  }
}

async function serve(input, output, { readCookies = cookiesForSource, fetcher = globalThis.fetch } = {}) {
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let cookies;
  try {
    for await (const line of lines) {
      let reply;
      try {
        if (line.length > 16384) failure('invalid_request');
        let request;
        try { request = JSON.parse(line); } catch (_) { failure('invalid_request'); }
        if (!request || Array.isArray(request) || typeof request !== 'object' ||
            Object.keys(request).length !== 1 || !Object.hasOwn(request, 'url')) failure('invalid_request');
        sourceURL(request.url); // Reject identity before touching profile secrets.
        if (!cookies) cookies = readCookies();
        reply = { ok: true, html: await getHtml(request.url, cookies, fetcher) };
      } catch (error) { reply = { ok: false, error: safeErrorCode(error) }; }
      if (!output.write(JSON.stringify(reply) + '\n')) await once(output, 'drain');
      if (!reply.ok) return 1; // Stop on the first error, without automatic retry.
    }
    return 0;
  } finally {
    lines.close();
    input.pause();
  }
}

if (require.main === module) {
  serve(process.stdin, process.stdout).then(code => { process.exitCode = code; }).catch(() => {
    process.stdout.write(JSON.stringify({ ok: false, error: 'local_or_transport_error' }) + '\n');
    process.exitCode = 1;
  });
}

module.exports = { ORIGIN, HOST, PROFILE, MAX_BYTES, TIMEOUT_MS, sourceURL, boundDomain,
  safeErrorCode, decodeCookieRows, cookieHeader, cookiesForSource, getHtml, serve };
