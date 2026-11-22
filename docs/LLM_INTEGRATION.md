# LLM integration milestone: possible next steps

> **Status: planning only.** Nothing in this document is built yet. V1 runs without an LLM or API key. This file lists options and possible next steps for the milestone, so they can be discussed, reordered, or dropped before any work starts.

## Goal

Replace V1's canned answers with **live model answers** and measure whether a prompt change reduces contradicted and unsupported answers. The evaluator, checker, metrics, dashboard, and alert from V1 stay the same. Only the source of the answers changes.

```
V1:  canned answers  ──►  /evaluate  ──►  verdict  ──►  metrics, logs, dashboard, alert
V2:  LLM answers     ──►  /evaluate  ──►  (unchanged)
```

## The experiment

Run the **same six questions** from `data/cases.json` against **two prompt versions** and compare their flagged-answer rates.

| Held fixed | Varied |
|---|---|
| Model (one pinned model ID) | System prompt: `prompt-a` vs `prompt-b` |
| Generation settings (temperature 0, fixed max tokens) | |
| Runbook (same file, recorded by content hash) | |
| Questions (the six cases) | |
| Checker, alert thresholds | |

Only the prompt changes, so a difference in flagged rate between `prompt-a` and `prompt-b` can be attributed to the prompt. `prompt-a` and `prompt-b` are already in the evaluator's `prompt_version` allowlist, so the metrics need no changes.

Prompt ideas:

- **`prompt-a` (baseline):** "You are a helpful platform engineering assistant. Use the runbook below to answer."
- **`prompt-b` (grounded):** "Answer **only** from the runbook. If the runbook doesn't cover the question, say it isn't documented. If the question contains a false assumption, correct it."

---

## To-do list

Actionable items, in rough order. Check them off as they land.

- [ ] **Add a GitHub Actions workflow that runs `make check`.** *This doesn't depend on the LLM work and can be done now.*
  - **File:** `.github/workflows/check.yml`
  - **Triggers:** every push to `main` and every pull request.
  - **Steps:** check out the repo → set up Python 3.12 (matches the evaluator image) → set up Terraform (pin the version used locally) → `make venv` → `make check`.
  - **What `make check` covers:** 40 pytest tests, `terraform fmt -check`, `terraform validate` on both stages (`init -backend=false`, so no AWS credentials or state are needed), and `bash -n` on the scripts.
  - **Requirements:** no secrets or AWS credentials. It must stay that way, so live model calls (Phase 6) go in a separate, manually started workflow.
  - **Both repos:** the workflow file is part of the repo, so pushing it to `kingmellow08` and `Devops-Detroit` enables it in both. Check that Actions is allowed in the `Devops-Detroit` organization settings.
  - **Afterwards:** add a status badge to the README, and optionally make the check required before merging to `main`.
  - Sketch:
    ```yaml
    name: check
    on:
      push:
        branches: [main]
      pull_request:
    permissions:
      contents: read
    jobs:
      check:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: "3.12"
          - uses: hashicorp/setup-terraform@v3
            with:
              terraform_version: "1.16.5"   # match your local version
              terraform_wrapper: false
          - run: make venv
          - run: make check
    ```
- [ ] Phase 0: decide on model access (Bedrock or a direct API), the model, the repetition count, and the budget.
- [ ] Phase 1: version the prompts and runbook (files, hashes, run manifest).
- [ ] Phase 2: build the `generate` command.
- [ ] Phase 3: run the generator in AWS.
- [ ] Phase 4: measure and handle checker gaps on free-form answers.
- [ ] Phase 5: add the prompt-A-vs-B comparison panel and generator health metrics.
- [ ] Phase 6: add recorded-answer fixtures and a fake model client, so CI never needs a key.
- [ ] Phase 7 (optional): keep metric history.

## Possible next steps

These are grouped into phases. Each phase is useful on its own, and later phases can be skipped.

### Phase 0: decisions to make first

| Decision | Options | Notes |
|---|---|---|
| **Model access** | (a) **Amazon Bedrock**: call the model with the task's IAM role. (b) A provider's API directly, with an API key. | Bedrock needs no API key in the container. Access is controlled by IAM (`bedrock:InvokeModel` on one model), and the model must be available in your account and region. A direct API needs the key stored in Secrets Manager or SSM. |
| **Model** | Any current chat model. Pin one exact model ID. | Record the model ID in every log line. Changing the model starts a new experiment. |
| **Repetitions** | N runs per question per prompt version, for example 5. | 6 questions × 5 runs = 30 evaluations per prompt version, which clears the alert's minimum count of 10. Runs at temperature 0 are mostly repeatable, but not guaranteed to be identical, so repeats show how stable the answers are. |
| **Budget** | Set a maximum number of calls per run. | 2 prompts × 6 questions × N runs. Keep N small until the cost per run is known. |

### Phase 1: version the inputs

- Store the prompts as files: `prompts/prompt-a.md`, `prompts/prompt-b.md`.
- Compute a content hash (SHA-256) for each prompt file and for the runbook at run time.
- Write a small run manifest per experiment: model ID, settings, prompt hashes, runbook hash, N, and start time. This makes every result traceable to its exact inputs.

### Phase 2: build a generator

- Add a `generate` command to the CLI, next to `evaluate` and `replay`:
  ```
  python -m delusion_monitor generate --prompt-version prompt-b --runs 5 --target http://localhost:8000
  ```
- For each case and run, the generator:
  1. Sends the system prompt, the runbook, and the question to the model.
  2. POSTs the answer to `/evaluate` with `prompt_version` set.
  3. Logs the model ID, run ID, prompt hash, runbook hash, latency, and token counts.
- Keep the generator **separate from the evaluator**. The evaluator stays deterministic and never needs model credentials.
- Add timeouts, a few retries with backoff for rate limits, and a hard cap on total calls.
- **Labels stay bounded:** model ID, hashes, and run IDs go in **logs**, never in Prometheus labels.

### Phase 3: run it in AWS

- **Where it runs:**
  - Option 1: a fourth container in the task.
  - Option 2 (cleaner): a separate one-off ECS task started with `aws ecs run-task`.
  - Option 3: a scheduled run with EventBridge Scheduler targeting ECS.

  A separate task keeps the monitor running while experiments come and go. It would reach the evaluator over the VPC instead of localhost. That needs one security-group rule from the generator to the evaluator on port 8000, with the evaluator listening on its task IP instead of only `127.0.0.1`.
- **IAM:** give the generator its own task role. For Bedrock, allow `bedrock:InvokeModel` on the one pinned model ARN. For a direct API, let only the generator read the secret.
- **Networking:** the existing outbound rule (TCP 443) already allows calls to Bedrock or an external API.
- **Terraform:** add the generator task definition, role, and optional schedule to stage 1, behind a variable (for example, `enable_generator`) so V1 still deploys without it.

### Phase 4: handle free-form answers

Real model answers are wordier and less predictable than the canned ones. The V1 checker is designed for retention durations and environment names.

1. **Measure first.** Count how many live answers end up `unsupported` because the checker found no duration and no "undocumented" statement. Review a sample by hand.
2. **Extend the rules** where the gaps are clear: more phrasings for "not documented", more number formats, clause-level environment detection.
3. **Only if needed,** add a second opinion: an LLM-as-judge or an entailment model. Log its verdict **beside** the deterministic one at first, and keep the deterministic verdict as the source of the metric until the two agree on a hand-labelled sample.
4. Optionally add a fourth verdict, `unparseable`, so checker gaps don't inflate the `unsupported` count. Adding it means one more value for the `verdict` label, which stays bounded.

### Phase 5: dashboard and alerts

- Add a **side-by-side panel**: flagged rate for `prompt-a` vs `prompt-b` over the same window, plus the difference between them.
- Add generator health metrics with bounded labels:
  - `delusion_generation_requests_total{prompt_version, outcome}`, where `outcome` is `ok`, `error`, or `timeout`
  - a latency histogram
  - token counters
- Add an alert on the generator error rate, and optionally a cost guard based on the token counters.
- Annotate the dashboard with each run's start and end, so each run is easy to pick out.

### Phase 6: tests and CI without an API key

- Record real model answers once and save them as fixtures, for example `data/recorded/prompt-a.json`. Replay them in tests, so `make check` never needs a key or network access.
- Add a fake model client for unit tests of the generator: retries, timeouts, the call cap.
- The `make check` workflow from the [to-do list](#to-do-list) runs these on every push. Live model calls belong in a separate workflow that only runs when started manually.

### Phase 7 (optional): keep the history

V1 loses its metrics and Grafana configuration whenever the task is replaced. That's fine for a demo, but comparing experiments over weeks needs history. Options:

- An EFS volume mounted into the task for the Prometheus and Grafana data.
- Amazon Managed Service for Prometheus and Amazon Managed Grafana instead of the in-task containers.
- Writing each run's results (verdicts plus the manifest) to S3 as JSON, which is cheap and easy to analyze later.

---

## Risks to keep in mind

| Risk | Mitigation |
|---|---|
| Answers vary between runs, even at temperature 0 | Use several repetitions, and compare rates rather than single answers |
| Checker gaps get counted as hallucinations | Phase 4: measure, extend the rules, and consider an `unparseable` verdict |
| Cost and rate limits | Call cap, small N, backoff, and a token-based cost alert |
| Credentials leak | Prefer Bedrock with an IAM role. Otherwise, inject the secret into the generator only |
| Too many metric series | Model, hashes, and run IDs go in logs only; prompt versions stay allowlisted |
| A model change gets mistaken for a prompt effect | Pin the model ID, and treat a model change as a new experiment |

## Open questions

- Bedrock or a direct API?
- Which model, and what spending limit per experiment?
- Should the generator be a fourth container (simple) or a separate task (cleaner)?
- Is the deterministic checker enough for live answers, or is a judge needed (Phase 4)?
- Is metric history worth paying for (Phase 7), or are results in S3 enough?

## Possible definition of done

- [ ] `generate` runs the six questions × N runs for `prompt-a` and `prompt-b` against a pinned model.
- [ ] Every evaluation log line carries the model ID, prompt hash, runbook hash, and run ID.
- [ ] The dashboard compares the two prompt versions side by side.
- [ ] `make check` passes with recorded fixtures and no API key.
- [ ] A short write-up of the result: did `prompt-b` lower the flagged rate, and by how much?
