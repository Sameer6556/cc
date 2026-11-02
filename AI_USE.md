# Use of AI tools

## Tools used

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic's agentic coding assistant, run as a cloud session on claude.ai) | Reading the handout and the student kit; designing the architecture; writing the worker, `clean.py`, training/evaluation scripts, the FastAPI service, Dockerfiles, Kubernetes manifests, Makefile, CI workflows, unit tests, the subnet plan and NACL; running the experiments; drafting the report and the README. |

No other AI tool, model or paid API was used. The teacher model (phi3.5 on Ollama) and the student
(Pythia-70M) are part of the assignment itself, not assistants.

## How the output was checked

AI-generated code was treated as untrusted until it was tested. The checks below are reproducible
from the repository.

1. **Unit tests** (`make test`, 54 tests): every rejection rule of `clean.py`, the duplicate rule, the order
   independence of the output, the shard partition (no gaps, no repeats), the service's three endpoints, both
   headers, the exact error body, `FAULT_INJECT`, schema validation edge cases (NaN, extra keys, wrong
   types), the subnet table and the NACL.
2. **Kit tools as the referee.** `tools/score.py`, `tools/nacl_sim.py` and `tools/locustfile.py` are used
   unmodified, and all reported numbers come from their outputs or from `kubectl`/`docker` output that is
   saved in `results/`.
3. **Independent recomputation.**
   - The subnet table was recomputed with Python's `ipaddress` module (`tests/test_network.py`).
   - The NACL was checked against the 6 sample packets plus 16 extra edge-case packets, and against a
     deliberately mis-ordered copy, to confirm that the deny rule's position matters.
   - The `train.jsonl` checksum was recomputed by re-running `clean.py` outside the cluster.
   - The model checksums were re-verified with `sha256sum -c` after downloading the Release assets.
4. **Dry runs before the real runs.** The Kubernetes manifests and every experiment script were first run
   on a local k3d cluster, with a mock teacher and a stub inference image, to check the mechanics: sharding,
   resume, cleaning, readiness, rolling update, recovery, HPA and load balancing. The mock and stub runs
   only checked the mechanics; none of their numbers appear in the report.
5. **No fabricated results.** The report's numbers are copied from files in `results/` produced by the
   runs linked in the report. Where something could not be measured, the report says so.

## Where the AI was wrong or needed correcting

- A `pkill -f` pattern matched its own shell. The AI also tripped over `set -e` combined with `pipefail`
  in a pipeline whose loop ended on a failed `kubectl get`, which aborted the cold-start script. Both were
  found by dry runs and fixed.
- The first coverage checker reused a loop variable and would have miscounted shard sizes. This was
  caught in review before any real run.
- Credentials left in the shell environment from an earlier manual test silently took precedence over
  the cluster's generated credentials. The S3 helper now prefers the generated `.secrets/s3.env`.
- Inside a cgroup-v1 nested container the CPU limit is not visible, so the thread count falls back to
  the host CPU count. This is documented as a limitation; it works on cgroup v2.
- The first full labelling run was designed badly: four workers at once, and an HTTP liveness probe on
  Ollama with a 1 s timeout. With every core busy generating, the probe timed out, Kubernetes restarted
  Ollama 23 times and the Job failed after 900 of 3,000 replies (commit 772487b). The probes became TCP
  checks, two workers run at a time, and the run was resumed from the 900 saved replies. Measuring showed
  that extra workers did not add throughput anyway (6.2 to 6.8 s per command overall with one, two or
  four), because the teacher is compute-bound.
- Two workflow files put a colon inside a one-line `run:` value, which is invalid YAML, so GitHub did
  not start them. A cancelled labelling run still committed its partial evidence; those files were
  deleted in the next commit (6ed0302) and the evidence steps now skip cancelled runs.
