"""Pure MVC contact application policy; never merge source identities by email."""
from collections import Counter
import html
import re

ACCOUNT='mv-centr'
EMAIL=re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+\Z')
SOCIAL={'telegram_user_id':'custom_avo_telegram_id','telegram_user':'custom_avo_telegram_username',
        'vk_user_id':'custom_avo_vk_id','vk_user':'custom_avo_vk_username'}


class PlanError(ValueError):pass


def text(row,key):
    value=row.get(key)
    if value is None:return ''
    if not isinstance(value,str):raise PlanError('unexpected_field_type')
    return value.strip()


def bit(row,key):
    value=row.get(key)
    if value not in ('0','1') or not isinstance(value,str):raise PlanError('invalid_source_flag')
    return value=='1'


def optout(row):
    flags=(bit(row,'not_to_write'),bit(row,'spam_clicked'))
    return int(any(flags))


def email(row):return text(row,'email').lower()


def plan(row,*,existing_kind=None,excluded=False,protected=False,email_frequency=0,email_taken=False,account=ACCOUNT):
    if account not in ('mv-centr','mastervision','iomp'):raise PlanError('invalid_account')
    if excluded:return {'action':'excluded'}
    if protected:return {'action':'protected'}
    if existing_kind:
        if existing_kind not in ('User','Contact'):raise PlanError('ambiguous_source_identity')
        return {'action':'existing','optout':optout(row)}
    ident=text(row,'id_contact')
    if not re.fullmatch('[1-9][0-9]{0,18}',ident):raise PlanError('invalid_source_id')
    address=email(row)
    data={'first_name':text(row,'name'),'middle_name':text(row,'middle_name'),'last_name':text(row,'last_name'),
        'custom_avo_contact_id':ident,'custom_avo_account':account,'custom_no_marketing_email':optout(row)}
    data.update({target:text(row,source) for source,target in SOCIAL.items()})
    phone=text(row,'phone_number')
    shared_email=bool(EMAIL.fullmatch(address) and (email_frequency>1 or email_taken))
    password=row.get('password') or ''
    if not isinstance(password,str):raise PlanError('unexpected_field_type')
    if EMAIL.fullmatch(address) and password and not shared_email:
        data.update(email=address,new_password=password,mobile_no=phone)
        data['first_name']=data['first_name'] or address
        if len(password)>512:raise PlanError('password_too_long')
        if any(len(value)>140 for key,value in data.items() if isinstance(value,str) and key!='new_password'):
            raise PlanError('field_too_long')
        return {'action':'create_user','data':data,'source_banned':bit(row,'ban')}
    data['doctype']='Contact';data['custom_avo_source_email']=text(row,'email')
    if EMAIL.fullmatch(address):data['email_ids']=[{'email_id':address,'is_primary':1}]
    if phone:data['phone_nos']=[{'phone':phone,'is_primary_mobile_no':1}]
    if any(len(value)>140 for value in data.values() if isinstance(value,str)) or len(phone)>140:
        raise PlanError('field_too_long')
    return {'action':'create_contact','data':data}


def matches(saved,data):
    for key,value in data.items():
        if key in ('doctype','new_password','phone_nos','email_ids'):continue
        actual=saved.get(key)
        if key=='custom_no_marketing_email':
            if int(actual or 0)!=value:return False
        elif key in ('first_name','middle_name','last_name'):
            if html.unescape(str(actual or ''))!=html.unescape(value):return False
        elif str(actual or '')!=str(value):return False
    if data.get('doctype')=='Contact':
        expected_email=(data.get('email_ids') or [{}])[0].get('email_id','')
        if saved.get('user') or str(saved.get('email_id') or '')!=expected_email:return False
        actual_emails=[str(row.get('email_id') or '') for row in saved.get('email_ids') or []]
        if actual_emails!=([expected_email] if expected_email else []):return False
        expected=(data.get('phone_nos') or [{}])[0].get('phone','')
        if str(saved.get('mobile_no') or '')!=expected:return False
    return True
