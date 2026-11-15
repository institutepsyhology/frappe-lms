"""Read personal links from individual MV-Centr API cards into a private archive.

Default: three-card preflight only. The key stays in memory and is entered in a
masked local window. No Frappe write or link redemption is performed here.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs, unquote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from audit_legacy_links import API_ORIGIN, inspect_record
from private_link_storage import StorageError, protect_url


class CollectionError(Exception):
    """Only fixed non-secret codes may leave the collection boundary."""


ERROR_CODES = frozenset({'wrong_contact', 'unexpected_detail_structure', 'redirect_blocked',
    'response_too_large', 'network_error', 'invalid_response_json', 'api_key_in_link',
    'detail_url_uid_mismatch', 'detail_missing_link', 'detail_invalid_link_type_or_length',
    'detail_unexpected_url_shape', 'detail_unexpected_query_fields', 'detail_invalid_url',
    'detail_empty_or_invalid_token', 'http_400', 'http_401', 'http_403', 'http_404',
    'http_408', 'http_429', 'http_500', 'http_502', 'http_503', 'http_504',
    'private_link_crypto_failed', 'private_link_storage_unavailable', 'link_encoding_too_deep'})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_detail(payload, source_id):
    for _ in range(5):
        if isinstance(payload, dict) and (payload.get('error') or payload.get('errors')):
            raise CollectionError('unexpected_detail_structure')
        if isinstance(payload, dict) and 'id_contact' in payload:
            if str(payload['id_contact']) != str(source_id):
                raise CollectionError('wrong_contact')
            return payload
        if isinstance(payload, list) and len(payload) == 1:
            payload = payload[0]
        elif isinstance(payload, dict):
            containers = [payload[key] for key in ('data', 'contacts', 'items') if key in payload]
            if len(containers) != 1:
                break
            payload = containers[0]
        else:
            break
    raise CollectionError('unexpected_detail_structure')


def read_detail(key, source_id):
    query = urlencode({'r': 'api/rest/contacts', 'id': str(source_id), 'key': key})
    url = API_ORIGIN + '/?' + query
    request = Request(url, headers={'Accept': 'application/json'}, method='GET')
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
            if response.geturl() != url:
                raise CollectionError('redirect_blocked')
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise CollectionError('response_too_large')
        payload = json.loads(raw.decode('utf-8-sig'))
    except HTTPError as error:
        code = error.code
        error.close()
        raise CollectionError('http_' + str(code)) from None
    except (URLError, TimeoutError, OSError):
        raise CollectionError('network_error') from None
    except (ValueError, UnicodeError):
        raise CollectionError('invalid_response_json') from None
    return normalize_detail(payload, source_id)


def verified_link(source_id, detail):
    url = detail.get('link_personal_auth') if isinstance(detail, dict) else None
    record = {'source': API_ORIGIN, 'contact': {'id': source_id},
              'auth_links': {'user': url, 'api_fields': {'link_personal_auth': url}},
              'api_data': {'list': {'link_personal_auth': url}}}
    status, token_digest = inspect_record(source_id, record)
    if status != 'verified':
        raise CollectionError('detail_' + status)
    return url, token_digest


def parse_key(value):
    if not isinstance(value, str):
        raise CollectionError('invalid_key_input')
    value = value.strip()
    if '://' in value:
        parts = urlsplit(value)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (parts.scheme != 'https' or parts.netloc != urlsplit(API_ORIGIN).netloc
                or parts.path != '/' or parts.fragment
                or query.get('r') != ['api/rest/contacts'] or len(query.get('key', [])) != 1):
            raise CollectionError('invalid_key_input')
        value = query['key'][0]
    if (not value or len(value) > 512 or any(ord(char) < 33 or ord(char) == 127 for char in value)
            or '://' in value or value[:1] in ('\"', "'") or value[-1:] in ('\"', "'")):
        raise CollectionError('invalid_key_input')
    return value


def graphical_key():
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.withdraw()
    root.title('МВЦ: проверка персональных ссылок')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.grid()
    ttk.Label(frame, text='API KEY GET из настроек АВО МВЦ', font=('', 12)).grid(sticky='w')
    ttk.Label(frame, text='Будут прочитаны только 3 отдельные карточки.\n'
              'Пароли и настройки не меняются. Ссылки не открываются.').grid(sticky='w', pady=10)
    ttk.Label(frame, text='Ключ или рабочий API-адрес (не отправляйте его в чат):').grid(sticky='w')
    entry = ttk.Entry(frame, width=65, show='*')
    entry.grid(sticky='ew', pady=6)
    result = []

    def submit():
        try:
            key = parse_key(entry.get())
        except (CollectionError, ValueError):
            messagebox.showerror('Проверьте ключ', 'Нужен ключ GET именно аккаунта МВЦ.', parent=root)
            return
        result.append(key)
        entry.delete(0, 'end')
        root.destroy()

    ttk.Label(frame, text='Ключ используется только в памяти и не записывается.').grid(sticky='w')
    ttk.Button(frame, text='Проверить 3 карточки', command=submit).grid(sticky='e', pady=10)
    root.bind('<Return>', lambda event: submit())
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    root.update_idletasks()
    root.geometry('+' + str(max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2))
                  + '+' + str(max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 2)))
    root.attributes('-topmost', True)
    root.deiconify()
    root.lift()
    entry.focus_force()
    root.after(1500, lambda: root.attributes('-topmost', False))
    root.mainloop()
    if not result:
        raise CollectionError('cancelled')
    return result.pop()


def collect(source_database, output_database, key, limit=3, fetch=read_detail, pause=time.sleep):
    if type(limit) is not int or limit < 1 or limit > 3:
        raise CollectionError('invalid_preflight_limit')
    source_database, output_database = Path(source_database).resolve(), Path(output_database).resolve()
    if source_database == output_database or output_database.exists():
        raise CollectionError('output_must_be_new')
    # Only fixed aggregate metadata leaves this function. Output DB is private.
    report = {'mode': 'individual_card_preflight', 'account': 'mv-centr',
              'requested': 0, 'verified': 0, 'failed': 0, 'status': 'not_started',
              'source_values_printed': False, 'frappe_changed': False,
              'links_redeemed': False, 'key_stored': False}
    with closing(sqlite3.connect(source_database.as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('PRAGMA query_only=ON')
        rows = source.execute('SELECT id, record_json FROM contacts ORDER BY id LIMIT ?', (limit,))
        candidates = []
        for source_id, raw in rows:
            record = json.loads(raw)
            if (record.get('source') != API_ORIGIN or type(source_id) is not int or not 0 < source_id < 2**63
                    or str((record.get('contact') or {}).get('id')) != str(source_id)):
                raise CollectionError('wrong_source_archive')
            candidates.append(source_id)
    if not candidates:
        raise CollectionError('empty_source_archive')
    try:
        descriptor = os.open(output_database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except FileExistsError:
        raise CollectionError('output_must_be_new') from None
    with closing(sqlite3.connect(output_database)) as output:
        output.execute('CREATE TABLE links (source_id INTEGER NOT NULL, url_encrypted BLOB NOT NULL, '
                       'token_digest BLOB NOT NULL UNIQUE, captured_at TEXT NOT NULL, '
                       'source_field TEXT NOT NULL, PRIMARY KEY (source_id, captured_at))')
        output.commit()
        for index, source_id in enumerate(candidates):
            if index:
                pause(1)
            report['requested'] += 1
            try:
                detail = normalize_detail(fetch(key, source_id), source_id)
                url, token_digest = verified_link(source_id, detail)
                decoded = url
                for _ in range(9):
                    if key in decoded:
                        raise CollectionError('api_key_in_link')
                    next_value = unquote(decoded, errors='strict')
                    if next_value == decoded:
                        break
                    decoded = next_value
                else:
                    raise CollectionError('link_encoding_too_deep')
                encrypted = protect_url(source_id, url)
                with output:
                    output.execute('INSERT INTO links VALUES (?, ?, ?, ?, ?)',
                        (source_id, encrypted, token_digest, datetime.now(timezone.utc).isoformat(),
                         'link_personal_auth'))
            except (CollectionError, StorageError, sqlite3.IntegrityError) as error:
                report['failed'] += 1
                report['status'] = 'stopped_at_first_invalid_detail'
                code = str(error) if isinstance(error, (CollectionError, StorageError)) else 'token_collision'
                report['error_code'] = code if code in ERROR_CODES or code == 'token_collision' else 'invalid_detail'
                break
            report['verified'] += 1
        else:
            report['status'] = 'individual_cards_verified'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-database', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args(argv)
    folder = args.output_directory.resolve()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / 'links.sqlite').exists():
            raise CollectionError('output_must_be_new')
        key = graphical_key()
        try:
            report = collect(args.source_database, folder / 'links.sqlite', key)
        finally:
            key = None
    except CollectionError as error:
        report = {'status': str(error), 'source_values_printed': False}
    except Exception:
        # No tracebacks: network exceptions may contain the API key in the URL.
        report = {'status': 'preflight_failed', 'source_values_printed': False}
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report.get('status') == 'individual_cards_verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
