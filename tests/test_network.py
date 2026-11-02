"""Task 5: the subnet table and the NACL."""
import ipaddress
import json
import os
import re

import nacl_sim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = {'app': 1000, 'public': 250, 'data': 100, 'management': 20}


def subnet_rows():
    text = open(os.path.join(ROOT, 'network', 'subnets.md'), encoding='utf-8').read()
    section = text.split('## Result', 1)[1]
    rows = {}
    for m in re.finditer(r'^\| (\w+) \| ([\d.]+) \| /(\d+) \| ([\d.]+) to ([\d.]+) \| ([\d.]+) \| ([\d,]+) \|$',
                         section, re.M):
        rows[m.group(1)] = m.groups()[1:]
    return rows


def test_subnet_table_is_correct_and_minimal():
    rows = subnet_rows()
    assert list(rows) == ['app', 'public', 'data', 'management']  # largest first
    cursor = ipaddress.ip_address('10.20.0.0')
    for name, (net, prefix, first, last, bcast, usable) in rows.items():
        n = ipaddress.ip_network(f'{net}/{prefix}')
        assert n.network_address == cursor  # placed right after the previous one
        assert n.subnet_of(ipaddress.ip_network('10.20.0.0/16'))
        hosts = 2 ** (32 - n.prefixlen) - 2
        assert int(usable.replace(',', '')) == hosts >= REQUIRED[name]
        assert 2 ** (32 - n.prefixlen - 1) - 2 < REQUIRED[name]  # one bit smaller would not fit
        assert (first, last, bcast) == (str(n.network_address + 1), str(n.broadcast_address - 1),
                                        str(n.broadcast_address))
        cursor = n.broadcast_address + 1


def decide_all(packets_file):
    rules = nacl_sim.load_rules(os.path.join(ROOT, 'network', 'nacl.json'))
    out = []
    for line in open(os.path.join(ROOT, 'network', packets_file), encoding='utf-8'):
        if line.strip():
            p = json.loads(line)
            out.append((p['id'], nacl_sim.decide(rules, p)[0], p['expected']))
    return out


def test_nacl_decides_every_sample_packet_correctly():
    assert all(got == want for _, got, want in decide_all('packets_sample.jsonl'))


def test_nacl_edge_cases():
    wrong = [(i, got, want) for i, got, want in decide_all('packets_extra.jsonl') if got != want]
    assert wrong == []


def test_abusive_range_deny_comes_before_every_allow():
    rules = json.load(open(os.path.join(ROOT, 'network', 'nacl.json'), encoding='utf-8'))['inbound']
    deny = next(r for r in rules if r['cidr'] == '198.51.100.0/24')
    assert deny['action'] == 'deny' and deny['protocol'] == 'all'
    assert all(deny['rule'] < r['rule'] for r in rules if r['action'] == 'allow')
