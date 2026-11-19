"""Import the single owner-reviewed IOMP masterclass via native LMS editing tools."""
import base64
import json

from importer import Review, Stop


FRAME = ('<p><iframe src="https://abramova.iomp.ru/rasprodaza2026/" width="100%" '
         'height="3100px" frameborder="0" allowfullscreen=""></iframe></p>')


def reviewed_content(payloads):
    if len(payloads) != 1:
        raise Review('masterclass_outline_changed')
    p = payloads[0]
    if tuple(p.get(key) for key in ('account', 'source_origin', 'course_id', 'lesson_id', 'format')) != (
        'iomp', 'https://shop.iomp.ru', '347', '7128', 'ape'
    ):
        raise Review('masterclass_identity_changed')
    page = p['ape']
    nodes = page.get('children', [])
    if page.get('name') != 'page' or len(nodes) != 1:
        raise Review('masterclass_frame_changed')
    node = nodes[0]
    fields = node.get('fields', {})
    markup = fields.get('html')
    if (node.get('name') != 'code' or node.get('children') or set(fields) != {'anchor', 'html'}
            or fields['anchor'] or not isinstance(markup, str) or markup.strip() != FRAME
            or any(node.get(key) for key in node.keys() - {'name','id','style','fields','children'})
            or any(page.get(key) for key in page.keys() - {'name','id','style','fields','children'})):
        raise Review('masterclass_frame_changed')
    return {'version':'2.29.0', 'blocks':[{'type':'htmlBlock', 'data':{
        'encodedHtml':base64.b64encode(markup.encode('utf-8')).decode('ascii'), 'height':1600}}]}


def import_frame(importer, payloads, mutate, checked_course):
    importer.check_site()
    client = importer.client
    expected = reviewed_content(payloads)
    p = payloads[0]

    def find(doctype, filters):
        response = client.call('list_documents', {'doctype':doctype, 'filters':filters, 'fields':['name'], 'limit':2})
        rows = response['documents']
        if response.get('has_next_page') or len(rows) > 1:
            raise Review('masterclass_destination_conflict')
        return rows[0]['name'] if rows else None

    def get(doctype, name):
        return client.call('get_document', {'doctype':doctype, 'name':name})

    course = find('LMS Course', {'custom_lms_id':'347'})
    lesson = find('Course Lesson', {'custom_lms_id':'7128'})
    created = int(not lesson)
    if not course:
        if lesson:
            raise Review('masterclass_destination_conflict')
        title = p['course_title']
        course = mutate(client, 'create_document', {'doctype':'LMS Course', 'data':{
            'title':title, 'description':title, 'short_introduction':title, 'published':0,
            'disable_self_learning':1, 'custom_avo_account':'iomp', 'custom_avo_id':'347',
            'instructors':[{'instructor':'Administrator'}]}})['name']
    doc = checked_course(client, course, '347')
    if doc['title'] != p['course_title'] or doc.get('disable_self_learning') != 1:
        raise Review('masterclass_destination_conflict')
    if not doc.get('chapters'):
        if lesson or find('Course Chapter', {'course':course}):
            raise Review('masterclass_destination_conflict')
        mutate(client, 'call_method', {'method':'lms.lms.api.upsert_chapter', 'args':{
            'title':'Уроки курса', 'course':course, 'is_scorm_package':False}})
        doc = checked_course(client, course, '347')
    if len(doc['chapters']) != 1:
        raise Review('masterclass_destination_conflict')
    chapter = doc['chapters'][0]['chapter']
    ch = get('Course Chapter', chapter)
    if ch['course'] != course or ch.get('is_scorm_package') or ch['title'] != 'Уроки курса':
        raise Review('masterclass_destination_conflict')
    refs = [row['lesson'] for row in ch.get('lessons', [])]
    if refs and refs != [lesson]:
        raise Review('masterclass_destination_conflict')
    if not lesson:
        lesson = mutate(client, 'create_document', {'doctype':'Course Lesson', 'data':{
            'course':course, 'chapter':chapter, 'title':p['lesson_title'], 'custom_avo_account':'iomp',
            'custom_avo_id':'7128', 'is_draft':1, 'include_in_preview':0,
            'content':json.dumps(expected, ensure_ascii=False)}})['name']
    saved = get('Course Lesson', lesson)
    if (tuple(saved.get(k) for k in ('course','chapter','custom_avo_account','custom_avo_id','custom_lms_id',
            'title','is_draft','include_in_preview')) != (course,chapter,'iomp','7128','7128',p['lesson_title'],1,0)
            or json.loads(saved['content']) != expected):
        raise Review('masterclass_destination_conflict')
    if not refs:
        mutate(client, 'update_document', {'doctype':'Course Chapter','name':chapter,'data':{
            'modified':ch['modified'],'lessons':[{'lesson':lesson}]}})
    if importer.outline('347')['ids'] != ['7128']:
        raise Stop('masterclass_outline_invalid')
    return course, created
