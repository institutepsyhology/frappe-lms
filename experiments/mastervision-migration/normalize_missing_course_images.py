"""Omit only owner-approved, source-bound HTTP404 course images; never fetch URLs.

The bindings were checked anonymously on 2026-11-13.  They describe original
Master Vision APE, before image extraction. Only IMG tags and image-only span
tags around them are removed; surrounding text and links remain byte-exact. The
normal caller must retain the original APE witness and run the usual converter.
"""
import copy
import hashlib
from html import unescape
from html.parser import HTMLParser
import re

from importer import ACCOUNT, ORIGIN, Review
from normalize_legacy_html_decorations import _has_content_style
from normalize_static_presentation import _material
from normalize_static_presentation import VOID

CODE = 'owner_confirmed_missing_course_image_omitted'


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _review():
    raise Review('missing_course_image_binding_requires_review')


class _Images(HTMLParser):
    def __init__(self, source, wanted):
        super().__init__(convert_charrefs=False)
        self.source, self.wanted, self.found, self.ranges = source, wanted, [], []
        self.lines = [0] + [i + 1 for i, char in enumerate(source) if char == '\n']
        self.tree = {'tag': '', 'children': []}
        self.stack, self.wrappers = [self.tree], 0

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        line, column = self.getpos()
        start = self.lines[line - 1] + column
        node = {'tag': tag, 'attrs': attrs, 'children': [], 'start': start, 'opening': raw, 'missing': False}
        self.stack[-1]['children'].append(node)
        if tag not in VOID:
            self.stack.append(node)
        if tag != 'img':
            return
        values = dict(attrs)
        src = values.get('src')
        if not isinstance(src, str):
            return
        pair = [_sha(src), _sha(raw)]
        if pair not in self.wanted:
            return
        if (len(values) != len(attrs) or set(values) - {'src', 'width', 'height', 'alt'}
                or values.get('alt') not in (None, '')):
            _review()
        if self.source[start:start + len(raw)] != raw:
            _review()
        self.found.append(pair)
        self.ranges.append((start, start + len(raw)))
        node['missing'] = True

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if len(self.stack) < 2 or self.stack[-1]['tag'] != tag:
            _review()
        node = self.stack.pop()
        line, column = self.getpos()
        node['closing_start'] = self.lines[line - 1] + column
        end = self.source.find('>', node['closing_start'])
        if end < 0:
            _review()
        node['closing_end'] = end + 1

    def handle_data(self, value): self.stack[-1]['children'].append(value)
    def handle_entityref(self, value): self.handle_data('&' + value + ';')
    def handle_charref(self, value): self.handle_data('&#' + value + ';')
    def handle_comment(self, value): self.handle_data('<!--' + value + '-->')

    def select_wrappers(self, validate):
        if len(self.stack) != 1:
            _review()
        def only_missing(node):
            if isinstance(node, str):
                return (0, not unescape(node).strip())
            if node['tag'] == 'img':
                return (1, True) if node['missing'] else (0, False)
            if node['tag'] != 'span' or set(dict(node['attrs'])) - {'style'}:
                return 0, False
            if len(dict(node['attrs'])) != len(node['attrs']):
                return 0, False
            # These unsupported styles are inert only around a proven missing
            # image. Validate every other declaration with the normal policy.
            css = dict(node['attrs']).get('style', '')
            if not isinstance(css, str): return 0, False
            kept, seen = [], set()
            for piece in css.split(';'):
                if not piece.strip(): continue
                if ':' not in piece: return 0, False
                key, value = (part.strip() for part in piece.split(':', 1))
                key = key.lower()
                if key in seen: return 0, False
                seen.add(key)
                if key in {'display', 'overflow', 'transform'}:
                    if (key, value) not in {('display', 'inline-block'), ('overflow', 'hidden'),
                                            ('transform', 'rotate(3.14rad)')}:
                        return 0, False
                elif key in {'width', 'height'}:
                    match = re.fullmatch(r'([1-9][0-9]{0,3})px', value)
                    if not match or int(match[1]) > 4096:
                        return 0, False
                else:
                    kept.append(piece)
            from html import escape
            style = ';'.join(kept)
            probe = '<span' + (' style="' + escape(style, quote=True) + '"' if style else '') + '>proof</span>'
            try: validate(probe)
            except (ValueError, UnicodeError, RecursionError): return 0, False
            proofs = [only_missing(child) for child in node['children']]
            count = sum(proof[0] for proof in proofs)
            return count, bool(count and all(proof[1] for proof in proofs))
        def visit(node):
            if isinstance(node, str): return
            count, safe = only_missing(node)
            if node['tag'] == 'span' and safe:
                # Remove tags only: whitespace and decoded text remain exact.
                self.ranges.extend([(node['start'], node['start'] + len(node['opening'])),
                                    (node['closing_start'], node['closing_end'])])
                self.wrappers += 1
            for child in node['children']: visit(child)
        visit(self.tree)


def _merged(events):
    result = []
    for event in events:
        if result and event[0] == 'text' and result[-1][0] == 'text':
            result[-1] = ('text', result[-1][1] + event[1])
        else:
            result.append(event)
    return result


def _clean(source, binding, validate):
    digest = _sha(source)
    if digest == binding['result_sha256']:
        return None  # Exact previously authorized result; no second omission.
    if digest != binding['source_sha256']:
        _review()
    wanted = binding['images']
    parser = _Images(source, wanted)
    parser.feed(source)
    parser.close()
    parser.select_wrappers(validate)
    if sorted(parser.found) != sorted(wanted) or len(set(map(tuple, wanted))) != len(wanted):
        _review()
    cleaned = source
    for start, end in sorted(parser.ranges, reverse=True):
        cleaned = cleaned[:start] + cleaned[end:]
    if _sha(cleaned) != binding['result_sha256']:
        _review()
    hashes = {item[0] for item in wanted}
    expected = [event for event in _material(source)
                if not (event[0] == 'src' and event[1] == 'img' and _sha(event[2]) in hashes)]
    if _merged(expected) != _material(cleaned):
        raise Review('missing_course_image_material_mismatch')
    return cleaned, parser.wrappers


def normalize_missing_course_images(ape, course_id, lesson_id, validate_static):
    """Return an immutable copy and URL-free receipt for the exact approved source.

    This is a scoped omission, not HTML sanitization. Unknown markup remains
    byte-identical for subsequent strict static validation, including live IMG.
    No account can be inferred from numeric IDs: the caller must first enforce
    the Master Vision account and source-origin boundary, as normalize_payload
    does for every scoped source helper.
    """
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        raise Review('normalization_account_mismatch')
    if (not callable(validate_static) or type(course_id) is not int or course_id <= 0
            or type(lesson_id) is not int or lesson_id <= 0
            or not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list)):
        raise Review('missing_course_image_source_invalid')
    result, changes = copy.deepcopy(ape), []
    bindings = [item for item in BINDINGS
                if (item['course_id'], item['lesson_id']) == (course_id, lesson_id)]
    if not bindings:
        return result, changes
    expected = {tuple(item['path']): item for item in bindings}
    if len(expected) != len(bindings):
        _review()
    seen, visited = set(), 0

    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict):
            _review()
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list):
            _review()
        protected = protected or fields.get('anchor') not in (None, '') or any(
            fields.get(key) not in (None, '', False, [], {}) for key in ('visibleConditions', 'displayDelay'))
        binding = expected.get(tuple(path))
        if binding is not None:
            if (protected or binding['kind'] != 'html' or node.get('name') not in {'text', 'code'}
                    or children or set(fields) - {'html', 'anchor'}
                    or set(node) - {'id', 'name', 'fields', 'children', 'style'}
                    or _has_content_style(node.get('style'))
                    or not isinstance(fields.get('html'), str)):
                _review()
            cleaned = _clean(fields['html'], binding, validate_static)
            seen.add(tuple(path))
            if cleaned is not None:
                fields['html'], wrappers = cleaned
                changes.append({'path': list(path), 'code': CODE, 'images': len(binding['images']),
                                'empty_image_wrappers': wrappers,
                                'source_sha256': binding['source_sha256'],
                                'result_sha256': binding['result_sha256'],
                                'url_sha256': [item[0] for item in binding['images']]})
        for index, child in enumerate(children):
            walk(child, path + [index], protected)

    walk(result, [])
    if seen != set(expected):
        _review()
    return result, changes


BINDINGS = [{'course_id': 520,
  'lesson_id': 5171,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'feeec6e578dccfdf10949e6e5a8c43c7a1c232eb8c750e7b7f510b6a705a7b28',
  'images': [['33973737643e0ff234eda358e76b7224668b23e05b1a6dfa7686a2058847a727',
              '9cd57dbd0f7a63013eaf373173411ebb64ba586979a922a1aa8df2d2cfc40b9b'],
             ['bf6e4cad822098d6211a75368a21fa79c082b60a275845e8f2b90f9e7fc73688',
              '5d5b6b61af76de4559e8b9e3a0254a5182c8b02e6008fe66cb7a57b7d971ddcd'],
             ['de1ed5c2cb7d9c92a9d998f1ac83a7d4ca428e98f354b01a64002f1124a2b04c',
              '5167b5aba070db42bc8292c292a31fae8b938584e127590ede6c4ce7b0dbf0c0'],
             ['b7246e6715774cd059c095f4c88bdea536a0e51ff659d77e851d8aeec7b26a8b',
              'c0d0aee0d3f55fde9246b6b6e48352ad4706b22cb17b8c56ae484a05df3e0362']],
  'result_sha256': 'd5e539025ff224d020890301bc06171e3414c44b37a8a12c7836d07494b6db0b'},
 {'course_id': 520,
  'lesson_id': 5198,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'bdeb48515a8302dc5ce333509337c225cbb3ca68403c92e17e2b767387f35a8b',
  'images': [['50474d22f86ffa997c6e430ea81b26d27e6ababba6a50cf3201bb3e3f8d91db2',
              '822c0cc3f3b1345f2377ba15c3a6bf578e55b0410a021d7cdf60fbf617be8913'],
             ['7962e9738124113d59dd6190fb8ce8b6eb23dad8380aaa7ce80b516ad72bef35',
              'dde3498b91074e9796e78bd1b65174df0ae7e5c021488336398ec425a556ca34']],
  'result_sha256': '79e17600ce43394c7cb4e600f299920d09eebbcc59de0f403a440ac95f1e7f44'},
 {'course_id': 520,
  'lesson_id': 5199,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'ffcc34be16b7b010190321e64279063c235195feed6939a15fdad0ed897046fe',
  'images': [['0736d8a1cb52921737612c01aa8fe63ced52bd745c7702a4c24ee8eafc72f02b',
              'c82c02165caac6ba26c8d4558b9d686b80d5e726474b695b7bb0a2d3383b2504'],
             ['3cf5d59a903a9abf3bea5dbee54affe992a81c759cc87ce30f93203d1bcf3a09',
              'e5b68177330f607f32fabaec56437f1fec4b95cc5b71bbdcfed53af66afd32f9']],
  'result_sha256': '8f52a9d3484664c7433d75a67c04f4c01c120b5a3073a83d68a5750b2dbfe9b9'},
 {'course_id': 520,
  'lesson_id': 5200,
  'path': [2],
  'kind': 'html',
  'source_sha256': '59bc2349fc52a22af7c631dbff16bb4f1a8ed4259126475adeaa550a841bb633',
  'images': [['f534518bbb2d3231facf4ffd728c1ec5419a39f2d36c15acd87ab78b713b0ffe',
              '2a673da5dc0561016ec0b39a4641e46a1db45ccc275186a8fab47b2a50f61c9a']],
  'result_sha256': 'a43ae7c610ffb081ebd8839e4b74a6ee4e6cda0774ab7066858087aa47c5de3a'},
 {'course_id': 520,
  'lesson_id': 5201,
  'path': [2],
  'kind': 'html',
  'source_sha256': '2160d537c0de8fb8345f68035bcd7ee42db2e93298be2508943a906b6b4e1a87',
  'images': [['29ebf351f3f70264d53a061791577327ba72ffb152076f86aca3e59363fda337',
              '8818380fce8ae1737f90843f4a35e55be874d9d0a3d1f33ebd4088402833bc28'],
             ['0bacadb1df349cd3b552be7fb5f0db8b6e60ac93d459f741193522c39ace1c8d',
              '5c1a550529b5d0f2e057bba45d594b8c131f7b159ae123781faa9b834411441c'],
             ['2594b1db957a8f2b9cb19a7e16b1a65189043844befd10c0d1e5a9366fea7ef6',
              '932179511dc4415e29b93e4869577277ef40f3b394e46b3533297b84c59a8fd8']],
  'result_sha256': '176425ec53db4440649921e7f35273137cc0ba960d4fb801cb3e6424cf5f64a2'},
 {'course_id': 520,
  'lesson_id': 5203,
  'path': [2],
  'kind': 'html',
  'source_sha256': '1583c39503f35ae80e1824ea3ea18652cdbd4378b28a9c6949242667f3b683a0',
  'images': [['a9f79c5296b1706c238c2d020c35f566906d179bcc3938fd8c39646dad0d91d0',
              'e55bb90e3daaaf117bda93734f0fc45bde54c8ab5540744588ad0d752393e217'],
             ['89df200bdb97a6c000c12d444bb113bc4bf6f409a6b812f01e1e1699b1038704',
              '7b1814ff65cf4d19bffb9f7a42757c3adbbc1215a899efd4d1a763525babdb42']],
  'result_sha256': '6694d5766f736dd0a3de2293f2a26a5d16c8eb4f8c0ef0c83713ca6cd307cbd5'},
 {'course_id': 520,
  'lesson_id': 5202,
  'path': [2],
  'kind': 'html',
  'source_sha256': '195dfc7ff18f2e3d217b15200372f1fda3f8af3e03bfe946108abb3bf79bf819',
  'images': [['5859755d081a59217fb7ab0b31e8bc889cda3940c334e5063affc93b41c63282',
              '6927033c4255f48a097b34cdf57edf7a019426809e17bd79ab8db36ab4368ce6'],
             ['393d2fb3879741903cbe39869e43bf5cc8b1ad6140e1d0925a3c93ba9c91b9ca',
              '39419084f466d347eeae72d5f3f269b88cc42ac27e12594bf6d0c3ed9045519b']],
  'result_sha256': 'dac812ff4adda776f0dd789d43c294487305685ef881d4be1fb533e4a9a923a9'},
 {'course_id': 520,
  'lesson_id': 5204,
  'path': [2],
  'kind': 'html',
  'source_sha256': '4dea9268b9e61aefa289f9f5bb1aa16dcb167a5ed8c23a7a6167999ed732158c',
  'images': [['b6c66fa12c1a2f1aba613570c0b1f552efdaf747003918ba0e17230bf0beae58',
              '6b153e0bdc2b042a9291f109a21246740e67a6524a845f36d17c093443918ebc'],
             ['d740e2d3e9b91e96f0ef3f038cba120605fa7a706cb457b66f4424ace23e2507',
              '2e35dd855a8f71a657b51fa55d591ed9bd1b3d74f384497734be79ff64b0ff94']],
  'result_sha256': '9fa2242b21d128f9320fa23882b721b17ee8ca8776a1c459a8d2bd8be0ce8e79'},
 {'course_id': 520,
  'lesson_id': 5205,
  'path': [2],
  'kind': 'html',
  'source_sha256': '99dfe4d8ddffa66e3ee1784b24373a4a5e0998c76daa17ac20a40014feb40e38',
  'images': [['6bcc86711b51b9f492ed0a8f3cc47fa53a35e3cfdf70e041202dedf61d51aae0',
              'b9a58d3fe72c994f7c53725b4219b5671fc4441257f03244249feb76636cb513'],
             ['21375f096a5830558426053bca783633bd9d7e9254b36e7f8d9d9ce39deb654c',
              '0c1fca77e8b2b227200155ba948000bb54c949c1729a164cc0ad3d47e2f9c535']],
  'result_sha256': 'fa5014c68eafcc81d7a4d5c0128d6a2a01165bcd45d7bd358c990d8979f7f83c'},
 {'course_id': 520,
  'lesson_id': 5207,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'ad2c756adec009df69bfc5b48e484fd5d8bfe5d5d6b57ca3b5d054cf9fd75673',
  'images': [['161591f335310d231c8c3c798aaee9b628945aaa2ef254654198e4f187d10677',
              'b40d3d3106569cee904f5653af263302b02711c855d41c23ffd6f882826d6c2f']],
  'result_sha256': '9ec302cc2a08d5b30d6b76fcd7ab084b959bf66859083152345db4b4d9c7c04d'},
 {'course_id': 520,
  'lesson_id': 5206,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'c11b7647a14591301ed1e518b94f61df5e99c69057851df7843ce6bb686e4e33',
  'images': [['833af42fca5cbbff3cec684d874a87e46b2eeaa4c672b1176b3108328920ce78',
              'fbec0f3da0ae11250daec2fc0e909a01d3c6f8c4840768a17c139604e0039f3c'],
             ['0cfc8951569fc324cb722bf16a1fb68b3bcbdd52ad9964f7896eaf917b448e1e',
              '44c4cf54502007b953accf2802b5d2e2096c481fc3a3795ac9f486eabfa3ecdf']],
  'result_sha256': 'a75028b14b9c7b042dcc8e2b10e782c4a4f4e21b72d1a208c9a3060e0a628f37'},
 {'course_id': 520,
  'lesson_id': 5208,
  'path': [2],
  'kind': 'html',
  'source_sha256': '35c0ceeaabf8923d2acc41522b9da5c6d0f7b16cf7d21ab7c450ed4c584bab9a',
  'images': [['8964e60da380c7b0b0298c5959446990ca4eff5157efb441dbdb6df653607520',
              '04578846be9dfe9fe36540bff4efdc060141aee7fa305fcee8f8efa8595b14ec'],
             ['efabc38c8fdeb433bf7ccaeebda194fe4b2094e0cf9acc1e5f6dbb1c0a8ff685',
              'ffc7bb4611ce61dca3d81a1f731ae46d9a8200f1294893d29eeafe5c41414281']],
  'result_sha256': 'fa45bc6865f8777e16625a69f77317930a30458677919c19c4f1be35327cfa1a'},
 {'course_id': 520,
  'lesson_id': 5209,
  'path': [2],
  'kind': 'html',
  'source_sha256': '4e4310140de055f85ee015944c94329bb2671612a9768212d69f1912a21fa201',
  'images': [['3ab895c8d6afdedf15b1263308030ef9437059a986550c3597c1e8cafc72d7c4',
              'c36f342e00b25f2c686a64e1573c8712a472c87fa7488533185d13abfea2040d'],
             ['cd491c8daebb9d4a946d7f0360981898083ed031cf8d7594faf1c6d64cfa242d',
              'cfd0d6f2d4d918cd4209a3c4a6795fb1c629059eb326f7e0e46e86761f3729ed']],
  'result_sha256': 'cd589e1a9518f6a4718ac93a6566757a5e98ba1baedf313b4b63addd69a3c8ae'},
 {'course_id': 520,
  'lesson_id': 5210,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'ff36a53c6537f20b6fcd28d90b047fa45ed96230d84d5e689ec6edc16dcfb324',
  'images': [['3bf7e23dc0adb6d9234dbe4a0f7bd38e9eab536fa9513570929974858332715f',
              '3acc3a533363fb69ecf5876d92cf384ae15f3b83451eb97cc98e2aa6cc117ecf'],
             ['51ed1ce1bedbf7c2118763c9211347e0af64d4da239d5a649939383c994ad58a',
              '6b308f528379193edd7b466ddae3608d401469dcc54b9963972d8025752142da'],
             ['76281795129542b98af219644b18a2f468be3744f80412166ed21de15f7d29c3',
              '780506fd29c3330e1bc9b3c93d15149cd126df61d09f633088e2893e31b63b16']],
  'result_sha256': '23b415d835e4067655322a3dde9c53c661b982e07ca5a9e2a8d07d95ae19d5fc'},
 {'course_id': 520,
  'lesson_id': 5211,
  'path': [2],
  'kind': 'html',
  'source_sha256': '7480df184eed9bdc30b49a73d3675c0f73fda48ae71145250ce70b689e6f2bcb',
  'images': [['dfe9fadcf48bac6bdaf3916426e79dc5a4f4dd5af8e951238f3ed1e40d0be383',
              '0f1b79c51b14968ac88a7dae13000c53afb39865fb7aa8f0156b6bd55368dc1b']],
  'result_sha256': '684f4a6a5edb8ccee30b6850910851b92484384dd526a88652f420e2f1bd2e7d'},
 {'course_id': 520,
  'lesson_id': 5212,
  'path': [2],
  'kind': 'html',
  'source_sha256': '22bc0bb75dfc68cad21851c6180d8632b8eb5bddeacaa1e311eea9ef6127e76e',
  'images': [['1fd0d7b00c9484d2f24224e18b92172c25e980aa1dd1c86b5d8b5267462478d1',
              '4879de61d019b61b117c75245cf045966b9e54ff0a297969f71722984fdb898c'],
             ['5d189dd14ce58e22d35b3a03447e1151a80d7f0406edcaab61521e9d76df50c3',
              '0014fcf08845aeda717315205ff708d5a9265272982d844d1493d673dfce6b1b']],
  'result_sha256': '139ebbeb3c21358e9bb8afaca3154f1ce72cf2739e8592eb464ab9b0ab9caf7b'},
 {'course_id': 520,
  'lesson_id': 5213,
  'path': [2],
  'kind': 'html',
  'source_sha256': '918310fd046ecad8b979d9d9f8a702f596590480f5e0fc723628c5fe48e09da0',
  'images': [['473a4908802272f3b5c8cd366edd20368aa5193bb5e953d5aeffe9cc09205b9f',
              'bdbb422c9ed406b19dc660e6ab64a8538a71e21b353e27479918a83921cc3ed4'],
             ['73045eaec713d1321323963afd5deaf5be5cf4de123481b812982d72d6e0a1e7',
              'b85ee64f7c5de87c2d8d507a82610d440f10bdb39c8e014b0e02eacefd176d45']],
  'result_sha256': '44a1da441a5bb51ffba4fa27d3a993a6a968c54a2fee5cf80782cb5b9a420cef'},
 {'course_id': 520,
  'lesson_id': 5214,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'c0761e456c557ee73e9a3dfbc9a27d57ddbddb1754b6ac0e50b9b1789466ab8d',
  'images': [['367fec5a1f22489038ada37e0142f634aac160100ee098999a658e6ed41155d9',
              '3c3149fcf02b6f90322672c2f54fa1a8be1bdb3fd29fafcf2a76ef416c9de862']],
  'result_sha256': 'e8d5efe41f2619e4747d3fd0357393413ec7846c262b468d7fced8c171959f37'},
 {'course_id': 520,
  'lesson_id': 5215,
  'path': [2],
  'kind': 'html',
  'source_sha256': '5bd1a53743f7cfdbea7585691a90474839af39c72c917ffa9e3f5faf2d6c11a9',
  'images': [['574347941b942f0203c4abb7c0b39c6dc83cee7dfbf73d74807094b7e896e64e',
              '9e7781a7aae59f74225059dbaed45547770c75b4bbc0451afad75b7eb9eb11c2']],
  'result_sha256': '27cac75801f376eb851e531d8784bcd5fb8c4dbf2561062bd79c2802177f3ba5'},
 {'course_id': 520,
  'lesson_id': 5216,
  'path': [2],
  'kind': 'html',
  'source_sha256': '5b45d96058d6f3e5e6cd117194132a84bf6369f79073d6390201d5c57f17cb23',
  'images': [['b6660db84a7f436f872fd140a9f867cfd688c65983d1edd90340f53419591b1a',
              'b464907223d765c91e27c69b802b6bc8d96f53d8016d6e5143ee189eff50a5ea'],
             ['d5fe65e443b07fe9d7532ad4ede0b28ed5bc38f10d1a1c0c64fc4981e77b8c11',
              'cc622cbd821c94fe6cd44c59388cc01ba1e16affa86e30b159f4bf1fbd01cadb']],
  'result_sha256': '60d64aaec0e950ddafe1b8300328caeeaaf6dfe50ad199063b197493d8d2ee59'},
 {'course_id': 520,
  'lesson_id': 5217,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'bd941df599b51ab1720b2944bc5403bc4b8d9266f90369cdf0552e40b8d5ca2f',
  'images': [['8e806bc8f5f9035954834d6043a05171bbf80d729b611f219520697e9ba57792',
              'ece5d61c6b513ee92e462dcb050c17a86b4b4f1690bc91e1a3b836eb60a8ded1']],
  'result_sha256': '375b71e5a2d6a8132c25d8845500de73f8e728a3a3d569580ae5e018a62d28b2'},
 {'course_id': 520,
  'lesson_id': 5218,
  'path': [2],
  'kind': 'html',
  'source_sha256': '71e70e6997f96f5c004315777d81afb9e1721df9c13aadf9438ff12ee4ab5b69',
  'images': [['7be598113a8793aeea8194bc5c118c5230d7d6c4c85953dc4443fce5e8d05c52',
              'd4ea63a95622be6fedc2803075fe5f3b345b14d323f32b91275d28ba4ef31d9c']],
  'result_sha256': '3408befffd6df1e56015444526a080646fc5262d58ebc9200b6cff758f9463f9'},
 {'course_id': 520,
  'lesson_id': 5219,
  'path': [2],
  'kind': 'html',
  'source_sha256': 'e3439a95e288cb4dea4383701d73b9f979617f052d3dbec8c1e891831b4d4eba',
  'images': [['6a67e35fb3d247a278fdbd887b1dc2b83ef11538eeab14d8f0112fe8397c53c0',
              '270634531f065802ef095e4a8c09090d0d3cc57a69b2910bb488ec18f2337589']],
  'result_sha256': '64d5c6a5d1485b9772bb784a43a29d584f614b3afebd328ba6f9583182ddba75'},
 {'course_id': 520,
  'lesson_id': 5220,
  'path': [2],
  'kind': 'html',
  'source_sha256': '32910d78fbf3c494327109e4380c66701de985192ed53110afd0be2d01731e3f',
  'images': [['9df846212790152f2daf01cdaca9a4870646e0c777300297d3c3cc8244275e47',
              'f3098926ff9708a354eedc4a03ddc4f45e45c47314b50453b37bbae3ef414791']],
  'result_sha256': '92005cc769beec5aac07d4ac77e1cf8f1194dcf260db1b891b4a4ec06fc45b13'},
 {'course_id': 520,
  'lesson_id': 5221,
  'path': [2],
  'kind': 'html',
  'source_sha256': '232cae79693b2318712e5a5e0528aa592ac519f917e05bf2405eb327eaceda47',
  'images': [['27b943bdd1c06a76223d879c27da443dfe44aa676beca1f8fce5effea96180b6',
              '47a5cfa36be18a8e8ceb44c5eceaecb359f5a00ba7695f1a05e5864c64e26dc7'],
             ['1707d664599a9561fb49f7700cfb52c9815196564d42c16a14ac80500e3b233f',
              '2709725fc8400e081568977b99a8874fd69daeb5bcd33f73470231e2f5aabbd8'],
             ['1d589228f63792184d6bbc915525a9c63dcdd255451fbf4ea8fd49e804878262',
              '7ffed8c379db4d455bba7e6c0893701443fc475a2598feb6b0b1d9a13b90faa0']],
  'result_sha256': 'f4ffeb4e8bd1888cb4365466d043e3711fab94c53715d5ad770d7239e16ee1a3'},
 {'course_id': 520,
  'lesson_id': 5222,
  'path': [2],
  'kind': 'html',
  'source_sha256': '23e603fadebcfeef8933408d5813ce5cb71d5d355fe1d86f516daa5716669b48',
  'images': [['6a7b60c6cfdedde90f571c8c87d5a95b16403119b672be1aa2d9eaabc6f86ebf',
              '57c7fa06394fefc13820abcc843a8a1799e7d8d0cff0170bde63901707d9ed35']],
  'result_sha256': '2800187243d113724fee26c9adafcf3df49d67cc20aa059672c78d6962449229'}]
