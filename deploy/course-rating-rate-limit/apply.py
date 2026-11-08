from pathlib import Path

path = Path('/home/frappe/frappe-bench/apps/lms/lms/lms/utils.py')
source = path.read_text(encoding='utf-8')
old = 'ratings = [review.rating for review in get_reviews(course)]'
new = 'ratings = [review.rating for review in _get_reviews(course)]'
entry = 'def get_reviews(course: str):\n\treviews = frappe.get_all('
replacement = 'def get_reviews(course: str):\n\treturn _get_reviews(course)\n\n\ndef _get_reviews(course: str):\n\treviews = frappe.get_all('
if source.count(old) != 1 or source.count(entry) != 1:
	raise SystemExit('Unexpected source; refusing to modify it')
path.write_text(source.replace(old, new).replace(entry, replacement), encoding='utf-8')
