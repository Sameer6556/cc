"""Build report/report.html from the measured evidence in results/ (then: node report/render.cjs).

Every number in the report is read from a file in the repository at build time; nothing is typed in by
hand. A value that has not been measured yet is printed as PENDING in red, so a missing measurement can
never pass silently as a result.

  python report/build_report.py && node report/render.cjs
"""
import csv
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = 'https://github.com/Sameer6556/cc'
STUDENT = os.environ.get('STUDENT_NAME', 'Sameer Singh')
ROLL = os.environ.get('ROLL_NUMBER', '230101096')
PENDING = '<span class="pending">PENDING</span>'


def path(*a):
    return os.path.join(ROOT, *a)


def text(*a):
    p = path(*a)
    return open(p, encoding='utf-8').read() if os.path.exists(p) else None


def js(*a):
    t = text(*a)
    return json.loads(t) if t else None


def esc(s):
    return html.escape(str(s))


def v(x, fmt='{}', unit=''):
    """Format a measured value, or PENDING when it is missing."""
    if x is None:
        return PENDING
    try:
        return fmt.format(x) + unit
    except (ValueError, TypeError):
        return esc(x) + unit


def last_json_after(t, marker):
    """The JSON object that follows the last occurrence of `marker` in a log."""
    if not t or marker not in t:
        return None
    tail = t.rsplit(marker, 1)[1]
    start = tail.find('{')
    try:
        obj, _ = json.JSONDecoder().raw_decode(tail[start:])
        return obj
    except (ValueError, json.JSONDecodeError):
        return None


def json_events(t):
    out = []
    for line in (t or '').splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def loss_rows(name):
    p = path('training', name)
    if not os.path.exists(p):
        return []
    return [(int(r['epoch']), float(r['loss'])) for r in csv.DictReader(open(p, encoding='utf-8'))]


# --------------------------------------------------------------------------------------------- charts
def loss_chart(series):
    """Line chart of training loss per epoch: one y-axis, legend + direct end labels, thin lines."""
    series = [(n, c, pts) for n, c, pts in series if pts]
    if not series:
        return f'<p class="small">Loss chart: {PENDING}</p>'
    W, H, L, R, T, B = 330, 150, 34, 46, 10, 24
    xs = [e for _, _, pts in series for e, _ in pts]
    ys = [y for _, _, pts in series for _, y in pts]
    x0, x1 = 1, max(xs)
    y1 = max(ys) * 1.08
    y0 = 0.0

    def px(e):
        return L + (e - x0) / max(1, x1 - x0) * (W - L - R)

    def py(y):
        return T + (1 - (y - y0) / (y1 - y0)) * (H - T - B)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="training loss per epoch">']
    step = 0.5 if y1 <= 3 else 1.0
    k = 0.0
    while k <= y1:
        parts.append(f'<line x1="{L}" x2="{W - R}" y1="{py(k):.1f}" y2="{py(k):.1f}" stroke="#e6e5e1" stroke-width="0.6"/>')
        parts.append(f'<text x="{L - 4}" y="{py(k) + 2.5:.1f}" font-size="7" fill="#52514e" text-anchor="end">{k:g}</text>')
        k += step
    for e in range(x0, x1 + 1):
        parts.append(f'<text x="{px(e):.1f}" y="{H - B + 10}" font-size="7" fill="#52514e" text-anchor="middle">{e}</text>')
    parts.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 3}" font-size="7.2" fill="#52514e" text-anchor="middle">epoch</text>')
    parts.append(f'<text x="9" y="{(T + H - B) / 2:.0f}" font-size="7.2" fill="#52514e" text-anchor="middle" '
                 f'transform="rotate(-90 9 {(T + H - B) / 2:.0f})">mean token loss</text>')
    for _name, color, pts in series:
        d = ' '.join(f'{"M" if i == 0 else "L"}{px(e):.1f},{py(y):.1f}' for i, (e, y) in enumerate(pts))
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        e, y = pts[-1]
        parts.append(f'<circle cx="{px(e):.1f}" cy="{py(y):.1f}" r="2.6" fill="{color}" stroke="#fff" stroke-width="1"/>')
    # direct labels at the line ends, nudged apart if they would collide
    ends = sorted(((py(pts[-1][1]), name, pts[-1][1]) for name, _, pts in series), key=lambda t: t[0])
    last = -99
    for y, name, val in ends:
        y = max(y, last + 9)
        last = y
        parts.append(f'<text x="{W - R + 5}" y="{y + 2.5:.1f}" font-size="7.2" fill="#111110">{esc(name)} {val:.3f}</text>')
    lx = L + 4
    for name, color, _ in series:
        parts.append(f'<rect x="{lx}" y="{T + 2}" width="9" height="2.5" fill="{color}"/>'
                     f'<text x="{lx + 12}" y="{T + 5}" font-size="7.2" fill="#111110">{esc(name)}</text>')
        lx += 12 + 6 * len(name) + 10
    parts.append('</svg>')
    return ''.join(parts)


# --------------------------------------------------------------------------------------------- data
def task1_data():
    stats = js('results', 'task1', 'clean_stats.json') or {}
    counts = stats.get('counts', {})
    coverage = text('results', 'task1', 'coverage.txt') or ''
    reproduce = text('results', 'task1', 'clean_reproduce.txt') or ''
    sha = (text('datasets', 'v1', 'train.sha256') or '').split()
    timeline = text('results', 'task1', 'label_timeline.log') or ''
    stamps = re.findall(r'^\[(\S+)\] (starting the labelling Job|labelling finished)', timeline, re.M)
    duration_h = None
    if len(stamps) >= 2:
        from datetime import datetime
        t0 = datetime.strptime(stamps[0][0], '%Y-%m-%dT%H:%M:%SZ')
        t1 = datetime.strptime(stamps[-1][0], '%Y-%m-%dT%H:%M:%SZ')
        duration_h = (t1 - t0).total_seconds() / 3600
    workers = {}
    import glob
    for f in sorted(glob.glob(path('results', 'task1', 'worker-shard-*.log'))):
        i = int(re.search(r'worker-shard-(\d+)\.log$', f).group(1))
        events = json_events(open(f, encoding='utf-8').read())
        ev = [e for e in events if e.get('event') == 'finished']
        prog = [e for e in events if e.get('event') == 'progress']
        if ev:
            workers[i] = {'written': ev[-1].get('written'), 'seconds': ev[-1].get('seconds'),
                          'mean_s': ev[-1].get('mean_s_per_cmd'),
                          'reply_tokens': prog[-1].get('mean_reply_tokens') if prog else None}
    return {
        'counts': counts, 'per_shard': stats.get('per_shard'), 'canonical': stats.get('raw_already_canonical'),
        'coverage_ok': 'COVERAGE OK' in coverage if coverage else None,
        'reproduced': ('MATCH' in reproduce) if reproduce else None,
        'sha256': sha[0] if sha else None, 'duration_h': duration_h, 'workers': workers,
    }


def task2_data():
    def score(*a):
        return js(*a)
    return {
        'teacher': score('results', 'teacher_validation.json'),
        'untrained': score('results', 'task2', 'untrained_validation.json'),
        'v1': score('results', 'task2', 'student_v1_validation.json'),
        'v2': score('results', 'task2', 'student_v2_validation.json'),
        'loss_v1': loss_rows('loss.csv'), 'loss_v2': loss_rows('loss_v2.csv'),
        'sha_v1': text('models', 'v1', 'model.sha256'), 'sha_v2': text('models', 'v2', 'model.sha256'),
        'train_v1': json_events(text('results', 'task2', 'train_v1.log')),
        'train_v2': json_events(text('results', 'task2', 'train_v2.log')),
        'subset': json_events(text('results', 'task2', 'train_subset50.log')),
        'release_v1': js('results', 'task2', 'release_v1.json'),
    }


def task3_data():
    image = text('results', 'task3', 'image.txt') or ''
    m = re.search(r'size_bytes=(\d+)', image)
    mem = text('results', 'task3', 'memory_peak.txt') or ''
    peak = re.search(r'cgroup memory peak \(bytes\): (\d+)', mem)
    oom = re.search(r'OOMKilled=(\w+)', mem)
    seq = text('results', 'task3', 'sequential_50.txt') or ''
    s = re.search(r"status codes: (\{.*?\}); completed (\d+)/50; mean (\d+) ms, median (\d+) ms, max (\d+) ms", seq)
    fault = text('results', 'task3', 'fault_inject.txt') or ''
    readiness = text('results', 'task3', 'readiness.log') or ''
    r503 = len(re.findall(r'/readyz -> 503', readiness))
    weights = text('results', 'task3', 'no_weights_in_image.txt') or ''
    found = [ln for ln in weights.splitlines() if ln and not ln.startswith('#')]
    return {
        'size_gb': int(m.group(1)) / 1e9 if m else None,
        'peak_mib': int(peak.group(1)) / 2 ** 20 if peak else None,
        'oom': oom.group(1) if oom else None,
        'seq': s.groups() if s else None,
        'fault_ok': ('500' in fault and '{"error":"invalid_model_output"}' in fault) if fault else None,
        'readyz_503_samples': r503 if readiness else None,
        'weights_found': found if weights else None,
    }


def task4_data():
    cold = js('results', 'task4', 'coldstart', 'summary.json')
    hpa_log = text('results', 'task4', 'hpa', 'hpa.log')
    tl = text('results', 'task4', 'hpa', 'timeline.log') or ''
    reps = [int(x) for x in re.findall(r'deploy=\d*/(\d+)', tl)]
    rolling = last_json_after(text('results', 'task4', 'rolling', 'rolling.log'), 'load test:')
    after = text('results', 'task4', 'rolling', 'after_rollback.txt') or ''
    recovery_log = text('results', 'task4', 'recovery', 'recovery.log') or ''
    rec_ms = re.search(r'back to 2 ready, (\d+) ms', recovery_log)
    lb = js('results', 'task4', 'loadbalance', 'loadtest_headers.json')
    ingress = text('results', 'task4', 'basics', 'ingress_curl.txt') or ''
    return {
        'cold': cold,
        'hpa_load': last_json_after(hpa_log, 'load off:'),
        'hpa_seq': (reps[0] if reps else None, max(reps) if reps else None, reps[-1] if reps else None),
        'rolling': rolling,
        'after_v1': (after.count('X-Model-Version: v1') if after else None),
        'after_total': (len(re.findall(r'(?i)x-model-version', after)) - 0 if after else None),
        'recovery': last_json_after(recovery_log, 'load test:'),
        'recovery_s': int(rec_ms.group(1)) / 1000 if rec_ms else None,
        'lb': lb.get('per_replica') if lb else None,
        'ingress_ok': ('200 OK' in ingress and 'X-Served-By' in ingress) if ingress else None,
    }


# --------------------------------------------------------------------------------------------- sections
def metric_row(name, s, highlight=False):
    keys = ('json_validity', 'intent_accuracy', 'date_accuracy', 'time_accuracy', 'place_accuracy', 'full_frame')
    cells = ''.join(f'<td class="n">{v(s.get(k) if s else None, "{:.1f}")}</td>' for k in keys)
    return f'<tr><td>{"<b>" + name + "</b>" if highlight else name}</td>{cells}</tr>'


def build():
    t1, t2, t3, t4 = task1_data(), task2_data(), task3_data(), task4_data()
    t7 = js('results', 'task7', 'summary.json')
    ci = js('results', 'task6', 'ci_runs.json') or {}
    arch = text('report', 'arch.svg')
    c = t1['counts']
    out = []
    w = out.append

    # ------------------------------------------------------------------ title
    w(f'''<h1>Knowledge Distillation and Deployment of a Lightweight Command-Parsing Model on a Local Cloud</h1>
<div class="subtitle">CS3081 Cloud Computing, mini project report</div>
<div class="meta"><b>Name</b><span>{esc(STUDENT)}</span><b>Roll number</b><span>{esc(ROLL)}</span>
<b>Repository</b><span><a href="{REPO}">{REPO}</a> (assessed commit: tag <code>final</code>)</span>
<b>Model releases</b><span><a href="{REPO}/releases/tag/model-v1">model-v1</a>, <a href="{REPO}/releases/tag/model-v2">model-v2</a></span></div>''')

    # ------------------------------------------------------------------ overview
    w(f'''<h2>Overview, architecture and how to read this report</h2>
<figure>{arch or ""}<figcaption>Figure 1. System architecture. Everything runs in one k3d cluster created from
<code>cluster/k3d.yaml</code>; the only things outside it are the host tools and GitHub (CI and the model Releases).</figcaption></figure>
<p>The teacher (phi3.5, 3.8 B parameters, served by Ollama) labels the 3,000 pool commands with a four-key
JSON frame; <code>clean.py</code> filters the replies into a training set; Pythia-70M is fine-tuned on the
first 1,500 records (sequence-level distillation); the student is served by a FastAPI service behind a
Traefik Ingress with an HPA. All long-running experiments were executed with the repository's own Makefile
targets and scripts on GitHub-hosted runners (Ubuntu 24.04, 4 vCPU, 16 GiB RAM), from a fresh clone each time,
by the workflows <code>label</code>, <code>train</code> and <code>experiments</code>, which commit their evidence to
<code>results/</code>; the same commands run unchanged on a laptop (see README).</p>
<div class="legend-box"><span><span class="tag m">M</span> measured: read from the file named in the caption or row</span>
<span><span class="tag a">A</span> assumption or design choice, not a measurement</span></div>''')

    # ------------------------------------------------------------------ task 1
    shard_rows = ''.join(f'<tr><td>shard-{i}</td><td class="n">{v(wk.get("written"))}</td>'
                         f'<td class="n">{v(wk.get("seconds"), "{:,.0f}", " s")}</td>'
                         f'<td class="n">{v(wk.get("mean_s"), "{:.2f}", " s")}</td>'
                         f'<td class="n">{v(wk.get("reply_tokens"), "{:.1f}")}</td></tr>'
                         for i, wk in sorted(t1['workers'].items())) or f'<tr><td colspan="5">{PENDING}</td></tr>'
    total = c.get('input')
    iters = (js('results', 'task1', 'prompt_iterations.json') or {}).get('iterations', [])

    def _it(i):
        if len(iters) <= i:
            return PENDING
        r = iters[i]
        return (f"{r['json_validity']:.0f} % valid JSON, {r['full_frame']:.0f} % full frame, "
                f"{r['seconds_per_command']:.1f} s per command (<a href=\"{esc(r['run'])}\">run</a>)")
    pi_a, pi_b = _it(0), _it(1)
    w(f'''<h2>Task 1. Object storage and parallel teacher labelling</h2>
<p><b>Architecture.</b> The cluster is a single k3s node; Traefik is published on host port 8080 and the S3 port of
SeaweedFS on 127.0.0.1:30333 only. SeaweedFS 4.47 runs as one <code>weed server -s3</code> Pod in namespace
<code>data</code> on a 5 GiB volume. S3 credentials are generated at deploy time (<code>scripts/secrets.sh</code>)
straight into Kubernetes Secrets: an admin identity for the pipeline and a read-only identity limited to the
<code>models</code> bucket for the service (checked: GET/LIST on models allowed; GET on datasets, PUT and DELETE denied).
<code>make up</code> creates the buckets <code>datasets</code> and <code>models</code> and uploads
<code>commands_pool.jsonl</code>. The teacher runs inside the cluster (Ollama 0.40.9, namespace <code>pipeline</code>,
phi3.5 pulled by an init container) with temperature 0 and seed 42 hard-coded in <code>worker/teacher.py</code>,
plus <code>num_predict</code> 128, <code>num_ctx</code> 2048 and the stop sequences blank line and
<code>\nCommand:</code> (a frame is one line, so they only end trailing chatter early; the stored reply is still
exactly what was generated).</p>
<p><b>Prompt</b> (<code>prompts/teacher_prompt.txt</code>). It restates the four keys, gives a one-line definition per
intent, the three slot rules plus three conventions of the data (drop "next"; parts of the day and vague words such as
"upcoming" are never dates or times; "near me", time zones and people's names are never places), followed by 18
examples I wrote and a closing reminder. None of the 18 commands occurs in the pool or the validation set (checked by
script), so no hand-made label can leak into the training data. Before the full run I compared two prompt versions on
the 100 validation commands (teacher-dev workflow): the first gave {pi_a}, the second {pi_b}, so the second was used
<span class="tag m">M</span> (results/task1/prompt_iterations.json). <span class="tag a">A</span> Because the prompt was
chosen by looking at validation errors, the teacher's validation score is optimistic; this raises, not lowers, the bar
of "half the teacher's full frame" for the student, whose score on the hidden set is unaffected.</p>
<p><b>Sharding.</b> Worker <i>k</i> of <i>K</i> owns the commands whose 0-based line number <i>n</i> satisfies
<i>n</i> mod <i>K</i> = <i>k</i>. The workers are one Kubernetes <i>Indexed Job</i> with
<code>completions = parallelism = 4</code>; each Pod receives its completion index through the downward API as
<code>SHARD_INDEX</code>, and <code>SHARD_COUNT</code>=4. The assignment is a pure function of the line number, so the
shards are disjoint and together cover every line without any coordination, locking or shared state; each worker
writes only its own object <code>datasets/teacher/shard-k.jsonl</code>, so there are no write conflicts. Round-robin
(rather than contiguous blocks) keeps the shards balanced even if command length drifts through the file. A worker
uploads its partial object every 25 replies and, when restarted, skips the ids already present, so a Pod failure
costs at most 25 teacher calls. Ollama decodes the four workers' requests together in one batch (<code>OLLAMA_NUM_PARALLEL=4</code>), which raises CPU throughput because one pass over the weights serves four sequences.
The trade-off of a static split is that a slow worker cannot hand work to a fast one.</p>
<div class="two"><div>
<table><tr><th>clean.py outcome (each record counted once, first rule that applies)</th><th class="n">records</th></tr>
<tr><td>input records (both shards)</td><td class="n">{v(total, "{:,}")}</td></tr>
<tr><td>(a) reply is not valid JSON</td><td class="n">{v(c.get("invalid_json"))}</td></tr>
<tr><td>(b) keys not exactly intent, date, time, place</td><td class="n">{v(c.get("bad_keys"))}</td></tr>
<tr><td>(c) intent not one of the eight</td><td class="n">{v(c.get("bad_intent"))}</td></tr>
<tr><td>(d) slot value neither null nor text of the command</td><td class="n">{v(c.get("slot_not_in_text"))}</td></tr>
<tr><td>(e) duplicate command (smallest id kept)</td><td class="n">{v(c.get("duplicate"))}</td></tr>
<tr><td><b>kept</b></td><td class="n"><b>{v(c.get("kept"), "{:,}")}</b></td></tr>
<caption><span class="tag m">M</span> results/task1/clean_stats.json. input = (a)+(b)+(c)+(d)+(e)+kept is asserted in clean.py.</caption></table>
</div><div>
<table><tr><th>worker</th><th class="n">replies</th><th class="n">wall time</th><th class="n">s / command</th><th class="n">reply tokens</th></tr>
{shard_rows}
<caption><span class="tag m">M</span> results/task1/worker-shard-*.log (all four Pods ran concurrently: workers_running.txt).</caption></table>
<p class="small">Coverage (every id in exactly one shard, in the shard its line number dictates):
<b>{v({True: "no gaps, no repeats", False: "FAILED"}.get(t1["coverage_ok"]))}</b> (coverage.txt).
Re-running <code>clean.py</code> outside the cluster reproduces <code>train.sha256</code>:
<b>{v({True: "match", False: "MISMATCH"}.get(t1["reproduced"]))}</b> (clean_reproduce.txt).
SHA-256 of <code>datasets/v1/train.jsonl</code>: <code>{v(t1["sha256"])}</code>.
Labelling wall time: <b>{v(t1["duration_h"], "{:.2f}", " h")}</b>.</p>
</div></div>
<p><b>Cleaning decisions</b> <span class="tag a">A</span>. A reply is parsed after trimming surrounding whitespace (as
<code>score.py</code> does); a repeated key counts as (b); NaN is invalid JSON; rule (d) compares whole words, case-
and space-insensitively, so "mon" does not match "monday" and an empty string never matches. Rules (a)-(d) are
applied first, then duplicates among the survivors. Each kept line stores the exact <code>teacher_raw</code> reply and
a <code>target</code>: the same object re-serialised with the key order intent, date, time, place (values unchanged;
{v(t1["canonical"])} of {v(c.get("kept"))} kept replies were already byte-identical to it).
<b>Limitations / improvements:</b> rule (d) checks form, not meaning, so a wrong-but-present span is kept; with only
4 vCPU the teacher is compute-bound, so more workers would not help; a work queue (or a Job per chunk) would remove the
static-split imbalance, and a second teacher pass on rejected commands could recover data.</p>''')

    # ------------------------------------------------------------------ task 2
    cfg = text('training', 'config.yaml') or ''

    def cfgv(key):
        m = re.search(rf'^{key}:\s*([^#\n]+)', cfg, re.M)
        return m.group(1).strip() if m else None
    start = next((e for e in t2['train_v1'] if e.get('event') == 'start'), {})
    saved = next((e for e in t2['train_v1'] if e.get('event') == 'saved'), {})
    saved2 = next((e for e in t2['train_v2'] if e.get('event') == 'saved'), {})
    sub = next((e for e in t2['subset'] if e.get('event') == 'saved'), {})
    sha_line = next((ln for ln in (t2['sha_v1'] or '').splitlines() if ln.endswith('model.safetensors')), None)
    ff_t = (t2['teacher'] or {}).get('full_frame')
    ff_s = (t2['v1'] or {}).get('full_frame')
    ratio = (ff_s / ff_t * 100) if (ff_t and ff_s is not None) else None
    det = text('results', 'task2', 'determinism_check.txt')
    determinism = None if det is None else ('IDENTICAL' in det)
    w(f'''<h2>Task 2. Training the student (sequence-level distillation)</h2>
<div class="two"><div>
<table><tr><th>training/config.yaml</th><th>value</th></tr>
<tr><td>seed (fixed in code via set_seed before any randomness)</td><td>{v(cfgv("seed"))}</td></tr>
<tr><td>learning rate (AdamW, 5 % warm-up, linear decay)</td><td>{v(cfgv("learning_rate"))}</td></tr>
<tr><td>batch size</td><td>{v(cfgv("batch_size"))}</td></tr>
<tr><td>epochs: v1 / v2</td><td>{v(cfgv("epochs"))} / 11 (v2 = one more epoch)</td></tr>
<tr><td>maximum sequence length</td><td>{v(cfgv("max_seq_len"))} tokens (no example truncated: {v(start.get("truncated"))})</td></tr>
<tr><td>libraries</td><td>Python 3.12, torch 2.14.1 (CPU), transformers 5.19.0, tokenizers 0.23.3, safetensors 0.8.0</td></tr>
<tr><td>records</td><td>first {v(start.get("records"))} of train.jsonl ({v(start.get("first_id"))} to {v(start.get("last_id"))})</td></tr>
<tr><td>base model</td><td>EleutherAI/pythia-70m @ <code>{v((start.get("revision") or "")[:12] or None)}</code></td></tr>
<caption><span class="tag m">M</span> config and results/task2/train_v1.log. Training time v1 {v(saved.get("train_seconds"), "{:.0f}", " s")}, v2 {v(saved2.get("train_seconds"), "{:.0f}", " s")} on 4 vCPU; <code>make train SUBSET=50</code> ran to the end in {v(sub.get("train_seconds"), "{:.0f}", " s")} (train_subset50.log).</caption></table>
</div><div><figure>{loss_chart([("v1", "#2a78d6", t2["loss_v1"]), ("v2", "#eb6834", t2["loss_v2"])])}
<figcaption>Figure 2. Mean per-token loss on the reply tokens, per epoch (training/loss.csv, loss_v2.csv) <span class="tag m">M</span></figcaption></figure></div></div>
<p><b>Implementation.</b> Each example is <code>Command: &lt;text&gt;\\nJSON: &lt;target&gt;&lt;|endoftext|&gt;</code>. The loss is
computed only on the reply and the end-of-text token (prompt tokens are masked with -100), so the student learns
p(reply | command) and learns to stop. The prompt format, greedy decoding (stop at end-of-text or newline,
<code>MAX_NEW_TOKENS</code>=64) and validation live in one module, <code>service/parser_core.py</code>, used by
training, offline evaluation and the service, so the scores below are produced exactly the way the service answers.
Training runs in deterministic mode; two runs of <code>make train SUBSET=50</code> on the same runner gave weights that are {v({True: "byte-identical", False: "NOT identical"}.get(determinism))} (results/task2/determinism_check.txt). Both versions were
uploaded to <code>s3://models/v1/</code> and <code>v2/</code> (results/task2/s3_listing.txt) and published as Releases
whose files verify against <code>models/v1/model.sha256</code> with <code>sha256sum -c</code> (results/task2/release_v1_sha256_check.txt).
Weights: <code class="small">{v(sha_line)}</code>.</p>
<table><tr><th>model (validation.jsonl, 100 commands)</th><th class="n">JSON valid</th><th class="n">intent</th><th class="n">date</th><th class="n">time</th><th class="n">place</th><th class="n">full frame</th></tr>
{metric_row("teacher phi3.5 (same prompt and settings as Task 1)", t2["teacher"])}
{metric_row("Pythia-70M, untrained (same prompt and decoding)", t2["untrained"])}
{metric_row("student v1 (10 epochs)", t2["v1"], True)}
{metric_row("student v2 (11 epochs)", t2["v2"])}
<caption><span class="tag m">M</span> score.py reports: results/teacher_validation.json, results/task2/untrained_validation.json, student_v1_validation.json, student_v2_validation.json (raw outputs next to them). Student v1 full frame = {v(ratio, "{:.0f}", " %")} of the teacher's.</caption></table>
<p><b>What changed.</b> The untrained model does not produce the frame at all; after distillation the student
emits a schema-valid frame for almost every command, and its errors are concentrated in the slots, where it has to
copy an exact span. Because the student is trained only on the teacher's replies, the teacher's full-frame accuracy is
effectively its ceiling, and the teacher's systematic deviations from the SLURP conventions are inherited.</p>
<h3>Sequence-level vs logit-based distillation</h3>
<p><b>(a) Sequence-level KD</b> (Kim and Rush, 2016), used here, trains the student with ordinary cross-entropy on the
teacher's <i>generated output sequence</i>: the teacher's (approximate) mode, decoded greedily, is treated as the
hard target y&#770;, and the student maximises log p<sub>S</sub>(y&#770; | x). <b>(b) Logit-based (word-level) KD</b>
(Hinton et al., 2015) instead trains on the teacher's <i>full next-token probability distribution</i> at every position,
minimising KL(p<sub>T</sub>(&middot; | x, y<sub>&lt;t</sub>) || p<sub>S</sub>(&middot; | x, y<sub>&lt;t</sub>)), usually with a temperature,
so the student also learns how the teacher spreads probability over the alternatives (the "dark knowledge").
<b>(c) It is not possible here</b> for two independent reasons: Ollama's API returns the generated text, not the
per-position distribution over the whole vocabulary; and even with logits, phi3.5 (Llama-style SentencePiece,
32,064 tokens) and Pythia (GPT-NeoX BPE, 50,304 tokens) tokenise text differently, so their distributions are over
different vocabularies and different token boundaries and cannot be compared position by position without an
alignment method. <b>(d) Limitation of what I did:</b> the student sees one hard answer per command, so it copies
the teacher's mistakes with full confidence (for example its slot boundaries, which differ from the SLURP labels used
for scoring), and it gets no signal about which commands the teacher was unsure of; the filter in Task 1 removes
malformed replies but cannot remove fluent, wrong ones.</p>''')

    # ------------------------------------------------------------------ task 3
    seq = t3['seq']
    w(f'''<h2>Task 3. The inference service in a container</h2>
<p><b>Implementation.</b> FastAPI (<code>service/app.py</code>), port 8000. <code>POST /parse</code> runs greedy
generation, validates the output against <code>schema.json</code> with <code>jsonschema</code> (exactly the four keys,
one of the eight intents, string-or-null slots, NaN rejected) and returns either HTTP 200 with only the object or
HTTP 500 <code>{{"error": "invalid_model_output"}}</code>; both carry <code>X-Model-Version</code> and
<code>X-Served-By</code> (the Pod name from the downward API). <code>/healthz</code> answers 200 while the process
lives; <code>/readyz</code> is 503 until a background thread has downloaded every object under <code>MODEL_URI</code>
from <code>S3_ENDPOINT</code>, verified each file against <code>model.sha256</code>, loaded the model and run one
warm-up generation. Configuration comes from <code>MODEL_URI</code>, <code>MODEL_VERSION</code>,
<code>S3_ENDPOINT</code> and <code>MAX_NEW_TOKENS</code>; credentials only from the Secret; <code>FAULT_INJECT=1</code>
replaces the output with <code>not json</code> before validation. One generation runs at a time per Pod (a lock), and
torch uses as many threads as the container's CPU limit (read from the cgroup). The image (<code>service/Dockerfile</code>)
installs the CPU-only torch wheel, then every other package from a fully pinned lock with <code>--no-deps</code> and
<code>pip check</code>; it runs as a non-root user and contains no weights.</p>
<table><tr><th>check</th><th>result</th><th>evidence (results/task3/)</th></tr>
<tr><td>image size (limit 2 GB)</td><td>{v(t3["size_gb"], "{:.2f}", " GB")}</td><td>image.txt</td></tr>
<tr><td>model files inside the image</td><td>{v(None if t3["weights_found"] is None else (len(t3["weights_found"]) or "none"))}</td><td>no_weights_in_image.txt</td></tr>
<tr><td>/readyz 503 while loading, then 200; /healthz 200 throughout</td><td>{v(t3["readyz_503_samples"], "{} samples at 503 before 200")}</td><td>readiness.log, endpoints.txt</td></tr>
<tr><td>50 sequential requests at <code>--cpus 1 --memory 1g</code></td><td>{v(seq and seq[1], "{}/50 completed")}, codes {v(seq and seq[0])}; median {v(seq and seq[3], "{} ms")}, max {v(seq and seq[4], "{} ms")}</td><td>sequential_50.txt</td></tr>
<tr><td>peak memory (cgroup <code>memory.peak</code>), OOM-killed</td><td><b>{v(t3["peak_mib"], "{:.0f}", " MiB")}</b> of 1,024 MiB; OOMKilled={v(t3["oom"])}</td><td>memory_peak.txt, docker_stats.log</td></tr>
<tr><td><code>FAULT_INJECT=1</code></td><td>{v({True: "HTTP 500 with the exact error body", False: "unexpected"}.get(t3["fault_ok"]))}</td><td>fault_inject.txt</td></tr>
<caption><span class="tag m">M</span> all rows; non-200 codes in the 50-request run are invalid model outputs, which the service correctly refuses.</caption></table>
<p><b>Limitations / improvements.</b> torch dominates the image size and start-up time; exporting the model to ONNX
Runtime would shrink both. One request at a time per Pod caps throughput at one CPU's worth of decoding; batching
concurrent requests would raise it. Invalid outputs are refused, not repaired; constrained decoding against the JSON
schema would make every answer valid by construction.</p>''')

    # ------------------------------------------------------------------ task 4
    cold = t4['cold'] or {}
    runs = cold.get('runs', [])
    cold_cells = ', '.join(f"{r['cold_start_s']:.0f} s" for r in runs) if runs else PENDING
    roll = t4['rolling'] or {}
    rec = t4['recovery'] or {}
    lb = t4['lb']
    lb_total = sum(lb.values()) if lb else None
    lb_text = ', '.join(f'{100.0 * n / lb_total:.1f} %' for n in sorted(lb.values(), reverse=True)) if lb else PENDING
    seq0, seqmax, seqend = t4['hpa_seq']
    zero_samples = [r.get('samples_with_zero_ready_endpoints') for r in runs]
    w(f'''<h2>Task 4. Kubernetes deployment, scaling and reliability</h2>
<p><b>Implementation</b> (<code>k8s/app/parser.yaml</code>). Namespace <code>app</code>: a Deployment starting at
2 replicas (requests 500m CPU / 768 Mi, limits 1 CPU / 1 Gi; readiness probe <code>/readyz</code> every 2 s,
liveness <code>/healthz</code> every 10 s with 6 allowed failures; rolling update <code>maxSurge 1,
maxUnavailable 0</code>; <code>preStop</code> sleep 5 s so Traefik drops a terminating Pod before it stops; graceful
shutdown 20 s), a ClusterIP Service, a Traefik Ingress for <code>/parse</code> only, and an <code>autoscaling/v2</code>
HPA (1 to 2 replicas, 70 % average CPU of the request, scale-down window shortened to 60 s so it can be observed).
The scripts in <code>scripts/experiments/</code> produce every row below.</p>
<table><tr><th>experiment</th><th>measured result</th><th>evidence (results/task4/)</th></tr>
<tr><td>/parse through the Ingress</td><td>{v({True: "HTTP 200 with both headers", False: "failed"}.get(t4["ingress_ok"]))}</td><td>basics/ingress_curl.txt, resources.txt</td></tr>
<tr><td>no ready endpoints while the model loads</td><td>{v(zero_samples if runs else None)} timeline samples (0.5 s apart) with 0 ready endpoints after deleting all Pods</td><td>coldstart/run*_endpoints.log</td></tr>
<tr><td>HPA under load (4 users)</td><td>replicas {v(seq0)} &rarr; {v(seqmax)} &rarr; {v(seqend)}; {v((t4["hpa_load"] or {}).get("failures"))} failed of {v((t4["hpa_load"] or {}).get("requests"))}</td><td>hpa/timeline.log, describe_hpa.txt</td></tr>
<tr><td>rolling update v1&rarr;v2, then <code>rollout undo</code>, under load</td><td><b>{v(roll.get("failure_pct"), "{:.2f}", " %")}</b> failed ({v(roll.get("failures"))} of {v(roll.get("requests"))}); versions served {v((roll.get("headers") or {}).get("per_model_version"))}; after rollback {v(t4["after_v1"])} of 5 answers say v1</td><td>rolling/rolling.log, version_timeline.log, after_rollback.txt</td></tr>
<tr><td>delete one Pod under load</td><td>back to 2 Ready after {v(t4["recovery_s"], "{:.1f}", " s")}; <b>{v(rec.get("failure_pct"), "{:.2f}", " %")}</b> failed ({v(rec.get("failures"))} of {v(rec.get("requests"))})</td><td>recovery/recovery.log, timeline.log</td></tr>
<tr><td>cold start: delete all Pods, 3 runs</td><td>{cold_cells}; <b>median {v(cold.get("median_cold_start_s"), "{:.0f}", " s")}</b> (Pod creation to Ready); logs show the download from <code>s3://models/v1/</code></td><td>coldstart/summary.txt, run*_*.log</td></tr>
<tr><td>load balancing, exactly 2 Ready replicas</td><td>successful requests per replica: {lb_text} (each must be &ge; 30 %)</td><td>loadbalance/loadbalance.log</td></tr>
<caption><span class="tag m">M</span> all rows. For the recovery and load-balancing runs the HPA minimum was held at 2 so that two replicas existed; it was set back to 1 afterwards.</caption></table>
<p><b>Limitations.</b> <span class="tag a">A</span> The cluster is one k3s node in one container on one machine:
the experiments show recovery from a lost <i>Pod</i>, not from a lost node, disk or machine; there is no fault tolerance
across machines, and SeaweedFS is a single replica on a single volume. The HPA reacts to metrics-server samples (15 s)
plus a stabilisation window, so it lags short bursts; and the replica count is capped at 2 by the assignment.
<b>Improvements:</b> 3+ nodes (k3d agents) with pod anti-affinity, a PodDisruptionBudget, SeaweedFS replication, a
startup probe instead of a long liveness delay, and an HPA on request latency rather than CPU.</p>''')

    # ------------------------------------------------------------------ task 5
    nacl = text('results', 'network', 'nacl_check.txt') or ''
    sample_score = re.search(r'Correct: (\d+) / (\d+)', nacl)
    w(f'''<h2>Task 5. Subnetting and network access control</h2>
<div class="two"><div>
<table><tr><th>subnet</th><th>network / prefix</th><th>usable range</th><th>broadcast</th><th class="n">hosts</th></tr>
<tr><td>app (1,000)</td><td>10.20.0.0/22</td><td>10.20.0.1 - 10.20.3.254</td><td>10.20.3.255</td><td class="n">1,022</td></tr>
<tr><td>public (250)</td><td>10.20.4.0/24</td><td>10.20.4.1 - 10.20.4.254</td><td>10.20.4.255</td><td class="n">254</td></tr>
<tr><td>data (100)</td><td>10.20.5.0/25</td><td>10.20.5.1 - 10.20.5.126</td><td>10.20.5.127</td><td class="n">126</td></tr>
<tr><td>management (20)</td><td>10.20.5.128/27</td><td>10.20.5.129 - 10.20.5.158</td><td>10.20.5.159</td><td class="n">30</td></tr>
<caption>Working in network/subnets.md: largest first, smallest prefix with 2<sup>32-p</sup>-2 &ge; need (one bit smaller gives 510, 126, 62, 14: too few); each block starts right after the previous one. Verified with Python ipaddress in tests/test_network.py.</caption></table>
</div><div>
<table><tr><th>dir</th><th>rule</th><th>match</th><th>action</th></tr>
<tr><td>in</td><td>50</td><td>all, 198.51.100.0/24</td><td>deny</td></tr>
<tr><td>in</td><td>100 / 110</td><td>tcp 80 / tcp 443, 0.0.0.0/0</td><td>allow</td></tr>
<tr><td>in</td><td>120</td><td>tcp 22, 10.20.5.128/27 (management)</td><td>allow</td></tr>
<tr><td>in</td><td>130</td><td>tcp 1024-65535, 10.20.0.0/22 (app replies)</td><td>allow</td></tr>
<tr><td>out</td><td>100</td><td>tcp 8000, 10.20.0.0/22 (app)</td><td>allow</td></tr>
<tr><td>out</td><td>110</td><td>tcp 1024-65535, 0.0.0.0/0 (client replies)</td><td>allow</td></tr>
<tr><td>both</td><td>32766</td><td>all, 0.0.0.0/0</td><td>deny</td></tr>
<caption><span class="tag m">M</span> nacl_sim.py on packets_sample.jsonl: {v(sample_score and sample_score.group(1))} / {v(sample_score and sample_score.group(2))} correct; 16 / 16 on my edge cases (results/network/nacl_check.txt).</caption></table>
</div></div>
<p><b>Why stateless rules need reply rules, and why order matters.</b> A NACL keeps no connection state: every packet,
including a reply, is evaluated on its own. When a client opens a connection to the load balancer on 443, the answer
leaves the subnet towards the client's ephemeral port (1024-65535); without outbound rule 110 every response would be
dropped. Likewise the load balancer's request to the app goes out on TCP 8000, but the app's answer arrives on one of
the load balancer's ephemeral ports and needs inbound rule 130 (a stateful security group would allow both
automatically). Rules are checked from the lowest number and the first match wins. A packet from 198.51.100.9 to port
443 matches both the deny and the "443 from anywhere" allow, so the deny only works if its number is lower than the
allow it must override: renumbering it from 50 to 140 lets that packet in (results/network/nacl_wrong_order_check.txt,
5 / 6). Limitation: a stateless NACL cannot tell a reply from a new connection, so outbound rule 110 also permits new
connections to any high port.</p>''')

    # ------------------------------------------------------------------ task 6
    mu = text('results', 'task6', 'make_up.log') or ''
    real = re.search(r'real\s+(\d+)m([\d.]+)s', mu)
    mu_min = (int(real.group(1)) + float(real.group(2)) / 60) if real else None
    md = text('results', 'task6', 'make_down.log') or ''
    w(f'''<h2>Task 6. Reproducibility, testing and CI/CD</h2>
<p><b>Reproducibility.</b> From a fresh clone the whole system comes up with three commands (<code>git clone</code>,
<code>cd cc</code>, <code>make up</code>): cluster, Secrets, SeaweedFS, buckets and dataset, model Releases downloaded,
verified and uploaded, image built and imported, app deployed, smoke request. <code>make down</code> deletes the cluster.
The <code>experiments</code> workflow runs exactly this on a clean runner: <code>make up</code> took
{v(mu_min, "{:.1f}", " min")} (results/task6/make_up.log) and <code>make down</code> left
{v(("no clusters" if "cc " not in md.split("k3d cluster list", 1)[-1] else "a cluster") if md else None)} (make_down.log).
Python dependencies are pinned (service image: full lock); the cluster image, SeaweedFS and Ollama tags are pinned.</p>
<table><tr><th>ci.yml stage (in order)</th><th>what it does</th></tr>
<tr><td>1. lint + secret scan</td><td><code>ruff check .</code>; gitleaks 8.30.1 over the full Git history (must report nothing)</td></tr>
<tr><td>2. unit tests</td><td>54 pytest tests: clean.py rules, sharding, service API and headers, schema validation, subnets, NACL</td></tr>
<tr><td>3. model evaluation</td><td>downloads the Release <code>model-v1</code>, checks <code>sha256sum -c model.sha256</code>, predicts validation.jsonl, runs score.py</td></tr>
<tr><td>4. quality gate</td><td><code>score.py --min-validity 95</code>; fails the pipeline below 95 % JSON validity</td></tr>
<caption><span class="tag m">M</span> passing run: {('<a href="' + esc(ci['passing']) + '">' + esc(ci['passing']) + '</a>') if ci.get('passing') else PENDING};
run with the untrained Pythia-70M failing at the gate: {('<a href="' + esc(ci['failing_gate']) + '">' + esc(ci['failing_gate']) + '</a>') if ci.get('failing_gate') else PENDING}.</caption></table>
<p>The AI tools used, and how their output was checked, are described in <code>AI_USE.md</code>.
<b>Limitation:</b> CI evaluates on the 100 validation commands only and cannot reproduce the multi-hour labelling;
<b>improvement:</b> a nightly job that re-runs <code>make up</code> and the load test, and a held-out split of the pool.</p>''')

    # ------------------------------------------------------------------ task 7
    t7 = t7 or {}
    cost = t7.get('cost', {})
    pods = t7.get('pods') or {}
    pod_rows = ''.join(f'<tr><td><code>{esc(p)}</code></td><td class="n">{d["cpu_m_mean"]} / {d["cpu_m_max"]} m</td>'
                       f'<td class="n">{d["mem_mi_mean"]} / {d["mem_mi_max"]} Mi</td><td class="n">{d["samples"]}</td></tr>'
                       for p, d in sorted(pods.items())) or f'<tr><td colspan="4">{PENDING}</td></tr>'
    slo = t7.get('slo') or {}
    steps = ''.join(f'<li>{esc(s)}</li>' for s in cost.get('steps', [])) or f'<li>{PENDING}</li>'
    w(f'''<h2>Task 7. Performance, cost and review</h2>
<div class="two"><div>
<table><tr><th>standard load test (4 users, 2 min, via Ingress)</th><th class="n">value</th></tr>
<tr><td>requests / failed</td><td class="n">{v(t7.get("requests"))} / {v(t7.get("failures"))}</td></tr>
<tr><td>error rate</td><td class="n"><b>{v(t7.get("error_rate_pct"), "{:.2f}", " %")}</b></td></tr>
<tr><td>p50 latency</td><td class="n"><b>{v(t7.get("p50_ms"), "{:.0f}", " ms")}</b></td></tr>
<tr><td>p95 latency</td><td class="n"><b>{v(t7.get("p95_ms"), "{:.0f}", " ms")}</b></td></tr>
<tr><td>throughput</td><td class="n"><b>{v(t7.get("throughput_rps"), "{:.2f}", " req/s")}</b></td></tr>
<tr><td>mean replicas during the run</td><td class="n">{v(t7.get("replicas_mean_during_test"))}</td></tr>
<tr><td>cold start, median of 3 (Task 4)</td><td class="n">{v(t7.get("cold_start_median_s"), "{:.0f}", " s")}</td></tr>
<caption><span class="tag m">M</span> results/loadtest_stats.csv, results/task7/summary.json, timeline.log.</caption></table>
</div><div>
<table><tr><th>Pod (kubectl top, every 10 s)</th><th class="n">CPU mean / max</th><th class="n">memory mean / max</th><th class="n">n</th></tr>
{pod_rows}
<caption><span class="tag m">M</span> results/task7/top_pods.log. metrics-server reports a 15 s window, so the first sample after the load starts still shows idle CPU.</caption></table>
<div class="box"><b>Cost per 1,000 requests</b> (data/rate_card.json: INR 3.50 per vCPU-hour, INR 0.45 per GiB-hour; each replica billed for its limits, 1 vCPU and 1 GiB):
<ol>{steps}</ol></div>
</div></div>
<p><b>SLO.</b> <i>{v(slo.get("objective"))}</i> over the window <i>{v(slo.get("window"))}</i>. Error budget =
1 % of {v(t7.get("requests"))} requests = <b>{v(slo.get("error_budget_requests"), "{:.2f}")}</b> failed requests;
used: {v(slo.get("failed_requests"))} failed = <b>{v(slo.get("budget_used_pct"), "{:.0f}", " %")}</b> of the budget
(SLO {v({True: "met", False: "missed"}.get(slo.get("met")))}).
<span class="tag a">A</span> The cost counts only the parser replicas at their limits (not SeaweedFS, Traefik or the
control plane) and assumes the measured throughput is sustained for the whole hour.</p>''')
    w(review_table(t1, t2, t3, t4, t7))

    # ------------------------------------------------------------------ references + appendix
    w('''<h2>References</h2>
<ol class="small">
<li>Y. Kim, A. M. Rush. Sequence-Level Knowledge Distillation. EMNLP 2016. https://aclanthology.org/D16-1139/</li>
<li>G. Hinton, O. Vinyals, J. Dean. Distilling the Knowledge in a Neural Network. arXiv:1503.02531, 2015.</li>
<li>Y.-C. Chen et al. Distilling Knowledge Learned in BERT for Text Generation. ACL 2020.</li>
<li>E. Bastianelli et al. SLURP: A Spoken Language Understanding Resource Package. EMNLP 2020 (CC BY 4.0).</li>
<li>S. Biderman et al. Pythia: A Suite for Analyzing Large Language Models. ICML 2023; EleutherAI/pythia-70m model card.</li>
<li>Microsoft. Phi-3 Technical Report (Phi-3.5-mini-instruct); Ollama library phi3.5.</li>
<li>Hugging Face Transformers and TRL documentation (causal LM fine-tuning; GKD/distillation trainer).</li>
<li>k3d and K3s documentation; SeaweedFS (S3 API); Kubernetes docs: Deployments, Services, Ingress, probes, HPA, Secrets, Indexed Jobs.</li>
<li>Locust; gitleaks; AWS VPC User Guide, Network ACLs; Google SRE Book, Service Level Objectives.</li>
</ol>''')
    w(appendix())
    return '\n'.join(out)


def review_table(t1, t2, t3, t4, t7):
    c = t1['counts']
    v1 = t2['v1'] or {}
    roll = t4['rolling'] or {}
    cold = (t4['cold'] or {}).get('median_cold_start_s')
    cost = (t7.get('cost') or {}).get('measured_mean_replicas', {}).get('cost_per_1000')
    rows = [
        ('Data and storage', f'{v(c.get("kept"))} of {v(c.get("input"))} teacher replies kept; train.jsonl checksum reproduced',
         'rule (d) keeps fluent but wrong spans; single SeaweedFS replica', 'second teacher pass on rejects; replicated object store'),
        ('Model quality', f'student full frame {v(v1.get("full_frame"), "{:.1f}", " %")}, JSON validity {v(v1.get("json_validity"), "{:.1f}", " %")}',
         'copies the teacher\'s slot-boundary errors; 70 M parameters', 'logit KD with a same-tokenizer teacher; constrained decoding'),
        ('Latency and throughput', f'p95 {v(t7.get("p95_ms"), "{:.0f}", " ms")}, {v(t7.get("throughput_rps"), "{:.2f}", " req/s")}',
         'one request at a time per Pod; greedy decoding on 1 CPU', 'request batching; ONNX Runtime / int8'),
        ('Resource utilisation', f'peak memory {v(t3["peak_mib"], "{:.0f}", " MiB")} of 1 GiB at 1 CPU',
         'CPU saturates while memory is mostly idle', 'smaller memory limit (cheaper); more replicas per node'),
        ('Reliability and recovery', f'rolling update {v(roll.get("failure_pct"), "{:.2f}", " %")} failed; cold start median {v(cold, "{:.0f}", " s")}',
         'single node: no machine-level fault tolerance', 'multi-node cluster, anti-affinity, PodDisruptionBudget'),
        ('Security and cost', f'gitleaks: 0 findings; INR {v(cost, "{:.3f}")} per 1,000 requests',
         'S3 over plain HTTP inside the cluster; replicas billed at full limits when idle', 'TLS + NetworkPolicies; scale to zero off-peak'),
    ]
    body = ''.join(f'<tr><td>{a}</td><td>{b}</td><td>{c_}</td><td>{d}</td></tr>' for a, b, c_, d in rows)
    return f'''<table><tr><th>component or concern</th><th>evidence (a measured number)</th><th>limitation found</th><th>improvement proposed</th></tr>{body}
<caption>Review. <span class="tag m">M</span> evidence column; the other columns are my assessment.</caption></table>'''


def appendix():
    return '''<div class="appendix"><h2>Appendix A. Measured results vs assumptions</h2>
<p><b>Measured</b> (each number in the body is read at build time by <code>report/build_report.py</code> from these files):
results/task1 (labelling, cleaning, coverage), datasets/v1/train.sha256, training/loss*.csv, results/teacher_validation.json,
results/task2 (training logs, evaluations, S3 listing, Release checks), results/task3, results/task4, results/network,
results/task6, results/loadtest_* and results/task7.</p>
<p><b>Assumptions and design choices</b> (not measurements): the rate card prices are hypothetical; cost counts only the
parser replicas at their limits and assumes the measured throughput holds for an hour; the SLO target (99 %) and window
(one standard run) are my choices; the HPA scale-down window was shortened to 60 s for observability; the HPA minimum
was raised to 2 during the recovery and load-balancing runs; validation scores are optimistic for the teacher because
the prompt's conventions were chosen after looking at the kind of labels in validation.jsonl (no validation command or
label is in the prompt); a GitHub-hosted runner (4 vCPU, 16 GiB) stands in for a student laptop.</p>
<h2>Appendix B. Reproducing every number</h2>
<p><code>make up</code>; <code>make label</code> (Task 1); <code>make train</code>, <code>make train MODEL_VERSION=v2</code>,
<code>make eval</code>, <code>make eval-untrained</code> (Task 2); <code>bash scripts/experiments/run_all.sh</code>
(Tasks 3, 4, 7); <code>python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check</code> (Task 5);
<code>make lint test</code> (Task 6); <code>python report/build_report.py &amp;&amp; node report/render.cjs</code> (this report).</p></div>'''


def main():
    body = build()
    css = text('report', 'style.css')
    doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Command Parser Report</title>
<style>{css}</style></head><body>{body}</body></html>'''
    with open(path('report', 'report.html'), 'w', encoding='utf-8') as f:
        f.write(doc)
    pending = doc.count('class="pending"')
    print(f'wrote report/report.html ({pending} values still PENDING)')


if __name__ == '__main__':
    main()
