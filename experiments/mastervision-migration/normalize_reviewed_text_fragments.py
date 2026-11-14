"""Preserve reviewed text while omitting the owner's excluded trainer action."""
import copy
import hashlib
import json
from html import unescape
from html.parser import HTMLParser
import re

from importer import Review
from normalize_remaining_static_material import _signature, _number
from normalize_legacy_html_decorations import _has_content_style

TRAINER_CODE = 'reviewed_named_trainer_link_omitted'
PRICING_CODE = 'reviewed_pricing_presentation_normalized'
PADDING_CODE = 'reviewed_ltr_padding_preserved'
APPROVED = {
    (321, 2563): (((1,), 'bf8ffef3eaf5057740e1a80049cdfdac2abdc542e5c00c4e905e58b682c0bbdb', 'trainer'),),
    (321, 2564): (((1,), 'cad98ba519eadb02d085339fbe5a9eef3070d3ddaa408ca8b43f866de0d75024', 'trainer'),),
    (322, 3126): (((1,), 'bf8ffef3eaf5057740e1a80049cdfdac2abdc542e5c00c4e905e58b682c0bbdb', 'trainer'),),
    (322, 3127): (((1,), 'cad98ba519eadb02d085339fbe5a9eef3070d3ddaa408ca8b43f866de0d75024', 'trainer'),),
    (470, 4425): (((1,), 'bf8ffef3eaf5057740e1a80049cdfdac2abdc542e5c00c4e905e58b682c0bbdb', 'trainer'),),
    (470, 4426): (((1,), 'cad98ba519eadb02d085339fbe5a9eef3070d3ddaa408ca8b43f866de0d75024', 'trainer'),),
    (366, 3178): (((1,), '35a03ba2067e18bf3b4829823b06f9b281053c7ecad56e42d86b323cefbc0454', 'padding'),),
    (635, 7348): (
        ((1, 0, 0), 'afcd3a722df374f530c010b8e35d65b2892cb5431d12834ff621db40e7c048aa', 'pricing'),
        ((1, 0, 1), '496e1c3daddb78e4c9e59a23f14f9906dbc134b130bddc08a947add84d157651', 'pricing'),
        ((1, 1, 0), 'c46559a2684719f4885c105907dd4123055fecafec372d15b728d070decc3497', 'pricing'),
        ((1, 1, 1), '5f9f35ec15f876b0a569dcd02baa8598a81f53edf617f206ff81730a15c47895', 'pricing'),
        ((3, 0, 0), '8249e67e2f4a9749a93c8724d60cc62716c31f24a05c401058cbf2d4b68edc27', 'pricing'),
        ((3, 0, 1), '9938bd48de3e9ba10c3ba44d11c720eca0556782409a2b93d22dbaf8df03a54a', 'pricing'),
        ((3, 1, 0), '9d64734e3c5fd0fd0dd90f0d9b2d82a6c10772459e661d6442c7f05b0955469c', 'pricing'),
        ((3, 1, 1), '0debeb96d85d37865c52f1ae075b0bb6f0c9bf9db64cab4a64c6a2247ebf2902', 'pricing')),
}
STYLE_BINDINGS = {
    **{(cid,lid,(1,)): style for cid,lids,style in (
        (321,(2563,2564),'46aa4ff69168b62acda60f1101ff957c67267fa24fc17dbcba2a498f22b4a6ed'),
        (322,(3126,3127),'431d7a92ccb15eecde8f0f0d623365b2a6b4de0288ba53eb33f485b74ea9ee7b'),
        (470,(4425,4426),'5cd67213198f2c24212fc2151e7d2fab1e807511bc38b1e3640c87ee4ad72788')) for lid in lids},
    (366,3178,(1,)):'390f0379eab6aa72476727498623a16c44356b2c45ab81d3af9170688e16b69f',
    **{(635,7348,path):style for path,style in (
        ((1,0,0),'4c528480f71fc6954586ea2980be95e494d62482b0aa1fbb1bdb5b6b89205b5f'),
        ((1,0,1),'4f5f469a16469bed98c13e4df60858f55b32f892f11f48c019f7d67002dac90e'),
        ((1,1,0),'716761e62c1e6fc4b21c09b84bdc9f1c135bf615c0db0fd4d70c0cd049e9f392'),
        ((1,1,1),'4f5f469a16469bed98c13e4df60858f55b32f892f11f48c019f7d67002dac90e'),
        ((3,0,0),'4f5f469a16469bed98c13e4df60858f55b32f892f11f48c019f7d67002dac90e'),
        ((3,0,1),'4f5f469a16469bed98c13e4df60858f55b32f892f11f48c019f7d67002dac90e'),
        ((3,1,0),'4c528480f71fc6954586ea2980be95e494d62482b0aa1fbb1bdb5b6b89205b5f'),
        ((3,1,1),'4f5f469a16469bed98c13e4df60858f55b32f892f11f48c019f7d67002dac90e'))},
}
PRICING_STYLE = ('display: block; text-align: center; color: rgb(255, 255, 255); '
                 'background-image: linear-gradient(rgb(0, 136, 204), rgb(0, 68, 204)); '
                 'border-radius: 5px; font-size: 17px; font-family: Arial, Helvetica, sans-serif; '
                 'font-weight: normal; font-style: normal; text-decoration: none; '
                 'height: 40px; line-height: 40px; width: 180px;')
SAFE_PRICING_STYLE = ('text-align:center;color:rgb(255,255,255);background-color:rgb(0,102,204);'
                      'font-size:17px;font-family:Arial,Helvetica,sans-serif;'
                      'font-weight:normal;font-style:normal;text-decoration:none;padding:10px')
STYLE_ATTR = re.compile(r'''\s+style\s*=\s*(["'])(.*?)\1''', re.S | re.I)


def _review(): raise Review('reviewed_text_fragment_requires_review')


class _Edits(HTMLParser):
    def __init__(self, source, action):
        super().__init__(convert_charrefs=True)
        self.source, self.action = source, action
        self.starts = [0] + [i + 1 for i, c in enumerate(source) if c == '\n']
        self.active, self.edits, self.removed, self.pricing, self.centers = None, [], 0, 0, 0
        self.feed(source); self.close()
        if self.active is not None: _review()

    def pos(self):
        line, column = self.getpos(); return self.starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if len(dict(attrs)) != len(attrs): _review()
        if tag == 'center' and self.action == 'pricing':
            if attrs: _review()
            self.edits.append((self.pos(), self.pos() + len(self.get_starttag_text()), '<div style="text-align:center">'))
            self.centers += 1
        if tag == 'a':
            if self.active is not None: _review()
            self.active = [self.pos(), []]
            if self.action == 'pricing':
                if dict(attrs).get('style') != PRICING_STYLE: _review()
                opening = self.get_starttag_text(); matches = list(STYLE_ATTR.finditer(opening))
                if len(matches) != 1 or unescape(matches[0][2]) != PRICING_STYLE: _review()
                match = matches[0]
                self.edits.append((self.pos() + match.start(), self.pos() + match.end(), ' style="' + SAFE_PRICING_STYLE + '"'))
                self.pricing += 1

    def handle_data(self, data):
        if self.active is not None: self.active[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'center' and self.action == 'pricing':
            end = re.match(r'</\s*center\s*>', self.source[self.pos():], re.I)
            if not end: _review()
            self.edits.append((self.pos(), self.pos() + len(end[0]), '</div>'))
        if tag == 'a':
            if self.active is None: _review()
            end = re.match(r'</\s*a\s*>', self.source[self.pos():], re.I)
            if not end: _review()
            if self.action == 'trainer':
                label = ' '.join(' '.join(self.active[1]).split())
                if re.fullmatch(r'Задать вопрос тренеру курса(?: [А-Яа-яЁё-]+){2,5}', label, re.I):
                    self.edits.append((self.active[0], self.pos() + len(end[0]), '')); self.removed += 1
            self.active = None

    def rendered(self):
        if self.action == 'trainer' and self.removed != 1: _review()
        if self.action == 'pricing' and (self.pricing != 1 or self.centers != 1): _review()
        result = self.source
        for start, end, replacement in sorted(self.edits, reverse=True): result = result[:start] + replacement + result[end:]
        return result


def normalize_reviewed_text_fragments(ape, course_id, lesson_id, validate):
    context = (_number(course_id), _number(lesson_id))
    if (not isinstance(ape, dict) or ape.get('name') != 'page' or not callable(validate)
            or None in context):
        raise Review('reviewed_text_source_invalid')
    try: copied = copy.deepcopy(ape)
    except (TypeError, RecursionError): raise Review('reviewed_text_source_invalid') from None
    changes = []
    for path, expected, action in APPROVED.get(context, ()):
        node = copied
        try:
            for index in path: node = node['children'][index]
            fields = node['fields']; markup = fields['html']
            if (node.get('name') != 'text' or node.get('children') or not isinstance(markup, str)
                    or set(fields) - {'anchor', 'html'} or fields.get('anchor') not in (None, '')):
                raise ValueError()
        except (KeyError, IndexError, TypeError, ValueError):
            raise Review('reviewed_text_source_invalid') from None
        try: actual = hashlib.sha256(markup.encode()).hexdigest()
        except UnicodeError: raise Review('reviewed_text_source_invalid') from None
        if actual != expected:
            raise Review('reviewed_text_source_changed')
        style = node.get('style', {})
        try: style_hash = hashlib.sha256(json.dumps(style,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        except (TypeError,ValueError,UnicodeError,RecursionError): raise Review('reviewed_text_source_invalid') from None
        if (set(node)-{'id','name','fields','style','children'} or _has_content_style(style)
                or STYLE_BINDINGS.get((*context,path),style_hash)!=style_hash):
            raise Review('reviewed_text_source_changed')
        if action == 'padding':
            if (markup.count('padding-inline-start:48px') != 1
                    or re.search(r'''\bdir\s*=\s*["']rtl["']''', markup, re.I)):
                _review()
            rewritten = markup.replace('padding-inline-start:48px', 'padding-left:48px', 1)
            headings = list(re.finditer(r'<h4\b[^>]*>',rewritten,re.I))
            if len(headings)!=1: _review()
            opening=headings[0]
            if ' role="presentation"' in opening[0]:
                rewritten=rewritten[:opening.start()]+opening[0].replace(' role="presentation"','',1)+rewritten[opening.end():]
            if _signature(markup) != _signature(rewritten): raise Review('reviewed_text_material_mismatch')
        else: rewritten = _Edits(markup, action).rendered()
        if action == 'pricing':
            comparable = markup.replace('<center>', '<div style="text-align:center">').replace('</center>', '</div>')
            if _signature(comparable) != _signature(rewritten): raise Review('reviewed_text_material_mismatch')
        elif action not in ('trainer', 'padding'): _review()
        try: validate(rewritten)
        except (ValueError, UnicodeError, RecursionError): _review()
        fields['html'] = rewritten
        changes.append({'path': list(path), 'code': {'trainer':TRAINER_CODE, 'pricing':PRICING_CODE, 'padding':PADDING_CODE}[action],
                        'removed_links': 1 if action == 'trainer' else 0})
    return copied, changes
