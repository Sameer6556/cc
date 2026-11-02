import json

import pytest

import teacher
import worker


def lines(n):
    return [json.dumps({'id': f'C{i:04d}', 'text': f'command {i}'}) for i in range(n)]


@pytest.mark.parametrize('count', [1, 2, 3, 4])
def test_shards_partition_the_input_without_gaps_or_repeats(count):
    data = lines(11)
    owned = [worker.shard_of(data, i, count) for i in range(count)]
    numbers = sorted(n for shard in owned for n, _ in shard)
    assert numbers == list(range(11))
    for i, shard in enumerate(owned):
        assert all(n % count == i for n, _ in shard)


def test_blank_lines_keep_their_line_numbers():
    data = lines(3)
    data.insert(1, '')
    assert [n for n, _ in worker.shard_of(data, 0, 2)] == [0, 2]
    assert [r['id'] for _, r in worker.shard_of(data, 1, 2)] == ['C0002']


@pytest.mark.parametrize('index, count', [(2, 2), (-1, 2), (0, 0)])
def test_invalid_shard_settings_are_rejected(index, count):
    with pytest.raises(ValueError):
        worker.shard_of(lines(4), index, count)


def test_prompt_and_fixed_decoding_settings():
    template = teacher.load_prompt(teacher.__file__.replace('worker/teacher.py', 'prompts/teacher_prompt.txt'))
    prompt = teacher.build_prompt(template, 'what is the weather in paris')
    assert prompt.rstrip().endswith('Command: what is the weather in paris\nJSON:')
    assert '{command}' not in prompt
    opts = teacher.options(128, 2048)
    assert opts['temperature'] == 0 and opts['seed'] == 42


def test_resume_keeps_complete_lines_and_drops_a_torn_one(tmp_path):
    path = tmp_path / 'shard-0.jsonl'
    good = json.dumps({'id': 'C0001', 'text': 'a', 'teacher_raw': '{}'})
    path.write_text(good + '\n' + '{"id": "C0003", "te')
    kept, done = worker.load_done(str(path))
    assert kept == [good]
    assert done == {'C0001'}
