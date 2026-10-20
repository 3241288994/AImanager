# Focused discussion and joint design

Use for a consequential proposal or a disagreement worth resolving. For a small deterministic
question, use the relevant check directly. Keep the current coordinator responsible for delivery.

## Give enough common ground

Provide the objective, hard constraints, original material and the decision to make. Include
source locations and revisions when available. Mark assumptions and missing information.
Do not copy the whole conversation, omit a known constraint to elicit disagreement, or package
the coordinator's preferred answer as an established fact.

For consequential design, the coordinator notes a brief tentative choice and uncertainty before
reading peer advice. The collaborator offers its own proposal, key assumption and failure condition.
Neither needs to produce a full essay. Independent proposals can still share mistaken assumptions.

## Turn differences into useful work

| Difference | Useful next action |
|---|---|
| Conflicting facts | Inspect the relevant source, file, log or existing check. Use matching revisions. |
| Conflicting reasoning | Identify the disputed premise or a concrete counterexample. |
| Different tradeoffs | Apply the user's stated priorities; offer conditional choices only when the missing preference matters. |
| Complementary ideas | Construct a candidate using the useful parts, then check compatibility, complexity and constraints. |

Use only tools actually available to that call. Claude `read` currently provides Read/Glob/Grep,
not Bash; Codex `read` can use sandboxed read-only commands. Execution needs authorized `exec`
scope in a new task when the current conversation cannot perform it. API participants receive
selected content; a path or a suggested command is not evidence that they inspected or ran it.

Forward the relevant original argument and source rather than only the coordinator's paraphrase.
An opinion labelled A/B may help compare options, but it is not a blind review if prior conclusions
are included. Keep model/provider attribution in the actual job record.

## A compact follow-up

Adapt this wording; do not require the user to supply it:

> These are the differences that could change our decision: …
> For each, retain or revise your recommendation with a specific reason, or identify missing evidence.
> Can the useful parts form a better proposal? Explain the added cost and constraint fit.
> Do not force agreement or invent an objection.

New reasoning, a corrected interpretation of the user's actual requirements, or a better
construction can justify changing a view without new external evidence. Mere repetition,
deference to another model, or an unsupported inference about user preferences cannot.

## Finish proportionally

One independent contribution and one focused exchange is a default, not a mandatory sequence.
Continue for new material or a promising refinement; stop when additional discussion would
repeat positions or the remaining differences do not change the decision. If useful facts are
available, inspect them before defaulting to a conditional answer. Do not commission new research
experiments merely to close a discussion.

Deliver the proposal, the main reason to choose it, and material unresolved conditions.
Use a fresh independent review only when the decision warrants the extra call. `reply` preserves
context; `run --after` transfers a conclusion. Neither restores independence.
For a fresh artifact review, provide the artifact and original requirements without the earlier
discussion or endorsement. For an independent new proposal, omit the earlier proposals too.
