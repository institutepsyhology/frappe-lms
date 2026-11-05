"""Read an AVO course's literal lesson tree without running page scripts."""
import ast
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from page_extract import Page, ORIGIN, MAX_PAGE_CHARS


def _literal_array(script, start):
    if start >= len(script) or script[start] != '[':
        raise ValueError('source_structure_error')
    depth, quote, escaped = 0, None, False
    for i in range(start, min(len(script), start + 16 * 1024 * 1024)):
        c = script[i]
        if quote:
            if escaped: escaped = False
            elif c == '\\': escaped = True
            elif c == quote: quote = None
        elif c in "'\"": quote = c
        elif c in '[{': depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0:
                text = script[start:i + 1]
                try:
                    node = ast.parse(text, mode='eval')
                    class Literals(ast.NodeTransformer):
                        def visit_Name(self, n):
                            if n.id not in ('true', 'false', 'null'): raise ValueError('source_structure_error')
                            return ast.copy_location(ast.Constant({'true':True,'false':False,'null':None}[n.id]), n)
                    return ast.literal_eval(Literals().visit(node))
                except (SyntaxError, ValueError, RecursionError, MemoryError):
                    raise ValueError('source_structure_error') from None
    raise ValueError('source_structure_error')


def course_lessons_from_html(html, course_id):
    if type(course_id) is not int or course_id < 1 or not isinstance(html,str) or not html or len(html)>MAX_PAGE_CHARS:
        raise ValueError('source_structure_error')
    page=Page();page.feed(html)
    trees=[]
    for script in page.scripts:
        for match in re.finditer(r'\.LessonsEditor\s*\(',script):
            field=re.search(r"['\"]trainingLessonsTree['\"]\s*:\s*",script[match.end():match.end()+1000])
            if field:
                start=match.end()+field.end()
                trees.append(_literal_array(script,start))
    if len(trees)!=1 or not isinstance(trees[0],list): raise ValueError('source_structure_error')
    ids=[]
    def walk(value, depth=0):
        if depth>128: raise ValueError('source_structure_error')
        if isinstance(value,list):
            for item in value: walk(item,depth+1)
        elif isinstance(value,dict):
            if 'id_training_lessons' in value:
                lesson=value['id_training_lessons']
                if type(lesson) is not int or lesson<1 or value.get('id_training')!=course_id: raise ValueError('source_identity_mismatch')
                link=value.get('links',{}).get('update','') if isinstance(value.get('links'),dict) else ''
                u=urlsplit(urljoin(ORIGIN,link)); q=parse_qs(u.query)
                if u.scheme+'://'+u.netloc!=ORIGIN or u.path!='/shop/training/traininglessons/admin/update' or q.get('id')!=[str(lesson)]:
                    raise ValueError('source_identity_mismatch')
                ids.append(lesson)
            else:
                for child in value.values():
                    if isinstance(child,(dict,list)): walk(child,depth+1)
    walk(trees[0])
    if not ids or len(ids)!=len(set(ids)): raise ValueError('source_structure_error')
    return ids
