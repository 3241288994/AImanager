---
name: multi-model-collaboration
description: Coordinate AImanager Ensemble (合奏) collaboration through ai-collab when the user names a model or requests joint design, independent review, analysis, or workspace work. A model-only message selects a collaborator for the active task. Comparisons and incidental mentions do not request a call.
---

# AImanager Ensemble · 合奏

The current coordinating agent owns the final answer, regardless of its harness.
Use the installed `ai-collab`; model aliases and accounts come from personal configuration.
If no task exists, ask what the selected collaborator should work on.

## Prepare and call

- Resolve the requested name with `ai-collab resolve NAME`; preserve its provider and version.
- Run `ai-collab doctor` on first use or after connection trouble. Configuration health is not a successful model call.
- Give a concrete objective, necessary material, permitted operations and expected deliverable.
  Reuse information already supplied; do not repeat approval questions for authorized work.
- Identify the immediate purpose: develop a proposal together, review an existing artifact,
  or settle a specific decision. Infer it from the task; these are not mandatory phases.
- Preserve the user's constraints and separate established facts from assumptions and unknowns.
  Include relevant file locations/versions and actual tool access when they affect the decision.
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

- For consequential decisions, note the coordinator's tentative choice and uncertainty before
  reading the collaborator's answer. Invite an independent proposal from the same original
  task and evidence. For artifact review, include the artifact without an endorsement of it.
- Focus follow-up on differences that could change the decision, usually no more than three.
  Check factual disputes against sources; examine reasoning with counterexamples; resolve
  tradeoffs against the user's stated priorities. Do not turn a model's inferred preference
  into a user requirement. Seek clarification only when a material choice remains unknown.
- Invite constructive combinations as well as criticism. Ask what to retain, revise or combine,
  and why the resulting proposal meets the constraints; agreement is not the success criterion.
- When a recommendation changes, identify the specific source, reasoning correction, clarified
  requirement or better construction behind it. A model's confidence or agreement is not evidence.
- Use `reply` to supply missing material and respond to focused differences. A request for
  context does not authorize unrelated reads or commands. Read the
  [discussion guide](references/discussion.md) for substantial joint design or unresolved disagreements.
- `reply` continues a successful persisted conversation with the same identity and access.
  `run --after JOB_ID` passes its result text into a new call; it does not clone native context.
  It is not a blind review. If a consequential decision needs a fresh independent check, use
  a new `run` with the original task and evidence, excluding prior discussion and endorsements.
  Include the artifact when reviewing it; omit prior proposals when requesting a fresh solution.
- Background jobs let the coordinator continue other work. Wait at most 60 seconds per call
  and give progress updates. Inspect `status` before repeating a submission.
- Read results before adopting them. Distinguish conclusions, artifact locations, performed
  checks and unresolved questions. Verify according to the task, not a compulsory audit pipeline.
- A useful default is independent input followed, if needed, by one focused exchange.
  Continue when new evidence, a useful construction or a material unresolved issue warrants it;
  stop when the next exchange would only repeat positions. This is not a fixed round quota.
- Deliver the chosen proposal and its basis. Include meaningful unresolved differences or
  rejected alternatives only when they affect the decision; no compulsory ledger or empty fields.
  If progress requires unavailable facts or preferences, name the gap rather than manufacture consensus.
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
