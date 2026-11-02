"""Task 7 numbers from the measured files: latency, throughput, errors, Pod resources, cost and SLO.

Reads results/loadtest_stats.csv, results/task7/top_pods.log, results/task7/timeline.log,
results/task4/coldstart/summary.json, data/rate_card.json and the Deployment's limits
(k8s/app/parser.yaml). Writes results/task7/summary.json and prints every step of the cost.
"""
import csv
import json
import os
import re
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = lambda *a: os.path.join(ROOT, *a)  # noqa: E731
R = lambda *a: os.path.join(os.environ.get('RESULTS', os.path.join(ROOT, 'results')), *a)  # noqa: E731

SLO_TARGET = 99.0  # % of /parse requests that return HTTP 200 within 30 s, per standard load-test run


def parse_quantity_cpu(q):
    return float(q[:-1]) / 1000 if q.endswith('m') else float(q)


def parse_quantity_mem_gib(q):
    units = {'Ki': 2 ** -20, 'Mi': 2 ** -10, 'Gi': 1}
    for u, f in units.items():
        if q.endswith(u):
            return float(q[:-2]) * f
    return float(q) / 2 ** 30


def limits_from_manifest():
    text = open(P('k8s', 'app', 'parser.yaml'), encoding='utf-8').read()
    block = text.split('limits:', 1)[1]
    cpu = re.search(r'cpu:\s*"?([\dm.]+)"?', block).group(1)
    mem = re.search(r'memory:\s*"?([\dA-Za-z.]+)"?', block).group(1)
    return parse_quantity_cpu(cpu), parse_quantity_mem_gib(mem)


def main():
    rows = {r['Name']: r for r in csv.DictReader(open(R('loadtest_stats.csv')))}
    agg = rows['Aggregated']
    n, failed = int(agg['Request Count']), int(agg['Failure Count'])
    rps = float(agg['Requests/s'])
    res = {
        'requests': n, 'failures': failed, 'error_rate_pct': round(100.0 * failed / n, 3),
        'p50_ms': float(agg['50%']), 'p95_ms': float(agg['95%']), 'throughput_rps': round(rps, 3),
    }

    # kubectl top pods, sampled every 10 s during the run
    pods = {}
    for line in open(R('task7', 'top_pods.log'), encoding='utf-8'):
        m = re.match(r'(\S+)\s+(\d+)m\s+(\d+)Mi', line.strip())
        if m:
            pods.setdefault(m.group(1), []).append((int(m.group(2)), int(m.group(3))))
    res['pods'] = {p: {'samples': len(v), 'cpu_m_mean': round(statistics.mean(c for c, _ in v)),
                       'cpu_m_max': max(c for c, _ in v), 'mem_mi_mean': round(statistics.mean(m for _, m in v)),
                       'mem_mi_max': max(m for _, m in v)} for p, v in pods.items()}

    # replicas running during the run (time-weighted from the 5 s timeline)
    timeline = open(R('task7', 'timeline.log'), encoding='utf-8').read()
    counts = [int(m.group(1)) for m in re.finditer(r'deploy=\d*/(\d+)', timeline)]
    avg_replicas = statistics.mean(counts) if counts else 2
    res['replicas_mean_during_test'] = round(avg_replicas, 2)

    # cost per 1,000 requests from the rate card
    rate = json.load(open(P('data', 'rate_card.json')))
    cpu_limit, mem_limit_gib = limits_from_manifest()
    per_replica_hour = cpu_limit * rate['vcpu_hour'] + mem_limit_gib * rate['gib_memory_hour']
    steps = [f'per replica: {cpu_limit:g} vCPU x {rate["vcpu_hour"]:.2f} + {mem_limit_gib:g} GiB x '
             f'{rate["gib_memory_hour"]:.2f} = {per_replica_hour:.4f} {rate["currency"]}/hour']
    costs = {}
    for label, replicas in (('measured_mean_replicas', avg_replicas), ('two_replicas', 2.0)):
        hourly = replicas * per_replica_hour
        per_hour = rps * 3600
        c = hourly / per_hour * 1000
        costs[label] = {'replicas': round(replicas, 3), 'hourly_cost': round(hourly, 4),
                        'requests_per_hour': round(per_hour, 1), 'cost_per_1000': round(c, 4)}
        steps.append(f'{label}: {replicas:.2f} replicas x {per_replica_hour:.4f} = {hourly:.4f} '
                     f'{rate["currency"]}/hour; '
                     f'{rps:.3f} req/s x 3600 = {per_hour:.1f} req/hour; '
                     f'{hourly:.4f} / {per_hour:.1f} x 1000 = {c:.4f} {rate["currency"]} per 1,000 requests')
    res['cost'] = {'currency': rate['currency'], 'per_replica_hour': round(per_replica_hour, 4), **costs,
                   'steps': steps}

    # SLO: 99 % of requests succeed in one standard run
    budget = n * (100 - SLO_TARGET) / 100
    res['slo'] = {'objective': f'{SLO_TARGET:g}% of /parse requests return HTTP 200 within 30 s',
                  'window': 'one standard load-test run (4 users, 2 minutes)',
                  'error_budget_requests': round(budget, 2), 'failed_requests': failed,
                  'budget_used_pct': round(100.0 * failed / budget, 1) if budget else None,
                  'met': 100.0 * (n - failed) / n >= SLO_TARGET}

    try:
        cold = json.load(open(R('task4', 'coldstart', 'summary.json')))
        res['cold_start_median_s'] = cold['median_cold_start_s']
    except FileNotFoundError:
        res['cold_start_median_s'] = None

    json.dump(res, open(R('task7', 'summary.json'), 'w'), indent=2)
    print(json.dumps({k: v for k, v in res.items() if k != 'cost'}, indent=2))
    print('\n'.join(steps))


if __name__ == '__main__':
    main()
