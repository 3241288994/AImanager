# CLI details

`run` defaults to text without a workspace and read with a workspace. `--access exec`
requires a specific prepared directory and a supported sandbox; it never implies unrestricted mode.
Codex currently supports read/exec workspaces; Claude also supports tool-free text.
Read mode does not authorize edits; files remain live: Codex may use OS-sandboxed read-only shell commands.

`reply JOB` accepts prompt/files/timeout/wait only. Use the newest successful, resumable job.
It inherits provider, model, native account, workspace, access and effective cwd. A busy,
failed, legacy non-persistent or incompatible conversation fails explicitly. Start a new
`run` with selected context when needed; no implicit fallback. API history is bounded.
A failed/cancelled continuation freezes that conversation because native context may have
partially changed. Inspect the workspace/logs and explicitly start a new task with selected material.

`--cwd` records the requesting context; `effectiveCwd` is where the collaborator runs.
Prepare Git worktrees with git or use task-specific output directories. Only the coordinator
merges results; ai-collab never creates, merges or deletes worktrees automatically.
Sandbox dependencies and local command/file limits are reported honestly. Native project
instructions are task context, while hooks and arbitrary external MCP tools remain disabled.

`jobs --workspace /project` filters associated tasks. `status/result/cancel` use returned IDs.
`--host ALIAS` selects a configured SSH host. Prompts travel over structured stdin; files are
explicitly attached. A remote path is not readable on the local host. Remote job references
include their host and must be copied exactly. Independent experiments need their own job handle.

For model upgrades use `models --refresh`, `alias set` and `alias default`. Explicit versioned
names keep their binding. Unknown names fail. Discover capabilities and validate a small call
before claiming a new provider/model works. Never silently replace subscription OAuth with API keys.

MCP uses the same operations behind an explicit model/root policy. CLI access does not imply
web access. Credentials are referenced from existing stores, never attached to prompts.
