import json
import os

import pytest

import parser_core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = parser_core.load_schema(os.path.join(ROOT, 'data', 'schema.json'))


def test_prompt_matches_the_training_layout():
    assert parser_core.build_prompt('set an alarm') + parser_core.build_target('{"a": 1}') == \
        'Command: set an alarm\nJSON: {"a": 1}'


def test_validate_accepts_a_schema_valid_object_and_orders_keys():
    obj = parser_core.validate(' {"place": null, "time": "six pm", "date": "today", "intent": "alarm_set"} ', SCHEMA)
    assert list(obj) == ['intent', 'date', 'time', 'place']


@pytest.mark.parametrize('raw', [
    '', 'not json', '[]', 'null',
    json.dumps({'intent': 'alarm_set', 'date': None, 'time': None}),
    json.dumps({'intent': 'alarm_set', 'date': None, 'time': None, 'place': None, 'extra': None}),
    json.dumps({'intent': 'unknown', 'date': None, 'time': None, 'place': None}),
    json.dumps({'intent': 'alarm_set', 'date': ['today'], 'time': None, 'place': None}),
    '{"intent": "alarm_set", "date": NaN, "time": null, "place": null}',
])
def test_validate_rejects_everything_else(raw):
    assert parser_core.validate(raw, SCHEMA) is None


def test_cpu_limit_is_a_positive_integer():
    assert parser_core.cpu_limit() >= 1
