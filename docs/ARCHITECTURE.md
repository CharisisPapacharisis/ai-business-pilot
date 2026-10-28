# Architecture Evolution

This document records how AI Business Pilot grew from a local database demo
into a stateful, multi-source business analysis workflow. It explains why the
current boundaries exist and provides context for future changes. Operational
commands belong in [DEVELOPMENT.md](DEVELOPMENT.md).

## 1. Deterministic fictional business data

The project began with seeded `customers`, `products`, and `orders` tables in
DuckDB. Deterministic sample data made revenue and gross-profit questions
repeatable without exposing real company data.

The first lesson was that model-generated SQL needs a boundary independent of
the model. SQLGlot now parses each query before execution. Only one SELECT over
approved tables and functions is accepted; writes, external tables, nested
queries, and other unsupported syntax are rejected.

```text
model SQL -> SQLGlot guard -> read-only DuckDB connection
```

## 2. DuckDB became a local MCP server

Database operations were exposed through an MCP stdio server instead of being
embedded directly in an agent. This separated business-data capabilities from
model orchestration and made table discovery, schema inspection, predefined
analytics, and validated SQL independently callable.

The MCP client launches the local server as a subprocess. A directly started
stdio server therefore waits silently for protocol input; the calling adapter
owns its lifecycle.

## 3. A single LangChain analyst established tool use

The first model-backed workflow gave an Ollama-hosted instruction model the
DuckDB MCP tools. This proved that a local model could inspect schemas, produce
SQL, execute it, and explain results.

It also exposed two limits of relying on prompts alone:

- a small model can skip an intended tool or choose an overly broad one;
- exposing many tool schemas consumes context and reduces reliability.

Tool filtering and code-level validation became part of the design rather than
optional prompt advice.

## 4. Linear added a second evidence system

The project then connected to Linear's remote read-only MCP endpoint. Linear
provides initiative, proposal, decision, and status context, while DuckDB
provides measured business results.

```text
DuckDB -> actual products, sales, costs, revenue, profit
Linear -> proposals, work items, decisions, current status
```

Initially the model received raw `list_issues` and `get_issue` tools. When a
question supplied a title but no ID, the model sometimes invented an ID such
as `LIN-1234` and called `get_issue` directly. The `linear_find_issue` wrapper
now enforces this sequence in code:

```text
title or keywords -> list issues -> select real result -> get real issue ID
```

This established a general rule: mandatory tool sequences belong in code, not
only in prompts.

Unlike the seeded DuckDB dataset, Linear records live in the operator's own
workspace and are not repository fixtures. Live demonstrations therefore use
environment-configured issue titles and team names. Unit tests keep fictional
Linear payloads in code and mock the tool boundary.

## 5. Cross-system analysis required orchestration

Questions about the effect of a proposed change need evidence from both
systems. A single combined agent could answer them, but it exposed every tool
for every question and made routing difficult to inspect.

The workflow moved to LangGraph with explicit stages:

```text
START
  -> memory
  -> planner
       -> DuckDB analyst --+
       -> Linear analyst ---+-> reporter -> END
       -> combined analyst -+
```

The planner classifies the evidence required by the current question. The
selected analyst gathers evidence, and the reporter turns findings plus raw
tool results into the audience-facing answer. Only one analyst path runs per
turn.

Route normalization handles minor model formatting variations and defaults an
ambiguous response to `both`, the safer evidence-rich path. The graph still
checks the stored route before conditional routing so invalid state fails
explicitly.

## 6. Tool exposure became route-specific

The DuckDB analyst receives only table discovery, schema inspection, and
validated query tools. The Linear analyst receives only the composed
title-first lookup. The combined analyst receives both filtered sets.

This reduced prompt size, made tool provenance visible through server prefixes,
and limited accidental capabilities. It also clarified that discovering 35
Linear tools does not mean exposing all 35 to the model.

## 7. Evidence was separated from conversation history

Graph state distinguishes:

- the current question;
- planner route and plan;
- analyst findings;
- raw tool evidence and call trace;
- final answer;
- conversation history;
- retrieved long-term memories.

Analyst output is an internal synthesis of the current tool run. Evidence is
the actual tool-result content. The reporter receives both. Previous answers
can help resolve a phrase such as “that proposal,” but they are not accepted as
proof that an issue is still open or that a price remains current.

The checkpoint retains complete normalized evidence, while reporter and draft
prompts receive a bounded source-balanced projection. This preserves audit and
debugging detail without overflowing the smaller local model context window.
Evidence normalization and compaction now live in a dedicated module so the
graph nodes remain focused on orchestration.

## 8. Checkpointing added same-thread conversations

An asynchronous SQLite checkpointer made graph state durable by `thread_id`.
The same thread can pause between process invocations and can interpret
follow-up questions using recent user and assistant messages.

Every new question still traverses planner and analyst nodes. The analyst is
explicitly instructed to query required MCP sources again, preventing an old
calculation or issue status from becoming current truth merely because it is
present in history.

## 9. A persistent store added cross-thread memory

Checkpoint history is conversation-specific. A separate SQLite store now
holds explicit business preferences under a user namespace:

```text
("business_memory", user_id)
```

This permits multiple threads for one user to share conventions such as demand
scenarios, report formatting, currency display, and internal terminology.
Memory is loaded before planning and supplied as context to later stages.

The checkpointer and store deliberately use separate databases:

```text
graph_checkpoints.sqlite -> one thread's evolving graph state
business_memory.sqlite   -> durable preferences shared across threads
```

The first implementation accepts explicit memory writes only. Automatic model
extraction is deferred because it introduces duplicate, contradictory,
sensitive, and stale memories that require lifecycle management.

## 10. Human approval created a write boundary

The current Linear analyst is read-only. Before adding mutation, the project
introduced a standalone LangGraph approval workflow using `interrupt()` and a
SQLite checkpointer.

```text
issue draft
  -> approval interrupt
  -> process may stop
  -> human resumes with approve or reject
       -> approve: defensive check -> simulated action
       -> reject: finish without action
```

Unique thread IDs identify pending requests. The terminal displays the exact
action, title, and description before accepting a decision. The execute node
also verifies `approved is True`; routing alone is not treated as sufficient
authorization.

This established the approval boundary before an external write was added.

## 11. Authorized Linear writing was placed after approval

A frozen Pydantic `LinearIssueDraft` then defined the exact title, description,
team, proposed priority, supporting evidence, and unique request ID. The
workflow now follows:

```text
prepare and validate
  -> interrupt with complete draft
  -> approve or reject
  -> exact-title duplicate check
  -> runtime-discovered save_issue tool without an update ID
  -> direct get_issue verification using the returned ID
  -> exact-title fallback when direct verification is unavailable
```

The normal analyst adapter remains read-only. Write credentials and the full
Linear MCP URL are opt-in and opened only after approval. The write node maps
the approved fields onto the MCP tool's discovered schema rather than allowing
a model to generate new arguments after approval.

Execution and verification have bounded retries. Every write attempt first
searches for the unique approved title, so a retry after a successful remote
write but interrupted local response reuses the existing issue. A restart
after approval resumes the pending action without requesting a second decision.

Schema discovery confirmed that the full endpoint exposes `save_issue` rather
than `create_issue`. Omitting `id` creates an issue; supplying it updates one.
The guarded creation path constructs no `id` argument.

## 12. Analyst-generated actions joined the main graph

Integrating actions into the main graph extended planning from one decision to
two independent decisions:

```text
source = DuckDB | Linear | both
action = none | draft_issue
```

All requests first gather fresh evidence. Analysis-only requests go directly
to the reporter. Action requests pass findings and raw evidence to a structured
drafting service. That service declines to propose a duplicate when an existing
Linear initiative already addresses the finding.

```text
analyst findings
  -> issue draft decision
       -> no equivalent needed: reporter
       -> validated draft: interrupt
            -> reject: reporter
            -> approve: duplicate check -> save_issue -> verify -> reporter
```

Read and write capabilities remain separate. The analyst sees only filtered
DuckDB tools and the read-only `linear_find_issue` wrapper. Write tools are
injected only into the action nodes and receive the frozen approved draft, not
arguments regenerated by a model after approval. The action result is stored
under the same checkpoint thread as the original analysis.

## 13. Testing architecture

The project originally relied on executable integration scripts. It now keeps
deterministic safety and routing checks in pytest while retaining scripts for
real Ollama, MCP, and Linear behavior. This provides a fast local feedback loop
without pretending mocked tests validate external integrations. The test
inventory and commands live in [DEVELOPMENT.md](DEVELOPMENT.md).

## 14. Reliability controls became explicit modules

Repeated live runs exposed failure modes that prompts alone could not prevent:
exact tool retries, loops, false absence claims after a query used the wrong
column, context overflow, and arithmetic invented in prose.

The current design uses several small boundaries:

```text
agent_safety.py -> duplicate/empty-result middleware and call limits
evidence.py     -> normalize full evidence and build compact model context
SQL guard       -> reject unsupported or mutating SQL before DuckDB
prompts         -> require final calculations to appear in tool evidence
pytest          -> lock down deterministic boundary behavior
```

These controls do not add more autonomous agents. Middleware wraps calls made
by the selected analyst and may return a structured error instead of accepting
an unsafe or unsupported result. The complete evidence remains checkpointed;
only the reporter-facing copy is compacted.

## 15. Streamlit added a durable presentation layer

The local application is intentionally a thin client over the same graph used
by the scripts. It adds conversation selection, chat rendering, activity
visibility, and approval buttons without moving business logic into the UI.

```text
browser -> Streamlit -> existing LangGraph
                        |-- read MCP tools during analysis
                        |-- saved interrupt during approval
                        `-- write MCP tools only after approval
```

Streamlit reruns the application script after interactions, while MCP clients
and asynchronous SQLite connections have shorter, event-loop-sensitive
lifetimes. The runtime therefore opens them for one graph invocation and closes
them before returning. Ordinary UI reruns read the checkpoint without opening
MCP connections.

The UI thread catalog is an index, not a second source of conversation truth:

```text
ui_threads.sqlite         -> sidebar title, ordering, display status
graph_checkpoints.sqlite  -> messages, route, evidence, interrupt, action result
business_memory.sqlite    -> explicit knowledge shared across threads
```

Pending approvals survive browser refreshes and application restarts because
the interrupt and exact validated draft are checkpointed. Approve and Reject
resume that interrupt; Streamlit does not duplicate the approval workflow.

## Current architecture

```text
User in browser
    |
    v
Streamlit chat, thread selector, activity, approval
    |
    v
LangGraph runtime context -------------------------+
    |                                              |
    +-- user_id -> SQLite long-term memory store --+
    |
    v
Memory node -> Planner (source + action)
                  |
          +-------+--------+
          |       |        |
       DuckDB   Linear   Combined
          |       |        |
          +-------+--------+
                  |
          findings + evidence
                  |
          +-------+------------------+
          |                          |
      Reporter                 Issue drafting
                                     |
                                  approval
                               /             \
                         reject               approved write
                               \             /
                                  Reporter
                  |
             Final answer

Thread state <-> SQLite checkpointer keyed by thread_id

DuckDB analyst -> stdio MCP -> SQL guard -> read-only DuckDB
Linear analyst -> HTTPS MCP -> title-first read-only issue lookup
```

## Next architectural stages

### Later production concerns

- production API and deployment of the local user interface;
- authenticated user and organization identity;
- memory review, update, deletion, retention, and sensitive-data policy;
- semantic memory retrieval when the collection becomes large;
- durable audit trail for approvals and writes;
- observability, retries, timeouts, and concurrency controls;
- stronger evaluation of routing, tool use, and answer grounding;
- deployment security review before any non-local use.

## Design principles retained

- Use LLM judgment for language interpretation; use code for guarantees.
- Treat current source-system evidence as authoritative over history or memory.
- Expose the smallest tool set needed for each route.
- Keep external writes behind explicit, reviewable human approval.
- A polished answer is not proof of correct execution; inspect route, tools,
  arguments, and evidence.
- Keep fast deterministic tests separate from live model and service tests.
