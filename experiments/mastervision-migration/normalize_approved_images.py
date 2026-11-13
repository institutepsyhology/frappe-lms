"""Omit scoped references to the owner's approved missing-image files."""
import copy
import hashlib

from importer import ACCOUNT,ORIGIN,Review
from normalize_editor_nodes import _style_content


CODE='owner_approved_missing_image_omitted'
PATH=[0,0,0]
A='b818cf308e8653fb70263908a40f410f5680d9a3ace670884fe45f4bd2f38a25'
B='656420023fc55b84b2fe8c69ca647b3f3305e9e414cba50dfcab6a5fa5946c14'
C='fc93e347a1ef59ba7b9b32601c74cb670ee69f34403eea8f854f11768224aab8'
APPROVED={(377,lid):(B if lid==3189 else A) for lid in range(3185,3196)}
APPROVED.update({(486,lid):(B if lid==4662 else A) for lid in range(4658,4669)})
APPROVED.update({(331,lid):(B if lid==2779 else A)
                 for lid in (2775,2776,2777,2778,2779,2780,2782,2783,2784,2785,2786)})
APPROVED.update({(280,1802):C,(286,1857):C})
APPROVED_PATHS={(280,1802):[7],(286,1857):[7]}


def _children(node,index):
    if not isinstance(node,dict) or not isinstance(node.get('children'),list):return None
    fields=node.get('fields',{})
    if (not isinstance(fields,dict) or fields.get('visibleConditions') not in (None,'',False,[],{})
            or len(node['children'])<=index):return None
    return node['children']


def normalize_approved_images(ape,course_id,lesson_id):
    """Copy the tree and remove only a bound, unchanged original-path image.

    Unknown fields, captions, links, media styles and changed source hashes stay
    intact for review. The caller retains the complete original APE snapshot.
    This helper must run before other normalizers can change the original path.
    """
    if (ACCOUNT,ORIGIN)!=('mastervision','https://shop.mastervision.su'):
        raise Review('normalization_account_mismatch')
    copied=copy.deepcopy(ape)
    if (type(course_id) is not int or type(lesson_id) is not int
            or not isinstance(copied,dict) or copied.get('name')!='page'):return copied,[]
    expected=APPROVED.get((course_id,lesson_id))
    if expected is None:return copied,[]
    path=APPROVED_PATHS.get((course_id,lesson_id),PATH)
    parent=copied
    for index in path[:-1]:
        children=_children(parent,index)
        if children is None:return copied,[]
        parent=children[index]
    children=_children(parent,path[-1])
    if children is None:return copied,[]
    node=children[path[-1]]
    if (not isinstance(node,dict) or node.get('name')!='image'
            or set(node)-{'id','name','fields','children','style'} or node.get('children',[])!=[]):return copied,[]
    fields=node.get('fields');style=node.get('style')
    if (not isinstance(fields,dict) or set(fields)-{'anchor','imageSrc','linkHref','html'}
            or any(fields.get(key) not in (None,'') for key in ('anchor','linkHref','html'))
            or style is not None and not isinstance(style,dict) or _style_content(style)):return copied,[]
    url=fields.get('imageSrc')
    if not isinstance(url,str):return copied,[]
    try:digest=hashlib.sha256(url.encode('utf-8')).hexdigest()
    except UnicodeError:return copied,[]
    if digest!=expected:return copied,[]
    children.pop(path[-1])
    return copied,[{'path':list(path),'code':CODE,'url_sha256':digest}]
