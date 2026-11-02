"""API behaviour of the inference service, with a stub model (no download, no torch)."""
import json

import pytest
from fastapi.testclient import TestClient

import app as service


class StubParser:
    def __init__(self, reply):
        self.reply = reply

    def generate(self, text, max_new_tokens=64):
        return self.reply


VALID = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(service, 'load_model_forever', lambda: None)  # no S3 in unit tests
    monkeypatch.setitem(service.STATE, 'parser', None)
    monkeypatch.setattr(service, 'FAULT_INJECT', False)
    with TestClient(service.app) as c:
        yield c


def test_healthz_is_always_ok(client):
    assert client.get('/healthz').status_code == 200


def test_readyz_is_503_until_the_model_is_loaded(client):
    assert client.get('/readyz').status_code == 503
    assert client.post('/parse', json={'text': 'hi'}).status_code == 503
    service.STATE['parser'] = StubParser(VALID)
    assert client.get('/readyz').status_code == 200


def test_parse_returns_only_the_four_key_object_and_both_headers(client):
    service.STATE['parser'] = StubParser(VALID)
    r = client.post('/parse', json={'text': 'what is the weather in london'})
    assert r.status_code == 200
    assert r.json() == json.loads(VALID)
    assert list(r.json()) == ['intent', 'date', 'time', 'place']
    assert r.headers['X-Model-Version'] == service.MODEL_VERSION
    assert r.headers['X-Served-By'] == service.POD_NAME


@pytest.mark.parametrize('reply', [
    'not json',
    '{"intent": "weather_query", "date": null, "time": null}',
    '{"intent": "weather_query", "date": null, "time": null, "place": null, "x": 1}',
    '{"intent": "weather_report", "date": null, "time": null, "place": null}',
    '{"intent": "weather_query", "date": 5, "time": null, "place": null}',
    '{"intent": "weather_query", "date": null, "time": null, "place": "lon',
])
def test_invalid_model_output_is_a_500_with_the_exact_body(client, reply):
    service.STATE['parser'] = StubParser(reply)
    r = client.post('/parse', json={'text': 'x'})
    assert r.status_code == 500
    assert r.json() == {'error': 'invalid_model_output'}
    assert r.headers['X-Model-Version'] == service.MODEL_VERSION


def test_fault_injection_replaces_a_valid_output(client, monkeypatch):
    service.STATE['parser'] = StubParser(VALID)
    monkeypatch.setattr(service, 'FAULT_INJECT', True)
    r = client.post('/parse', json={'text': 'what is the weather in london'})
    assert r.status_code == 500
    assert r.text == '{"error":"invalid_model_output"}'


def test_request_without_text_is_rejected(client):
    service.STATE['parser'] = StubParser(VALID)
    assert client.post('/parse', json={}).status_code == 422
    assert client.post('/parse', json={'text': ''}).status_code == 422
