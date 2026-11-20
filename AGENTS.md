# AGENTS.md — working on `ple-forge`

This repository is an entry for **Physical-Engineering's Last Exam** on Kaggle
(https://www.kaggle.com/competitions/physical-engineerings-last-exam). Read
`README.md` and the competition repo's `kit/README.md` before changing the
harness.

## Entry contract

```
submission.yaml      name, model_api, install, serve, optional env
serve.py             WebSocket server on $PORT
harness.py           triage → execute → audit → fix → close
triage.py            deliverable extraction, brief, prompts
preflight_task.py    stdlib inventory run inside the task container
check_task.py        stdlib deliverable checker run inside the task container
scaffold.py          last-resort draft at a still-missing path
task-tools.ts        Pi's read/write/edit/bash routed to the task container
taskbridge.py        competition protocol
artifacts/           dev-set outputs, written only by eval/run.py
```

- One commit of a GitHub repo. `artifacts/` and the harness must be in the same
  commit.
- `model_api` must be a `google-cloud/<id>` model. The entry contains no API
  keys and no web access.
- 2 CPUs / 4 GB / 6 hours per task. The serve container must listen within
  120 s. The task container has no network.

## Local checks (Linux/WSL)

```bash
cd /root/ple-work/ple
export MODEL_PROXY_URL=http://localhost:4001
export MODEL_PROXY_KEY="$(cat /root/ple-work/model-proxy/proxy.key)"
uv run python -m kit check /root/ple-work/ple-forge --cancel-test
uv run python eval/run.py /root/ple-work/ple-forge --tasks <id> --trials 1
uv run python -m kit artifacts /root/ple-work/ple-forge
```

`kit check` must end with `ready to submit` after `artifacts/` is generated and
committed. The model proxy, HF token, and Docker live in WSL; see the project
`REFERENCE.md` in the vault.

## Harness rules

1. The task instruction is authoritative. The auto-generated brief is a
   candidate list; correct it in `/tmp/ple-forge/plan.md`.
2. Create a skeleton at every required deliverable path early. Never leave a
   required path missing.
3. Read drawings and scanned pages with the image-capable read tool; do not
   guess what a drawing shows.
4. Compute with code; re-derive key numbers; check units, dimensions, sums, and
   boundary conditions.
5. For archives, create every required member at the archive root; verify the
   zip. For document-store or case-tracking deliverables, use the MCP tools.
6. A reply without a tool call ends the task. Do not send progress notes.
7. The auditor is independent: re-read the governing clauses and validate
   against the owner templates/schemas. The fixer addresses only material gaps.
8. The deterministic checker and scaffold are the last line of defense. They
   never invent engineering answers; they prevent a missing-file zero.

## Fair play

- Never hard-code task answers or fingerprint a specific task.
- Never read `artifacts/`, the dev-set graders, or reference answers at build or
  run time.
- Do not bypass egress, use web search, or inspect grading scripts.
- Do not commit secrets (`proxy.key`, `local.env`, HF/Kaggle tokens).
- `artifacts/` must be exported by `eval/run.py` from the submitted harness and
  the declared `model_api`.

## Dev workflow

Edit the vault copy at
`01 Projects/Physical-Engineering Last Exam/work/entry`, sync to WSL:

```bash
rsync -a --exclude artifacts --exclude .git \
  "/mnt/c/Obsidian Vault/01 Projects/Physical-Engineering Last Exam/work/entry/" \
  /root/ple-work/ple-forge/
```

Then run the kit/eval. Commit from `/root/ple-work/ple-forge` so the manifest
hashes match the harness that produced `artifacts/`.
