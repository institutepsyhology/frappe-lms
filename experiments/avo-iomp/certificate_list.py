"""Replace IOMP's old certificate widget with the learner's certificate list."""

from importer import Review
from normalize_reviewed_pairs import _digest


PAGE_ROUTE = 'personal/certificate'
PAGE_URL = 'https://my-lk.iomp.ru/' + PAGE_ROUTE
LINK_LABEL = 'Мои сертификаты'
PURCHASE_BUTTON = 'c39ebef01965badf6e6a116f6658d93fae5266d93634940123d3ceb1d8b2d7bc'
PREPARED_PURCHASE_BUTTON = '0f3c855c4fedfb4c1fdac67506820c69375a544f67bd395741b088861cccea59'
TARGETS = {('296', str(i)) for i in range(5726, 5737)} | {
    ('280', '5299'), ('291', '5530'), ('318', '5874'), ('326', '6037'),
}
# Fingerprint only the widget and its two-column section. Outside text, offers,
# links and layout are retained even if the author updates them.
WIDGETS = {
    ('287cdc5cbf1bce802c2a947c0e6f7685707ff4d728cbf81d9b2efb672645592f',
     '6985be0ef3148e70106df583698f21f99357c576e40d3d5400b573edb3d3092c'),
    ('3252fac78ad330cda679d524d59a7adb08a94731a454a37f9dcd548f41e354ed',
     '2d20fdba257b8b93463cf77785efa45b95e19ade6c0b64dbfaf6974088418718'),
}


def normalize_certificate_list(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != (
            'iomp', 'https://shop.iomp.ru', 'ape'):
        return
    identity = str(payload.get('course_id')), str(payload.get('lesson_id'))
    if identity == ('271', '5069'):
        matches = [(node, _digest(node)) for node in payload['ape'].get('children', [])
                   if node.get('name') == 'button']
        matches = [(node, digest) for node, digest in matches if digest in (PURCHASE_BUTTON, PREPARED_PURCHASE_BUTTON)]
        if len(matches) != 1:
            raise Review('certificate_widget_changed', [{'lesson_id': '5069', 'codes': ['certificate_widget_changed']}])
        node, digest = matches[0]
        if digest == PURCHASE_BUTTON:
            del node['fields']['visibleConditions']
            node['fields'].update(html=LINK_LABEL, url=PAGE_URL)
        return
    if identity not in TARGETS:
        return
    children = payload['ape'].get('children', [])
    widgets = [index for index, node in enumerate(children) if node.get('name') == 'text'
               and '{certificate_iframe}' in node.get('fields', {}).get('html', '')]
    links = [node for node in children if node.get('name') == 'button'
             and node.get('fields', {}).get('html') == LINK_LABEL and node['fields'].get('url') == PAGE_URL]
    if len(links) == 1 and not widgets:
        return
    if len(widgets) == 1 and not links:
        index = widgets[0]
        pair = children[index:index + 2]
        if len(pair) == 2 and tuple(_digest(node) for node in pair) in WIDGETS:
            original = pair[1]['children'][0]['children'][0]
            link = {**original, 'fields': {**original['fields'], 'html': LINK_LABEL, 'url': PAGE_URL}}
            children[index:index + 2] = [link]
            return
    raise Review('certificate_widget_changed', [{'lesson_id': str(payload['lesson_id']),
                                                 'codes': ['certificate_widget_changed']}])


def certificate_page_document():
    """Native Frappe Web Page, rendered for the current session without page caching."""
    return {
        'doctype': 'Web Page', 'route': PAGE_ROUTE, 'title': LINK_LABEL, 'published': 1,
        'content_type': 'HTML', 'show_title': 1, 'show_sidebar': 0, 'dynamic_template': 1,
        'main_section_html': """
{% if not frappe.session.user or frappe.session.user == "Guest" %}
<p><a id="certificate-login" href="/login?redirect-to=%2Fpersonal%2Fcertificate">Войти, чтобы открыть сертификаты</a></p>
{% else %}
{% set requested = frappe.form_dict.get('page', '1') | string %}
{% set page = requested | int if requested.isascii() and requested.isdigit() and requested|length <= 7 else 1 %}
{% set page = [page, 1] | max %}
{% set size = 50 %}
{% set certificates = frappe.get_list('LMS Certificate', fields=['name', 'course_title', 'batch_title', 'issue_date', 'template'], filters={'member': frappe.session.user}, order_by='issue_date desc, name asc', limit_start=(page - 1) * size, limit_page_length=size + 1) %}
<section id="personal-certificate-list">
{% if certificates %}
<ul>
{% for row in certificates[:size] %}
{% set args = {'doctype': 'LMS Certificate', 'name': row.name} %}
{% if row.template %}{% set args = dict(args, format=row.template) %}{% endif %}
<li><a href="/api/method/frappe.utils.print_format.download_pdf?{{ args | urlencode | e }}">{{ (row.course_title or row.batch_title or 'Сертификат') | e }}</a>{% if row.issue_date %} — {{ frappe.format_date(row.issue_date) | e }}{% endif %}</li>
{% endfor %}
</ul>
{% elif page == 1 %}
<p>У вас пока нет выданных сертификатов.</p>
{% else %}
<p>На этой странице нет сертификатов.</p>
{% endif %}
{% if page > 1 or certificates|length > size %}
<nav aria-label="Страницы сертификатов">
{% if page > 1 %}<a rel="prev" href="?page={{ page - 1 }}">Предыдущая</a>{% endif %}
<span>Страница {{ page }}</span>
{% if certificates|length > size %}<a rel="next" href="?page={{ page + 1 }}">Следующая</a>{% endif %}
</nav>
{% endif %}
</section>
{% endif %}
""".strip(),
        'javascript': """
const certificateLogin = document.getElementById('certificate-login');
if (certificateLogin) window.location.replace(certificateLogin.href);
""".strip(),
    }
