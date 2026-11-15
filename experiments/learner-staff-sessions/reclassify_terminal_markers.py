"""Reclassify proven legacy end markers without changing original API pages."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

import legacy_api_snapshot as snapshot


def repair(directory):
    directory = snapshot.private_directory(directory)
    repaired, skipped = [], []
    with closing(sqlite3.connect(directory / 'snapshot.sqlite', timeout=10)) as db:
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        if any(metadata.get(key) != value for key, value in (
                ('format', snapshot.FORMAT), ('account', snapshot.ACCOUNT),
                ('source', snapshot.API_ORIGIN))):
            raise snapshot.SnapshotError('archive_metadata_mismatch')
        candidates = db.execute("SELECT resource,next_page,row_count,status FROM resource_state "
                                "WHERE error_code='invalid_json' AND status IN ('partial','error')").fetchall()
        for resource, page, count, old_status in candidates:
            if resource not in snapshot.INVENTORY:
                skipped.append(resource)
                continue
            stored = db.execute("SELECT raw_encrypted FROM pages WHERE resource=? AND page=? "
                                "AND parse_code='invalid_json' ORDER BY version_id DESC LIMIT 1",
                                (resource, page)).fetchone()
            if stored is None:
                skipped.append(resource)
                continue
            decoded = snapshot.unprotect_page(resource, page, stored[0])
            try:
                text = decoded['raw'].decode('utf-8-sig').strip()
                exact_marker = re.fullmatch(
                    r'No items where found for model\s+<b>([A-Za-z][A-Za-z0-9_]*)?</b>', text)
                empty = snapshot.parse_rows(decoded['raw'], snapshot.INVENTORY[resource]) == []
            except (UnicodeError, snapshot.SnapshotError):
                skipped.append(resource)
                continue
            prefix = db.execute("SELECT COUNT(*),COUNT(DISTINCT page),COALESCE(SUM(row_count),0),"
                                "MIN(page),MAX(page) FROM pages WHERE resource=? AND parse_code='accepted'",
                                (resource,)).fetchone()
            valid_prefix = (prefix[0] == page and prefix[1] == page and prefix[2] == count
                            and (not page or (prefix[3] == 0 and prefix[4] == page - 1)))
            if not exact_marker or not empty or not valid_prefix or decoded['snapshot'] != metadata['snapshot']:
                skipped.append(resource)
                continue
            if snapshot.INVENTORY[resource].id_field and db.execute(
                    'SELECT COUNT(*) FROM row_ids WHERE resource=?', (resource,)).fetchone()[0] != count:
                skipped.append(resource)
                continue
            if resource == 'contacts':
                with closing(sqlite3.connect((directory / 'contacts.sqlite').resolve().as_uri()
                                             + '?mode=ro', uri=True)) as index:
                    if index.execute('SELECT COUNT(*) FROM contacts').fetchone()[0] != count:
                        skipped.append(resource)
                        continue
            new_status = 'complete' if count else 'empty_inferred'
            with db:
                changed = db.execute("UPDATE resource_state SET status=?,error_code=NULL WHERE resource=? "
                                     "AND next_page=? AND row_count=? AND status=? AND error_code='invalid_json'",
                                     (new_status, resource, page, count, old_status)).rowcount
                if changed:
                    db.execute('INSERT INTO events VALUES(NULL,?,?,?,?)',
                               (datetime.now(timezone.utc).isoformat(), resource, page,
                                'terminal_marker_reclassified'))
            if changed:
                repaired.append({'resource': resource, 'rows': count, 'status': new_status})
    return {'reclassified': repaired, 'skipped_resources': skipped,
            'original_responses_preserved': True, 'source_or_frappe_changes': False}


if __name__ == '__main__':
    import argparse
    parser = snapshot.SafeParser(description=__doc__)
    parser.add_argument('--output-directory', required=True, type=Path)
    try:
        print(json.dumps(repair(parser.parse_args().output_directory), ensure_ascii=True))
    except Exception as error:
        print(json.dumps({'status': 'not_reclassified', 'error_code': snapshot.safe_code(error)}))
        raise SystemExit(1)
