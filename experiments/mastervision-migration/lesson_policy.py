"""Owner-approved scoped omissions; source checkpoints remain complete."""
from importer import ACCOUNT, ORIGIN, Stop

CODE = 'owner_deferred_lesson'
DEFERRED = {317: frozenset({2314}), 607: frozenset({6577}), 624: frozenset({7050}),
            627: frozenset({7198}), 628: frozenset({7247}), 629: frozenset({7252}),
            630: frozenset({7295}), 746: frozenset({8845})}
EXCLUDED_CODE = 'owner_excluded_obsolete_lesson'
EXCLUDED = {1: frozenset({1,6}), 2: frozenset({2,5}), 17: frozenset({2558}),
            23: frozenset({30}), 207: frozenset({1976}), 259: frozenset({1536}), 273: frozenset({1735}),
            274: frozenset({1749}),
            354: frozenset({2937}), 355: frozenset({2952}), 440: frozenset({7326}), 445: frozenset({4089}),
            557: frozenset({5952}), 598: frozenset({7544}), 618: frozenset({6870})}


def deferred_ids(course_id):
    if type(course_id) is not int or course_id < 1:
        raise Stop('lesson_policy_identity_invalid')
    return DEFERRED.get(course_id, frozenset())


def excluded_ids(course_id):
    if type(course_id) is not int or course_id < 1:
        raise Stop('lesson_policy_identity_invalid')
    return EXCLUDED.get(course_id, frozenset())


def partition_payloads(payloads):
    """Keep source order and payload bytes; pending identities are separate."""
    if not isinstance(payloads, list): raise Stop('lesson_policy_identity_invalid')
    selected, pending, seen, course = [], [], set(), None
    for payload in payloads:
        if (not isinstance(payload, dict) or
                (payload.get('account'), payload.get('source_origin')) != (ACCOUNT, ORIGIN) or
                type(payload.get('course_id')) is not int or payload['course_id'] < 1 or
                type(payload.get('lesson_id')) is not int or payload['lesson_id'] < 1 or
                payload['lesson_id'] in seen or course is not None and payload['course_id'] != course):
            raise Stop('lesson_policy_identity_invalid')
        course, lid = payload['course_id'], payload['lesson_id']; seen.add(lid)
        if lid in deferred_ids(course): pending.append(lid)
        elif lid not in excluded_ids(course): selected.append(payload)
    return selected, pending
