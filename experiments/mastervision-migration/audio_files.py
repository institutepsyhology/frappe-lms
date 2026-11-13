"""Register verified staged MP3 bytes as private, unattached MV File records.

The caller first verifies staging SHA256 and raises the upload limit if needed.
No source URLs, audio bytes, attachment changes, cleanup, or retries occur here.
"""
import hashlib
import json
import re

from covers import _binding
from importer import Review,Stop


PREFIX='avo-mastervision-audio-stage-'
MAX_SIZE=50*1024*1024
RECEIPT_FIELDS={'basename','url_sha256','size','sha256','md5'}
FILE_FIELDS=['name','file_name','file_url','is_private','owner','file_size','content_hash',
             'attached_to_doctype','attached_to_name','attached_to_field']


def _receipt(row):
    if (not isinstance(row,dict) or set(row)!=RECEIPT_FIELDS
            or any(not isinstance(row.get(key),str) or not re.fullmatch('[0-9a-f]{'+str(length)+'}',row[key])
                   for key,length in [('url_sha256',64),('sha256',64),('md5',32)])
            or row.get('basename')!=PREFIX+row['url_sha256']+'.mp3'
            or type(row.get('size')) is not int or not 0<row['size']<=MAX_SIZE):
        raise Review('audio_stage_receipt_invalid')
    return dict(row)


def _read(client,tool,args):
    _binding(client)
    try:result=client.call(tool,args)
    except Exception:raise Stop('audio_read_failed') from None
    if not isinstance(result,dict):raise Stop('audio_read_response_invalid')
    return result


def _write(client,tool,args):
    _binding(client);data=args.get('data',{})
    if tool=='create_document':
        allowed=(set(args)=={'doctype','data'} and args['doctype']=='File'
            and isinstance(data,dict) and set(data)=={'file_name','file_url','is_private'}
            and type(data['is_private']) is int and data['is_private']==1
            and isinstance(data['file_name'],str) and re.fullmatch(r'avo-mastervision-audio-[0-9a-f]{64}\.mp3',data['file_name'])
            and isinstance(data['file_url'],str) and re.fullmatch(r'/private/files/'+PREFIX+r'[0-9a-f]{64}\.mp3',data['file_url']))
    elif tool=='update_document':
        allowed=(set(args)=={'doctype','name','data'} and args['doctype']=='System Settings'
            and args['name']=='System Settings' and isinstance(data,dict) and set(data)=={'max_file_size','modified'}
            and type(data['max_file_size']) is int and data['max_file_size']==50
            and isinstance(data['modified'],str) and bool(data['modified']))
    else:allowed=False
    if not allowed:raise Stop('audio_mutation_not_allowed')
    try:response=client.rpc('tools/call',{'name':tool,'arguments':args})
    except Exception:raise Stop('audio_write_uncertain') from None
    if not isinstance(response,dict) or response.get('isError') or not isinstance(response.get('structuredContent'),dict):
        raise Stop('audio_write_uncertain')
    return response['structuredContent']


def _files(client,filters):
    value=_read(client,'list_documents',{'doctype':'File','fields':FILE_FIELDS,'filters':filters,'limit':3})
    rows=value.get('documents')
    if not isinstance(rows,list) or value.get('has_next_page') is not False or len(rows)>1:
        raise Review('audio_file_ambiguous')
    if rows and not isinstance(rows[0],dict):raise Stop('audio_read_response_invalid')
    return rows


def _matches(doc,row,filename,url):
    return (isinstance(doc,dict) and isinstance(doc.get('name'),str) and bool(doc['name'])
            and doc.get('file_name')==filename and doc.get('file_url')==url
            and type(doc.get('is_private')) is int and doc['is_private']==1 and doc.get('owner')=='Administrator'
            and type(doc.get('file_size')) is int and doc['file_size']==row['size'] and doc.get('content_hash')==row['md5']
            and all(doc.get(key) in (None,'') for key in ('attached_to_doctype','attached_to_name','attached_to_field')))


def register_audio(client,stage_receipt,apply=False):
    """Return relative File URL/checksums/size; dry-run returns the planned mapping.

    apply=True confirms a real private File through an independent readback.
    SHA256 comes from the trusted stage receipt; File MD5 and size are checked.
    Existing foreign, attached, public, duplicate or corrupt Files are not adopted.
    """
    _binding(client)
    if type(apply) is not bool:raise Review('audio_apply_invalid')
    row=_receipt(stage_receipt);filename='avo-mastervision-audio-'+row['sha256']+'.mp3';url='/private/files/'+filename
    mapping={'file_url':url,'sha256':row['sha256'],'md5':row['md5'],'size':row['size']}
    candidates=_files(client,[['file_name','=',filename]])
    if candidates and not _matches(candidates[0],row,filename,url):raise Review('audio_existing_file_conflict')
    # Frappe deduplicates globally by MD5/private status, including unrelated
    # filenames. Do not let that silently adopt another owner or canonical URL.
    duplicates=_files(client,[['content_hash','=',row['md5']],['is_private','=',1]])
    if duplicates and (not candidates or duplicates[0].get('name')!=candidates[0]['name']):
        raise Review('audio_file_content_conflict')
    if candidates:
        if not duplicates:raise Review('audio_existing_file_conflict')
        doc=_read(client,'get_document',{'doctype':'File','name':candidates[0]['name']})
        if doc.get('doctype')!='File' or doc.get('name')!=candidates[0]['name'] or not _matches(doc,row,filename,url):
            raise Review('audio_existing_file_conflict')
        return mapping
    if not apply:return mapping
    created=_write(client,'create_document',{'doctype':'File','data':{
        'file_name':filename,'file_url':'/private/files/'+row['basename'],'is_private':1}})
    if created.get('doctype')!='File' or not _matches(created,row,filename,url):raise Stop('audio_file_readback_invalid')
    final=_read(client,'get_document',{'doctype':'File','name':created['name']})
    if final.get('doctype')!='File' or final.get('name')!=created['name'] or not _matches(final,row,filename,url):
        raise Stop('audio_file_readback_invalid')
    try:
        for filters in ([['file_name','=',filename]],[['content_hash','=',row['md5']],['is_private','=',1]]):
            rows=_files(client,filters)
            if not rows or rows[0].get('name')!=created['name']:raise Review('audio_file_ambiguous')
    except Review:raise Stop('audio_file_readback_invalid') from None
    return mapping


def _settings(client):
    doc=_read(client,'get_document',{'doctype':'System Settings','name':'System Settings'})
    if (doc.get('doctype')!='System Settings' or doc.get('name')!='System Settings'
            or not isinstance(doc.get('modified'),str) or not doc['modified']):raise Stop('audio_settings_identity_invalid')
    value=doc.get('max_file_size')
    if type(value) is not int or value<0:raise Review('audio_settings_value_invalid')
    return doc


def _protected(doc):
    def visit(value,top=False):
        if isinstance(value,dict):return {key:visit(item) for key,item in value.items()
            if key not in {'modified','modified_by'} and not (top and key=='max_file_size')}
        if isinstance(value,list):return [visit(item) for item in value]
        return value
    try:return hashlib.sha256(json.dumps(visit(doc,True),sort_keys=True,ensure_ascii=True,allow_nan=False).encode()).hexdigest()
    except (TypeError,ValueError,RecursionError):raise Stop('audio_settings_response_invalid') from None


def ensure_audio_limit(client,apply=False):
    """Raise only the raw File limit to 50 MiB; keep larger configured limits."""
    _binding(client)
    if type(apply) is not bool:raise Review('audio_apply_invalid')
    before=_settings(client);value=before['max_file_size']
    if value>=50:return {'status':'already_sufficient','max_file_size':value}
    if not apply:return {'status':'would_update','max_file_size':value,'required_max_file_size':50}
    protected=_protected(before);latest=_settings(client)
    if (latest['modified']!=before['modified'] or latest['max_file_size']!=value or _protected(latest)!=protected):
        raise Review('audio_settings_changed')
    updated=_write(client,'update_document',{'doctype':'System Settings','name':'System Settings',
        'data':{'max_file_size':50,'modified':before['modified']}})
    for doc in (updated,_settings(client)):
        if (doc.get('doctype')!='System Settings' or doc.get('name')!='System Settings'
                or type(doc.get('max_file_size')) is not int or doc['max_file_size']!=50 or _protected(doc)!=protected):
            raise Stop('audio_settings_readback_invalid')
    return {'status':'updated','max_file_size':50}
