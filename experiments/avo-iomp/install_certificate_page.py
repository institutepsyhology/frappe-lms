"""Install the personal certificates page only on IOMP. Dry-run is the default."""

import argparse
from html.parser import HTMLParser
from urllib.request import Request

from import_capture import IompClient, Stop, mutate
from certificate_list import PAGE_ROUTE, PAGE_URL, certificate_page_document


def installed(client, data):
    matches = client.call('list_documents', {'doctype': 'Web Page', 'fields': ['name'],
        'filters': [['route', '=', PAGE_ROUTE]], 'limit': 2})
    if matches.get('has_next_page') or len(matches['documents']) > 1:
        raise Stop('certificate_page_ambiguous')
    if not matches['documents']:
        return False
    row = client.call('get_document', {'doctype': 'Web Page', 'name': matches['documents'][0]['name']})
    if any(row.get(key) != value for key, value in data.items()):
        raise Stop('certificate_page_route_already_occupied')
    return True


def install(client, apply=False):
    if (client.account, client.site) != ('iomp', 'my-lk.iomp.ru'):
        raise Stop('wrong_frappe_site')
    data = certificate_page_document()
    del data['doctype']
    if installed(client, data):
        return 'verified'
    if not apply:
        return 'ready_to_create'
    mutate(client, 'create_document', {'doctype': 'Web Page', 'data': data})
    if not installed(client, data):
        raise Stop('certificate_page_readback_failed')
    return 'created_and_verified'


class PageMarkers(HTMLParser):
    def __init__(self):
        super().__init__()
        self.login = self.personal = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('id') == 'certificate-login':
            self.login = attrs.get('href') == '/login?redirect-to=%2Fpersonal%2Fcertificate'
        if tag == 'section' and attrs.get('id') == 'personal-certificate-list':
            self.personal = True


def verify_http(client):
    if (client.account, client.site) != ('iomp', 'my-lk.iomp.ru'):
        raise Stop('wrong_frappe_site')
    for signed_in in (False, True, True, False):
        request = Request(PAGE_URL, headers=client.auth if signed_in else {})
        with client.opener.open(request, timeout=30) as response:
            if (response.status != 200 or response.geturl() != PAGE_URL
                    or 'no-store' not in response.headers.get('Cache-Control', '').lower()
                    or response.headers.get('X-From-Cache', '').lower() != 'false'):
                raise Stop('certificate_page_http_cache_unverified')
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise Stop('certificate_page_response_too_large')
            markers = PageMarkers()
            markers.feed(raw.decode('utf-8'))
            if (markers.login, markers.personal) != (not signed_in, signed_in):
                raise Stop('certificate_page_http_identity_unverified')
    return 'verified_guest_and_signed_in_no_store'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--verify-http', action='store_true')
    options = parser.parse_args()
    target = IompClient()
    try:
        print(install(target, options.apply))
        if options.verify_http:
            print(verify_http(target))
    finally:
        target.close()
