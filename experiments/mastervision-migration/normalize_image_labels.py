"""Consume only the known invisible AVO image-editor label, preserving the image.

Verified shipped renderer evidence (no vendor JS or lesson content is embedded):
current SHA256 4b28b5f5cac90dec5a6b0bf1e42c05aa5e9c2de412b1bd027164f8e7928ee379
reads imageSrc/linkHref/linkTarget; legacy SHA256
9cb867372194527bed4ec03dff82c969c137a2962dc94a3fe6a12a47374ac55e
reads imageSrc/linkHref. Neither image render function reads the html field.
The caller retains that exact field in its private original APE snapshot.
"""
import copy

from importer import ACCOUNT,ORIGIN,Review
from normalize_editor_nodes import _core,_style_content


CODE='image_label_preserved'


def _known_invisible_label(node):
    fields=node.get('fields',{});style=node.get('style')
    return (fields.get('html')=='Изображение' and not node.get('children',[])
            and not set(node)-{'id','name','fields','children','style'}
            and not set(fields)-{'anchor','html','imageSrc','linkHref'}
            and fields.get('anchor') in (None,'') and fields.get('linkHref') in (None,'')
            and _core()._url(fields.get('imageSrc'))
            and (style is None or isinstance(style,dict)) and not _style_content(style))


def normalize_image_labels(ape,validate_static):
    """Return copied APE and metadata; keep visible captions/unknown settings intact.

    No visible caption, wrapper or new node is generated: the source renderer
    does not display this one exact editor label. Image IDs/styles/URLs/order
    remain unchanged. The validator argument keeps the shared normalizer API.
    """
    if (ACCOUNT,ORIGIN)!=('mastervision','https://shop.mastervision.su'):
        raise Review('normalization_account_mismatch')
    if not callable(validate_static):raise Review('image_labels_validator_invalid')
    if not isinstance(ape,dict) or ape.get('name')!='page' or not isinstance(ape.get('children'),list):
        raise Review('image_labels_invalid')
    try:copied=copy.deepcopy(ape)
    except (TypeError,RecursionError):raise Review('image_labels_invalid') from None
    changes=[];visited=0
    def walk(node,path):
        nonlocal visited
        visited+=1
        if visited>150000 or len(path)>100 or not isinstance(node,dict) or not isinstance(node.get('name'),str):
            raise Review('image_labels_invalid')
        fields,children=node.get('fields',{}),node.get('children',[])
        if not isinstance(fields,dict) or not isinstance(children,list):raise Review('image_labels_invalid')
        if fields.get('visibleConditions') not in (None,'',False,[],{}):return
        if node['name']=='image':
            if not _known_invisible_label(node):return
            del fields['html'];changes.append({'path':list(path),'code':CODE})
        for index,child in enumerate(children):walk(child,path+[index])
    walk(copied,[])
    return copied,changes
