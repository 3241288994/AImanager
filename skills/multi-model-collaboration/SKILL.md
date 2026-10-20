---
name: multi-model-collaboration
description: Collaborate with a user-named external model through ai-collab, including opus5.5/Opus 5.5/Claude Code and gemini4/Gemini 4/Argon. Use for delegated analysis, code proposals, independent review, research criticism, or when a model-only message selects a collaborator for the active task. Model comparisons or incidental mentions alone do not request a model call.
---

# Named-model collaboration

Use the installed `ai-collab` command from any project. The coordinating Codex
keeps responsibility for implementation, evidence checks and the final answer.
The user wants a model name to be sufficient routing information: **“opus5.5”**
means collaborate with that Claude Code model; **“gemini4”** means the configured
Gemini web model. A model-only message steers the current task. If no task exists,
ask what the user wants to work on.

## Resolve and prepare

1. Check `command -v ai-collab`, then `ai-collab --json resolve 'opus5.5'`
   (substitute the user's name). The personal config is authoritative. Do not
   replace an explicit version with a default or a different provider.
2. On first use in a session, or after a connection failure, run
   `ai-collab --json doctor`. This checks configuration and discovery, **not**
   successful inference. `models --refresh` queries the Gemini proxy catalog
   and Claude's partial official CLI cache.
3. Use the active project's instructions and identify a concrete, bounded task:
   expected output, supplied evidence, constraints and acceptance criteria.
   A collaboration request authorizes the necessary model calls for that task;
   do not ask for confirmation again merely because another model is involved.
4. For Claude Code development/review, prefer `--workspace /absolute/project`
   to let it inspect the relevant project directly. Use the active task's specific
   project directory, not the whole personal workspace. Multiple roots may be
   granted explicitly (at most four). The path must exist on the CLI host.
   For a specific text bundle, attach relevant UTF-8 files with `--file`. For PDF, Office or remote/local
   workspace material, first use the existing LabContext readers and supply the
   needed extracted evidence. Paths alone are not readable by the Gemini model.
   Preserve source locations/hashes. Keep unrelated private research corpora,
   credentials and raw datasets out of context bundles.

## Delegate and verify

```bash
ai-collab --json run --model opus5.5 --role reviewer \
  --prompt-file /absolute/path/review-task.txt --file /absolute/path/change.diff
ai-collab --json run --model opus5.5 --role reviewer \
  --workspace /absolute/project --prompt "Inspect the login flow and identify reproducible defects."
ai-collab --json run --model gemini4 --role researcher \
  --prompt-file /absolute/path/research-question.txt --file /absolute/path/evidence.txt
ai-collab --json wait JOB_ID --timeout 30
ai-collab --json result JOB_ID
```

`run` returns a durable job ID. Poll using `wait` or `status`, and keep the user
informed during long calls. `jobs` lists recent work; `cancel JOB_ID` stops local
execution. A timeout/cancellation does not prove that the upstream request was
never processed. There is no automatic retry or provider fallback.

Without `--workspace`, both providers receive text context with no file/shell
tools. With `--workspace`, Claude Code gets only **Read/Glob/Grep**, under native
`--restricted` directory boundaries and `--safe-mode`; hooks, external MCP,
shell and write tools remain disabled. Known credential paths are denied.
The result includes read/search attempts and their reported success/failure,
plus workspace identity and starting Git revision. This is a live read, not an
immutable filesystem snapshot. Gemini continues using text through the web proxy.
Ask collaborators for analysis, concrete patches, checks or counterexamples.
Codex applies proposed changes and executes tests.

If both models were requested, independent analysis can run concurrently.
Give each the same relevant evidence before sharing their opinions. Use
`--after JOB_ID` to include a successful prior result for a focused follow-up.
Do not replace independent review with repeated requests for agreement.

Read results before accepting them. For development, reproduce reported defects
and run appropriate tests. For research, connect claims to source passages,
alternative explanations and experiments; use the existing research skills.
Report disagreements and unresolved findings. Attribute assistance using the
recorded provider/model metadata; model self-identification is not verification.
Never say a collaborator tested code when it only proposed a test.

## Model upgrades and failures

Model versions live in `~/.config/ai-collab/config.json`, not this workflow.
Unknown names fail explicitly. For a newly requested version, discover its actual
ID from the provider or official documentation, verify CLI compatibility and
register it with `alias set`. Run a small real task before claiming availability.
`alias default` changes unversioned `claude`/`gemini` preferences; existing
versioned names remain fixed unless the user requests replacement.

Use `ai-collab alias --help` for registration, `request --provider gemini-web
--path /models` for the read-only raw endpoint, and `ai-collab --help` for the
command contract. Failed jobs retain a reason code and private local artifacts.
Explain an unavailable requested model and continue independent useful work;
do not silently substitute another model, account or API billing channel.
