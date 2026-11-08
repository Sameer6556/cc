# Use of AI tools

AI tools were used as part of the development process for this project. I used Claude as a coding assistant to speed up implementation, troubleshoot issues, and organise the project around the seven tasks in the assignment. The work was guided by the assignment requirements, and the generated code and results were checked through the project's tests, evaluation scripts, and recorded experiments.

## Tool used

| Tool | How it was used |
|---|---|
| **Claude** (Anthropic AI assistant, used as a coding agent on claude.ai) | Used for planning and implementing project components, generating and refining code, helping debug workflow issues, preparing CI automation, and drafting technical documentation. It assisted with the worker and cleaning pipeline, model training and evaluation scripts, FastAPI service, Dockerfiles, Kubernetes manifests, tests, network configuration, README, and report. |

Phi-3.5 through Ollama was used as the teacher model, and EleutherAI Pythia-70M was used as the student model, as required by the assignment. These were part of the machine-learning workflow rather than general-purpose coding assistants. No paid inference API was used.

## My role and contribution

I treated the assignment rubric as the project plan and worked through the requirements task by task. My contribution focused on setting the direction, defining constraints, making project decisions, reviewing the implementation and understanding the results.

- I provided the assignment brief and student kit and used the seven tasks and marking criteria to define the expected features and deliverables.
- I set the key constraints for development: use the specified Phi-3.5 teacher and Pythia-70M student, keep the teacher settings fixed, train only on teacher-generated replies, use free tools, and keep credentials and model weights out of the Git repository.
- I guided the development around the complete workflow, from teacher labelling and dataset cleaning to CPU training, model evaluation, object storage, containerisation, Kubernetes deployment, networking, and CI.
- Where implementation choices were presented, I considered the alternatives and made the required decisions for the project. I also connected the GitHub account and authorised the coding session to work with the repository and run its workflows.
- I followed the implementation through its iterations, asked for explanations of the architecture and important code paths, and reviewed the recorded outputs against the assignment requirements.
- I focused on understanding how the components work together and what the results show, including the limitations of a small student model and of running Kubernetes on a single local node.

Claude assisted substantially with writing code and automating the longer workflows. This allowed me to focus on the assignment requirements, project direction, reviewing the implementation, and understanding the technical decisions instead of spending the entire project writing boilerplate manually.

## Testing and verification

The project includes automated checks and recorded evidence for the main requirements. These checks were used during development, and their outputs are available in the repository for review and reproduction.

1. **Code quality and unit tests:** the CI workflow runs Ruff, Gitleaks, and 54 pytest tests. The tests cover data cleaning, shard assignment, service endpoints and response headers, invalid model output, subnet calculations, and NACL rules.
2. **Model evaluation:** the supplied `tools/score.py` is used to compare the teacher, the original untrained Pythia-70M, and the trained student. Raw predictions and score reports are saved under `results/`.
3. **Dataset and model integrity:** the cleaned dataset is regenerated from the teacher shards and checked against its SHA-256 checksum. Model Release assets are also checked against their recorded checksums.
4. **Networking:** subnet calculations are checked with Python's `ipaddress` module. The NACL is tested with the provided sample packets and additional edge cases, including a case showing why the deny rule must appear before broader allow rules.
5. **Deployment and performance:** the recorded experiments cover container resource limits, readiness and liveness behaviour, fault injection, rolling updates, rollback, Pod recovery, cold starts, autoscaling, load balancing, and Locust performance results.

The long-running labelling, training, and deployment experiments recorded in `results/` were executed through GitHub Actions on GitHub-hosted CPU runners. The commands and configuration needed to reproduce the workflow are documented in the README.

## Development challenges and changes

A few issues during development helped reveal practical differences between a design that looks correct and one that works under load.

- **Teacher labelling:** the first full run used an HTTP liveness probe with a very short timeout. While Ollama was busy generating responses on the CPU, the probe timed out and Kubernetes restarted it repeatedly. The run stopped after 900 replies. The probe was changed to a TCP check, the saved shard outputs were reused, and the workers were run two at a time for the resumed run.
- **Workflow reliability:** dry runs exposed issues in helper scripts and coverage checking. These were corrected before relying on the final experiment outputs.
- **Rolling update:** the test recorded two failed requests while switching between model versions. The logs showed that these requests were rejected because v2 produced invalid JSON, rather than because Kubernetes failed to replace the Pods. This was an important distinction between application-level errors and deployment errors.

## Learning and findings

The project connected model training with practical cloud infrastructure. The main learning outcomes for me were:

- Sequence-level knowledge distillation trains the student using the teacher's generated answers as targets. It does not require access to the teacher's internal logits.
- A smaller model can learn the output format and much of the teacher's behaviour, but it can still make mistakes in intent classification and slot extraction.
- Dataset cleaning is important because incorrect or inconsistent teacher responses can become training targets. Sharding also makes a large labelling job easier to distribute and resume.
- Docker keeps the inference service separate from the model files, while object storage provides the model artefacts when a Pod starts.
- Kubernetes readiness probes prevent traffic from reaching a Pod before its model is loaded. Liveness probes serve a different purpose: checking whether the process should be restarted.
- A stateless NACL evaluates each packet independently, so reply traffic needs its own rule. Rule order matters when a specific deny rule overlaps with a wider allow rule.
- A successful deployment does not guarantee correct predictions. The model's output quality, API validation, and infrastructure health need to be evaluated separately.

The results also showed the limits of the setup. The student reached 56% full-frame accuracy on the validation set compared with 62% for the teacher. The local Kubernetes environment uses a single node, so the recovery experiment demonstrates Pod replacement, not protection against failure of the entire machine. The cost result is an estimate based on the hypothetical rate card supplied for the assignment.

## Conclusion

Using AI assistance made it possible to build and test all parts of the assignment within the available time. My focus throughout the project was to keep the implementation aligned with the rubric, make the required project decisions, follow the development and experiment results, and understand the system well enough to explain its architecture, behaviour, and limitations. The repository includes the implementation, tests, model artefacts through GitHub Releases, and experiment evidence so that the work can be inspected and reproduced.
