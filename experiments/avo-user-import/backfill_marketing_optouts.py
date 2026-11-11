"""Conservatively apply MV-Centr snapshot opt-outs without exporting contact data."""
import argparse
import importlib.util
import json
import time
import urllib.request
from pathlib import Path

import import_mvcentr_users as source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=0, help='maximum source rows to scan; 0 means all')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('invalid limit')
    report = json.loads((source.ROOT/'exports/contacts-api-all-fields/report.json').read_text(encoding='utf-8'))
    if report.get('origin') != 'https://mvcentr.autoweboffice.ru':
        raise ValueError('source_account_mismatch')
    headers = {}
    if args.apply:
        spec = importlib.util.spec_from_file_location('h', source.ROOT/'frappe-mcp/headers.py')
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        headers = helper.authenticated_headers('my-lk.mv-centr.ru')
    checked = blocked = applied = 0
    batch = []

    def send_batch():
        nonlocal applied
        if not batch or not args.apply:
            return
        body = json.dumps({'account':'mv-centr', 'ids':batch}).encode('utf-8')
        request = urllib.request.Request(source.SITE+'/api/method/lms.lms.avo_marketing.apply_source_optouts',
            data=body, headers={**headers, 'Content-Type':'application/json'}, method='POST')
        with source.DIRECT_OPENER.open(request, timeout=90) as response:
            message = json.load(response).get('message')
        if not isinstance(message, dict) or message.get('processed') != len(batch):
            raise ValueError('unexpected_backfill_response')
        applied += len(batch)
        print(json.dumps({'scanned':checked, 'positive_source_ids_applied':applied}), flush=True)
        time.sleep(0.5)

    for ident, record in source.load():
        if args.limit and checked >= args.limit:
            break
        checked += 1
        if source.marketing_optout(record):
            blocked += 1
            batch.append(str(ident))
        if len(batch) == 250:
            send_batch(); batch.clear()
    send_batch()
    print(json.dumps({'scanned':checked, 'source_optouts':blocked, 'positive_source_ids_applied':applied}))


if __name__ == '__main__':
    main()
