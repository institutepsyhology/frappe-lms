"""Supply an authenticated Frappe session to Codex's HTTP MCP transport.

Stdout is a credential channel: invoke from Codex or capture it, never log it.
Passwords stay in the existing protected access file. No secrets are stored here.
"""

import argparse
import http.cookiejar
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request


SITES = ("my-lk.mastervision.su", "my-lk.iomp.ru", "my-lk.mv-centr.ru")
ACCESS_FILE = Path(__file__).resolve().parents[1] / "frappe-deploy/private/initial-access.txt"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def authenticated_headers(site):
    if site not in SITES:
        raise ValueError("Unknown site")
    lines = ACCESS_FILE.read_text(encoding="utf-8").splitlines()
    address = "\u0410\u0434\u0440\u0435\u0441: https://" + site + "/login"
    matches = [i for i, line in enumerate(lines) if line == address]
    if len(matches) != 1:
        raise ValueError("Site credentials unavailable")
    index = matches[0]
    if lines[index + 1] != "\u041b\u043e\u0433\u0438\u043d: Administrator":
        raise ValueError("Unexpected login")
    prefix = "\u041f\u0430\u0440\u043e\u043b\u044c: "
    if not lines[index + 2].startswith(prefix):
        raise ValueError("Password unavailable")
    password = lines[index + 2][len(prefix):]
    if not password:
        raise ValueError("Empty password")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPCookieProcessor(cookies),
    )
    request = urllib.request.Request(
        "https://" + site + "/api/method/login",
        data=urllib.parse.urlencode({"usr": "Administrator", "pwd": password}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError("Login failed")
        result = json.load(response)
    if result.get("message") != "Logged In":
        raise ValueError("Login not confirmed")
    sessions = [cookie.value for cookie in cookies if cookie.name == "sid" and cookie.value != "Guest"]
    if len(sessions) != 1 or any(c in sessions[0] for c in "\r\n;"):
        raise ValueError("Session not confirmed")
    return {"Cookie": "sid=" + sessions[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", choices=SITES)
    args = parser.parse_args()
    try:
        print(json.dumps(authenticated_headers(args.site)))
    except Exception:
        # HTTP exception bodies, request objects, and cookie values are private.
        print("Frappe MCP login failed; check the protected access file and site availability.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
