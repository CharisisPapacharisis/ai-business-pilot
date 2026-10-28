# Manual Acceptance Guide

Use this guide after changing prompts, tools, routing, persistence, memory, or
the Streamlit runtime. It complements pytest: these checks exercise the real
local model and configured MCP services, so exact prose may vary.

## Before you start

1. Start Ollama and launch the UI with `make ui`.
2. Confirm the seeded DuckDB data and `.env` configuration are current.
3. Create a **new UI conversation**. Do not reuse an old checkpoint for this
   sequence.
4. For every response, inspect **Latest run activity** as well as the prose.

The example names below assume `DEMO_PRODUCT_NAME=Headphones` and a matching
Linear pricing initiative configured by `LINEAR_DEMO_ISSUE_TITLE`. Substitute
the names from your own fixture when needed.

## Serial UI checks

### 1. DuckDB entity lookup

Ask:

> Does Headphones exist in the product data? What are its category, price,
> and unit cost?

Verifies:

- route is `duckdb` and action is `none`;
- the analyst identifies the product by the correct column rather than
  treating its name as a category;
- a zero-row first attempt is corrected instead of becoming a false absence
  claim;
- the answer is supported by a successful DuckDB result.

### 2. Genuine missing entity

Ask:

> Does a product named Noise-Cancelling Speaker exist in the product data?

Verifies:

- the empty-result guard causes identifier/distinct-value verification;
- the final absence claim is based on a corrected search, not one empty query;
- the agent stops within its model and tool-call limits.

### 3. Linear-only retrieval

Ask:

> What is the current status and proposed change in the configured pricing
> initiative?

Use the actual initiative title if the model cannot resolve “configured
pricing initiative.”

Verifies:

- route is `linear` and action is `none`;
- `linear_find_issue` searches before retrieving a real issue ID;
- no DuckDB calls are made for a status/content-only question;
- current status and proposal details come from Linear evidence.

### 4. Cross-system numerical grounding

Ask:

> Based on historical sales, how would the proposed price change affect
> revenue and gross profit under the demand scenarios described in the pricing
> initiative?

Verifies:

- route is `both` and action is `none`;
- both Linear and DuckDB tools are called;
- proposal assumptions come from Linear while measured inputs come from
  DuckDB;
- a final DuckDB query returns the calculated scenario outputs;
- the reporter copies verified figures instead of doing new arithmetic.

For the repository's default fictional fixture, the expected Headphones gross
profits are baseline `$2,800`, no demand reduction `$3,100`, 5% reduction
`$2,945`, and 10% reduction `$2,790`.

### 5. Same-thread follow-up

In the same conversation, ask:

> Which scenario has the highest gross profit, and how much higher is it than
> the baseline?

Verifies:

- recent history resolves what “scenario” and “baseline” refer to;
- required source facts are retrieved again rather than trusted from history;
- the new difference is calculated by DuckDB and appears in evidence.

### 6. Draft and reject

Ask:

> Check whether an issue already covers post-launch monitoring of this pricing
> change. If not, propose a Linear issue for monitoring demand, revenue, and
> gross profit.

When a draft appears, refresh the browser once, return to the conversation,
and click **Reject**.

Verifies:

- route is `both` and explicit issue intent selects `draft_issue`;
- existing Linear work is checked before proposing a duplicate;
- the validated draft and pending interrupt survive a rerun;
- rejection creates no issue and is recorded in the same thread.

If the configured workspace already contains an equivalent issue, declining
to draft is the correct result. Use a clearly different fictional action to
exercise the rejection path.

### 7. Draft and approve

Repeat with a distinct, clearly labelled demo action. Review every field, then
click **Approve**.

Verifies:

- the approved fields are exactly the fields sent to Linear;
- write credentials/tools are opened only for the approved resume;
- the created issue is verified and saved with status `created_verified`;
- retry/refresh does not create a second equivalent issue.

Use a disposable Linear team or delete the demo issue afterward if desired.

### 8. Persistence and memory

Copy the approved workflow's thread ID and run:

```powershell
uv run python scripts/verify_issue_persistence.py checkpoint THREAD_ID
uv run python scripts/verify_issue_persistence.py conversation THREAD_ID
uv run python scripts/verify_issue_persistence.py memory THREAD_ID
```

These are three separate claims:

| Check | What it proves |
|---|---|
| `checkpoint` | The workflow state, approval, and created issue survived. |
| `conversation` | The same thread can refer to the outcome and re-check current source data. |
| `memory` | An explicitly recorded immutable event can be retrieved by another thread for the same user. |

Long-term memory is not a cache of current prices, calculations, or issue
statuses. Those facts must still be retrieved from DuckDB or Linear.

## Pass criteria

A run passes only when the route, action, tool arguments, evidence, interrupt,
and persisted outcome agree with the answer. Fluent prose alone is not an
acceptance signal. Record unexpected model variability separately from
deterministic code failures; `scripts/compare_graph_entrypoints.py` can compare
an analysis-only prompt through the direct graph and UI runtime.
