---
name: multi-model-collaboration
description: Delegate work to a user-named model through ai-collab, or coordinate an explicitly requested independent review, analysis, or workspace task. A model-only message selects a collaborator for the active task. Model comparisons and incidental mentions do not request a call.
---

# Lightweight model collaboration

The current coordinating agent owns the final answer, regardless of its harness.
Use the installed `ai-collab`; model aliases and accounts come from personal configuration.
If no task exists, ask what the selected collaborator should work on.

## Prepare and call

- Resolve the requested name with `ai-collab resolve NAME`; preserve its provider and version.
- Run `ai-collab doctor` on first use or after connection trouble. Configuration health is not a successful model call.
- Give a concrete objective, necessary material, permitted operations and expected deliverable.
  Reuse information already supplied; do not repeat approval questions for authorized work.
- Use one collaborator for a useful subtask. Parallelize only independent work and keep one coordinator.
- Choose the supported access mode: `text` for supplied content, `read` for workspace inspection,
  `exec` only for authorized edits or commands in a prepared workspace.
  A role such as reviewer never grants execution permission.
- CLI workspaces are real directories on the execution host. API models need explicit file content.
  Extract PDF/Office material with existing LabContext readers; include source locations.
- Supply relevant domain requirements, not the complete conversation or every installed skill.

```bash
ai-collab run --model NAME --workspace /project --prompt-file task.txt
ai-collab run --model NAME --access exec --workspace /prepared-task --prompt-file task.txt
ai-collab run --model NAME --file selected-evidence.txt --prompt-file task.txt
ai-collab wait JOB_ID --timeout 30
ai-collab result JOB_ID
ai-collab reply JOB_ID --prompt-file followup.txt
```

## Discuss and deliver

- For independent review, first provide original evidence without the coordinator's conclusion.
- Ask about concrete disagreements; supply missing evidence through `reply` when useful.
  A request for context is advice, not authority to execute a command or read unrelated files.
- `reply` continues a successful persisted conversation with the same identity and access.
  `run --after JOB_ID` passes its result text into a new call; it does not clone native context.
- Background jobs let the coordinator continue other work. Wait at most 60 seconds per call
  and give progress updates. Inspect `status` before repeating a submission.
- Read results before adopting them. Distinguish conclusions, artifact locations, performed
  checks and unresolved questions. Verify according to the task, not a compulsory audit pipeline.
- Stop when the requested result is useful, further progress needs unavailable input, or the
  agreed scope is reached. Do not repeatedly ask models to agree.
- Never silently change model, provider or billing channel. Failed/cancelled jobs do not authorize
  retries of side effects. A CLI cancellation may leave an independently launched experiment running.
- Attribute assistance using recorded metadata, noting when identity is only a request binding.

## Optional guidance

Read only what the task needs:
- [CLI details](references/cli.md): continuation errors, execution boundaries, remote calls, model upgrades.
- [Independent review](recipes/review.md): a second opinion on an existing artifact.
- [Plan and execute](recipes/plan-execute.md): analytical advice followed by native execution.
- [Research discussion](recipes/research.md): evidence, alternatives and missing information.
- [Writing](recipes/writing.md): drafting and revising from supplied material.

For handoff, stop new scheduling by the old coordinator and record the objective, completed work,
active job IDs, key files and next step. The successor reads jobs and results; native chats are not
transferred between vendors.
