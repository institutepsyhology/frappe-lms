"""Expose verified native accordion content in its original reading order."""
import copy
import hashlib
import json

from importer import Review
from normalize_editor_nodes import _style_content


CODE='accordion_content_flattened'
NODE_KEYS={'id','name','fields','children','style'}
OPTIONAL={'anchor','visibleConditions'}


def _protected(node, allowed):
    fields=node.get('fields',{})
    return (bool(set(node)-NODE_KEYS) or bool(set(fields)-allowed)
            or fields.get('anchor') not in (None,'',False)
            or fields.get('visibleConditions') not in (None,'',False,[],{})
            or _style_content(node.get('style')))


def _parent_supported(node):
    fields=node.get('fields',{})
    return (not _protected(node,OPTIONAL|{'initialState','expandedSpeedRate','onlyOneExpanded'})
            and fields.get('initialState')=='all-folded'
            and type(fields.get('expandedSpeedRate')) is int and fields['expandedSpeedRate']==1
            and fields.get('onlyOneExpanded') is True)


def _item_supported(node, validate):
    fields=node.get('fields',{});header=fields.get('headerHtml')
    if _protected(node,OPTIONAL|{'headerHtml'}) or not isinstance(header,str) or not header.strip(): return False
    try: validate(header)
    except (ValueError,UnicodeError,RecursionError): return False
    return True


def normalize_accordions(ape, validate_static):
    """Copy supported accordions to containers; retain protected subtrees exactly.

    Only the observed presentation controls are consumed. Header HTML is copied
    intact before the item's original children; no scripts or code are enabled.
    The caller retains the exact original APE in its private source metadata.
    """
    if not callable(validate_static): raise Review('accordions_validator_invalid')
    if not isinstance(ape,dict) or ape.get('name')!='page' or not isinstance(ape.get('children'),list):
        raise Review('accordions_invalid')
    try: copied=copy.deepcopy(ape)
    except (TypeError,RecursionError): raise Review('accordions_invalid') from None
    used=set();visited=0;changes=[]
    def reserve(node,path):
        nonlocal visited
        visited+=1
        if visited>150000 or len(path)>100 or not isinstance(node,dict) or not isinstance(node.get('name'),str):
            raise Review('accordions_invalid')
        if not isinstance(node.get('fields',{}),dict) or not isinstance(node.get('children',[]),list):
            raise Review('accordions_invalid')
        if isinstance(node.get('id'),str): used.add(node['id'])
        for index,child in enumerate(node.get('children',[])): reserve(child,path+[index])
    reserve(copied,[])

    def header_id(path,header):
        value=json.dumps([path,header],ensure_ascii=True,separators=(',',':')).encode('utf-8')
        base='avo-accordion-header-'+hashlib.sha256(value).hexdigest()[:40]
        candidate=base;number=1
        while candidate in used:
            number+=1;candidate=base+'-'+str(number)
        used.add(candidate)
        return candidate

    def walk(node,path):
        kind=node['name'];children=node.get('children',[])
        if kind=='unfolding':
            if not _parent_supported(node): return node
            node['name']='container';node['fields']={}
            changes.append({'path':list(path),'code':CODE})
        elif kind=='unfolding-item':
            if not _item_supported(node,validate_static): return node
            header=node['fields']['headerHtml'];node['name']='container';node['fields']={}
            changes.append({'path':list(path),'code':CODE})
            kept=[walk(child,path+[index]) for index,child in enumerate(children)]
            node['children']=[{'id':header_id(path,header),'name':'text','fields':{'html':header},'children':[]}]+kept
            return node
        if 'children' in node: node['children']=[walk(child,path+[index]) for index,child in enumerate(children)]
        return node
    return walk(copied,[]),changes
