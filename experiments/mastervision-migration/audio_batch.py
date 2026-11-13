"""Register a completely staged, source-bound MP3 batch and checkpoint metadata."""
from pathlib import Path

from audio_files import ensure_audio_limit,register_audio
from audio_stage_client import _plan,_index,_json,_save_index
from covers import _binding
from importer import ACCOUNT,ORIGIN,SITE,Stop


def _mapping_matches(value,receipt):
    expected={'file_url':'/private/files/avo-mastervision-audio-'+receipt['sha256']+'.mp3',
              'sha256':receipt['sha256'],'md5':receipt['md5'],'size':receipt['size']}
    return isinstance(value,dict) and set(value)==set(expected) and type(value.get('size')) is int and value==expected


def _registered(path,receipts):
    if not path.exists() and not path.is_symlink():
        return {'version':1,'account':ACCOUNT,'origin':ORIGIN,'site':SITE,'files':{}}
    value=_json(path)
    if (set(value)!={'version','account','origin','site','files'} or type(value['version']) is not int
            or value['version']!=1 or (value['account'],value['origin'],value['site'])!=(ACCOUNT,ORIGIN,SITE)
            or not isinstance(value['files'],dict) or set(value['files'])-set(receipts)):
        raise Stop('audio_registration_index_invalid')
    if any(not _mapping_matches(row,receipts[key]) for key,row in value['files'].items()):
        raise Stop('audio_registration_index_invalid')
    return value


def register_staged_audio(store,client,emit,apply=True):
    """Revalidate every File, persisting only confirmed mappings after each entry.

    The stage index must be complete before any MCP call. A dry run returns
    planned mappings without writing checkpoints or emitting verified progress.
    The caller holds the Store worker lock; no source capture or ledger is changed.
    """
    _binding(client)
    if type(apply) is not bool or not callable(emit):raise Stop('audio_registration_input_invalid')
    records=_plan(store)
    staged=_index(Path(store.directory)/'audio-stage-index.json',records)
    receipts=staged['files']
    if set(receipts)!=set(records):raise Stop('audio_staging_incomplete')
    path=Path(store.directory)/'audio-files-index.json'
    index=_registered(path,receipts);result={};total=len(records)
    def progress(completed):
        try:emit({'stage':'audio_register','completed':completed,'total':total})
        except Exception:raise Stop('audio_registration_progress_failed') from None
    if apply:progress(0)
    ensure_audio_limit(client,apply=apply)
    for key in records:
        mapping=register_audio(client,receipts[key],apply=apply)
        if not _mapping_matches(mapping,receipts[key]):raise Stop('audio_registration_mapping_invalid')
        result[key]=dict(mapping)
        if apply:
            if index['files'].get(key)!=mapping:
                index['files'][key]=dict(mapping)
                _save_index(path,index)
            progress(len(result))
    return result
