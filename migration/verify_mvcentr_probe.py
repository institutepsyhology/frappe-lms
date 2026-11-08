"""Verify the first eligible imported user without revealing contact data."""
import collections
import http.cookiejar
import importlib.util
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("migration", ROOT / "contacts-api/import_mvcentr_users.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
freq = collections.Counter(m.email_of(record) for _, record in m.load())
data = next(p for ident, record in m.load() if (p := m.payload(ident, record)) and freq[p["email"]] == 1)
spec = importlib.util.spec_from_file_location("auth", ROOT / "frappe-mcp/headers.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
headers = auth.authenticated_headers("my-lk.mv-centr.ru")
url = m.SITE + "/api/v2/document/User/" + urllib.parse.quote(data["email"], safe="")
with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
    doc = json.load(response).get("data", {})
fields = ["custom_avo_contact_id", "custom_avo_account", "custom_avo_telegram_id", "custom_avo_telegram_username", "custom_avo_vk_id", "custom_avo_vk_username"]
matches = all(str(doc.get(f) or "") == data[f] for f in fields)
body = urllib.parse.urlencode({"usr": data["email"], "pwd": data["new_password"]}).encode()
try:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), auth.NoRedirect(), urllib.request.HTTPCookieProcessor(jar))
    with opener.open(urllib.request.Request(m.SITE + "/api/method/login", data=body), timeout=20) as response:
        result = json.load(response)
        print(json.dumps({"login_http_status": response.status, "message_type": type(result.get("message")).__name__, "has_home_page": "home_page" in result, "has_full_name": "full_name" in result}))
        has_session = any(c.name == "sid" and c.value != "Guest" for c in jar)
        with opener.open(m.SITE + "/api/method/frappe.auth.get_logged_user", timeout=20) as check:
            login = has_session and json.load(check).get("message") == data["email"]
except urllib.error.HTTPError as exc:
    print(json.dumps({"login_http_status": exc.code}))
    login = False
except Exception as exc:
    print(json.dumps({"login_error_type": type(exc).__name__}))
    login = False
print(json.dumps({"fields_match": matches, "password_login": login}))

