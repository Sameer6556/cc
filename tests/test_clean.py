import json

import pytest

import clean


def rec(id_, text, reply):
    return {'id': id_, 'text': text, 'teacher_raw': reply if isinstance(reply, str) else json.dumps(reply)}


GOOD = {'intent': 'alarm_set', 'date': 'tomorrow', 'time': 'seven am', 'place': None}


def test_valid_record_is_kept_with_canonical_target():
    reply = '  {"place": null, "time": "seven am", "date": "tomorrow", "intent": "alarm_set"}\n'
    kept, counts, _ = clean.clean([rec('C1', 'wake me up tomorrow at seven am', reply)])
    assert counts['kept'] == 1
    assert kept[0]['teacher_raw'] == reply  # stored exactly as generated
    assert kept[0]['target'] == json.dumps(GOOD)  # key order intent, date, time, place


@pytest.mark.parametrize('reply, reason', [
    ('```json\n{"intent": "alarm_set", "date": null, "time": null, "place": null}\n```', 'invalid_json'),
    ('{"intent": "alarm_set", "date": null', 'invalid_json'),
    ('{"intent": "alarm_set", "date": NaN, "time": null, "place": null}', 'invalid_json'),
    ('["alarm_set"]', 'bad_keys'),
    ('{"intent": "alarm_set", "date": null, "time": null}', 'bad_keys'),
    ('{"intent": "alarm_set", "date": null, "time": null, "place": null, "person": null}', 'bad_keys'),
    ('{"intent": "alarm_set", "date": null, "time": null, "place": null, "place": null}', 'bad_keys'),
    ('{"intent": "alarm_delete", "date": null, "time": null, "place": null}', 'bad_intent'),
    ('{"intent": null, "date": null, "time": null, "place": null}', 'bad_intent'),
    ('{"intent": "alarm_set", "date": null, "time": "07:00", "place": null}', 'slot_not_in_text'),
    ('{"intent": "alarm_set", "date": "mon", "time": null, "place": null}', 'slot_not_in_text'),
    ('{"intent": "alarm_set", "date": "", "time": null, "place": null}', 'slot_not_in_text'),
    ('{"intent": "alarm_set", "date": 7, "time": null, "place": null}', 'slot_not_in_text'),
])
def test_each_rejection_reason(reply, reason):
    kept, counts, rejected = clean.clean([rec('C1', 'set an alarm for monday at seven am', reply)])
    assert kept == []
    assert counts[reason] == 1
    assert rejected == [{'id': 'C1', 'reason': reason}]


def test_slot_match_ignores_case_and_spacing_but_needs_whole_words():
    assert clean.appears_in('New  York', 'what is the weather in new york')
    assert clean.appears_in('seven am', 'wake me at seven am please')
    assert not clean.appears_in('york city', 'what is the weather in new york')
    assert not clean.appears_in('mon', 'set an alarm for monday')


def test_duplicates_keep_smallest_id_and_counts_add_up():
    records = [
        rec('C3', 'wake me up tomorrow at seven am', GOOD),
        rec('C1', 'Wake me up  tomorrow at seven am', GOOD),  # same command, smaller id
        rec('C2', 'what is the weather', '{oops'),
    ]
    kept, counts, rejected = clean.clean(records)
    assert [r['id'] for r in kept] == ['C1']
    assert counts == {'input': 3, 'invalid_json': 1, 'bad_keys': 0, 'bad_intent': 0,
                      'slot_not_in_text': 0, 'duplicate': 1, 'kept': 1}
    assert {'id': 'C3', 'reason': 'duplicate'} in rejected


def test_output_is_independent_of_input_order():
    records = [rec(f'C{i:04d}', f'set an alarm for {d}', {**GOOD, 'date': d, 'time': None})
               for i, d in enumerate(['monday', 'tuesday', 'friday'])]
    a, _, _ = clean.clean(records)
    b, _, _ = clean.clean(list(reversed(records)))
    assert a == b
    assert [r['id'] for r in a] == ['C0000', 'C0001', 'C0002']
