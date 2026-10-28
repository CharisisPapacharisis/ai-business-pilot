# Development Guide

This is the practical guide for returning to AI Business Pilot after a long
break. The README describes the project and its goals; this document explains
how to run, test, debug, and extend it. The ordered live verification prompts
are kept separately in [ACCEPTANCE.md](ACCEPTANCE.md), and design history is in
[ARCHITECTURE.md](ARCHITECTURE.md).

Run commands from the repository root unless stated otherwise.

## 1. Restore the environment

Install the Python environment and ensure the local model is available:

```powershell
uv sync
ollama pull qwen3:4b-instruct
ollama list
```

If Ollama is not already running as a service, leave this running in another
terminal:

```powershell
ollama serve
```

Create the deterministic fictional business database:

```powershell
uv run python scripts/seed_database.py
```

The placeholder-only `.env.example` should be committed. Copy it to the
ignored project-root `.env`, then add your credentials:

```dotenv
LINEAR_API_KEY=lin_api_replace_with_your_key
LINEAR_READ_MCP_URL=https://mcp.linear.app/mcp/readonly
LINEAR_WRITE_API_KEY=replace_with_write_credential
LINEAR_WRITE_MCP_URL=https://mcp.linear.app/mcp
LINEAR_DEFAULT_TEAM=Your Linear team name
LINEAR_DEMO_ISSUE_TITLE=Your pricing initiative title
DEMO_PRODUCT_NAME=Headphones
```

The read URL is optional and defaults to Linear's read-only MCP endpoint. Write
credentials are loaded only by the explicit approval workflow; normal analysts
do not receive the write server's tools.

### Portable and workspace-specific fixtures

The fictional DuckDB fixture is portable. `scripts/seed_database.py` contains
the products, customers, and orders, so every clone can recreate the same
database and deterministic pytest results.

Linear content is workspace-specific and is not stored in Git. Issue IDs,
initiative titles, team names, statuses, and descriptions in one developer's
workspace do not appear in another workspace automatically. Live scripts read
`LINEAR_DEMO_ISSUE_TITLE` and `LINEAR_DEFAULT_TEAM` so they can target an
equivalent test issue and team without code edits. `DEMO_PRODUCT_NAME` links
that issue to a product in the seeded DuckDB fixture.

The default values describe the maintainer's fictional local fixture. To run
the pricing examples unchanged, create an equivalent Linear issue whose
description supplies a proposed percentage change and demand scenarios, or
configure the variables for a suitable issue already in your workspace. Unit
tests use isolated fictional records and do not require that live issue.

## 2. Mental model

```text
question
  -> memory node: load user-scoped conventions, if a store is configured
  -> planner: independently choose sources and action intent
  -> selected analyst: call source tools and collect evidence
  -> reporter, or validated issue draft -> approval -> guarded write -> reporter
```

The major code boundaries are:

- `mcp_servers/duckdb_server.py`: local read-only MCP tools.
- `services/sql_guard.py`: deterministic validation before SQL execution.
- `src/ai_business_pilot/mcp_client.py`: DuckDB and Linear MCP configuration.
- `src/ai_business_pilot/mcp_tools.py`: safer composed tools, including
  title-first Linear issue lookup.
- `src/ai_business_pilot/evidence.py`: tool-content normalization and the
  compact evidence view used in model prompts.
- `src/ai_business_pilot/graph/agent_safety.py`: reusable analyst middleware
  and execution limits.
- `src/ai_business_pilot/graph/`: state, routing, nodes, and graph assembly.
- `src/ai_business_pilot/memory.py`: explicit, user-scoped long-term memory.
- `src/ai_business_pilot/ui/`: operation lifecycle and conversation catalog.
- `streamlit_app.py`: thin presentation layer over the existing graph.
- `scripts/`: seed commands and manual integration demonstrations.
- `tests/`: fast automated pytest coverage without Ollama or Linear.

The MCP adapter owns the server connections. Keep it open around tool
discovery and the entire graph invocation:

```python
async with adapter:
    tools = await adapter.list_tools()
    graph = build_graph(tools)
    result = await graph.ainvoke({"question": question})
```

The local stdio DuckDB server is started by the adapter. It does not need to
be started separately before a client or graph test. Running
`python -m mcp_servers.duckdb_server` directly appears idle because it is
waiting for MCP messages on standard input.

## 3. Testing strategy

The project needs both automated tests and manual integration tests. They
answer different questions.

### Automated pytest suite

Run:

```powershell
uv run pytest -q
```

These tests must be deterministic and must not require Ollama, Linear, network
access, or a live MCP process. They cover:

- allowed and rejected SQL syntax;
- route normalization and invalid stored routes;
- title-first Linear lookup with mocked tools;
- user memory namespacing and structured values;
- human approval pause, approve/reject resume, and execution guard;
- seeded DuckDB aggregates when the local demo database is present.

When changing pure Python logic, add or update pytest tests first. Mock the MCP
tool boundary instead of calling remote services.

### Manual integration scripts

Scripts under `scripts/` exercise real adapters, MCP servers, Ollama, or
Linear. They can take minutes and may depend on local or external state, so
they are not part of pytest.

| Script | Purpose | Dependencies |
|---|---|---|
| `check_mcp.py` | Check DuckDB, Linear read, or Linear write connectivity | Depends on selected source |
| `check_numerical_grounding.py` | Verify scenario results occur in DuckDB evidence and the final answer | Both MCPs, Ollama |
| `compare_graph_entrypoints.py` | Run one analysis prompt directly and through the UI runtime for A/B diagnosis | Both MCPs, Ollama, SQLite |
| `check_graph.py` | Full planner/analyst/reporter workflow | Both MCPs, Ollama |
| `demo_thread_checkpointing.py` | Two turns in one checkpointed thread | Both MCPs, Ollama |
| `demo_long_term_memory.py` | User memory reused by another thread | Store, both MCPs, Ollama |
| `check_approval_workflow.py` | Validate, pause, approve/reject, create, verify | SQLite; Linear only after approval |
| `check_issue_workflow.py` | Full analysis, conditional draft, approval, and write | DuckDB, Linear, Ollama, SQLite |
| `verify_issue_persistence.py` | Verify checkpoint, same-thread follow-up, or explicit cross-thread recall | Varies by command |

A convincing final answer is not sufficient. For agent tests, verify the
selected route, exact tool calls, arguments, retrieved evidence, and whether
the final answer is actually supported by that evidence.

When behavior appears to differ after a UI change, compare the same
analysis-only prompt through both entrypoints:

```powershell
uv run python scripts/compare_graph_entrypoints.py "YOUR EXACT QUESTION"
```

The utility uses the same tools, long-term-memory identity, and model, then
prints both routes, action decisions, tool calls, findings, and answers. Model
generation can still vary between the two runs, but the trace distinguishes
entrypoint differences from planner or analyst variability. Do not use an
action request here because the direct path intentionally has no approval
checkpointer.

## 4. Quality commands

```powershell
uv run pytest -q
uv run pytest tests/test_sql_guard.py -v
uv run pytest tests/test_approval.py -v

uv run ruff check .
uv run ruff check . --fix
uv run ruff format .
uv run ruff format --check .

make test
make lint
make check
```

`make check` runs lint, formatting validation, and pytest. The Makefile stays
small; run individual demonstration scripts directly with `uv run python`.

## 5. Seeded data and MCP development

Recreate the fictional DuckDB database:

```powershell
uv run python scripts/seed_database.py
```

Inspect the MCP server interactively:

```powershell
uv run mcp dev mcp_servers/duckdb_server.py
```

Run the local MCP smoke test:

```powershell
uv run python scripts/check_mcp.py duckdb
```

Generated SQL is accepted only when `services/sql_guard.py` permits it. The
current guard supports one SELECT statement against `customers`, `products`,
and `orders`, with an explicit function allowlist. It intentionally rejects
CTEs, subqueries, UNION, writes, qualified external tables, and unknown
functions. Extend the guard and its tests together.

Query failures are returned to the analyst as structured error details so it
can correct its arguments. An exact repeat of the same tool name and arguments
is blocked, while a revised query remains allowed. Each analyst run also has
bounded model calls, tool calls, and graph recursion; these controls prevent a
small local model from spending many minutes repeating an unsuccessful plan.

### Analyst guardrails in plain language

The safeguards are code-level controls around each LangChain agent, not extra
agents and not hidden model reasoning:

| Safeguard | Trigger | Result |
|---|---|---|
| Duplicate-call guard | Same tool and same arguments are attempted again | Returns a tool error and asks for changed arguments. |
| Empty-result guard | A DuckDB analytical query returns zero rows | Marks the result unverified and requires an identifier check. |
| Tool-call limit | One analyst reaches 10 tool calls | Ends that analyst run. |
| Model-call limit | One analyst reaches 8 model calls | Ends that analyst run. |
| Graph recursion limits | Internal or outer graph exceeds its step ceiling | Raises an explicit error instead of looping forever. |

Middleware means “logic wrapped around a tool or model call.” The duplicate
and empty-result functions can inspect or replace a tool result before it is
returned to the agent. Their order is defined in `analyst_middleware()` and is
covered by `tests/test_agent_safety.py`.

A zero-row analytical query is marked `UNVERIFIED_EMPTY_RESULT` and returned
as an error rather than accepted as proof that an entity is absent. The analyst
must inspect identifiers or distinct values and retry with changed arguments.
If the latest compact evidence still contains that marker, issue drafting is
blocked before the drafting model runs.

Full normalized tool evidence is retained in graph state for inspection. The
reporter and issue drafter receive a bounded, source-balanced view containing
the latest Linear result and final DuckDB calculation. This removes MCP wrapper
metadata and prevents raw schemas or issue metadata from overflowing the local
model context window without weakening the saved audit evidence.

The related state names are intentionally different: `evidence` is the full
saved trace, while `reporter_evidence` is the compact prompt-sized projection.
Compaction changes what the model sees, not what the checkpoint preserves.

The model must not perform derived arithmetic in its prose. For numerical
questions, the analyst runs a final DuckDB verification query containing the
inputs, assumptions, and requested outputs together. The reporter may format
those values but must not calculate, adjust, or round new ones. Run the live
pricing regression after changing analyst prompts, tools, or model versions:

```powershell
uv run python scripts/check_numerical_grounding.py
```

This is intentionally a live evaluation rather than pytest: it requires
Ollama, both MCP connections, and a configured Linear fixture with assumptions
matching the expected scenario values. The deterministic pytest suite
separately preserves the arithmetic over seeded data.

## 6. Linear development

Start with discovery:

```powershell
uv run python scripts/check_mcp.py linear-read
```

The graph does not expose raw `list_issues` and `get_issue` tools to the model.
`linear_find_issue` searches by title or keywords, resolves a real ID, and only
then retrieves the issue. This code-level sequence prevents a small model from
inventing plausible IDs such as `LIN-1234`.

Keep server prefixes such as `linear_` and `duckdb_` when several MCP servers
share an agent. Prefixes make tool provenance and integration traces clear.

Linear remains read-only in the analyst workflow. The separate write adapter is
used only after the approval boundary described below.

## 7. Graph routing and evidence

The planner uses conversation history only to understand follow-up references.
It makes two independent decisions. The source decision chooses:

- `duckdb` for measured sales, price, cost, revenue, or profit data;
- `linear` for issue status, proposal contents, and decisions;
- `both` when current operational data and proposal context are both needed.

The action decision is `none` for analysis-only requests or `draft_issue` when
the user asks to propose, prepare, draft, or create an issue. Action intent does
not authorize a write; it only enables drafting after fresh analysis.

The analyst always performs fresh MCP retrieval. Conversation history and
long-term memory are context, not authoritative evidence. Current issue status,
prices, sales, and calculations must be re-read from their source systems.

The reporter receives the current question, selected route, analyst findings,
and current tool evidence. It should synthesize rather than repeat the analyst
verbatim, although small local models may still produce overlapping text.

## 8. Persistence and memory

Checkpointing and long-term memory are separate:

| Mechanism | Scope | Database |
|---|---|---|
| Checkpointer | One conversation `thread_id` | `graph_checkpoints.sqlite` |
| Store | Many threads for one `user_id` | `business_memory.sqlite` |

Run the same-thread example:

```powershell
uv run python scripts/demo_thread_checkpointing.py
```

Seed fictional development memories:

```powershell
uv run python scripts/seed_business_memory.py
```

Run the cross-thread example:

```powershell
uv run python scripts/demo_long_term_memory.py
```

Store durable preferences, reporting conventions, approved decision rules, and
internal terminology. Do not store changing issue statuses, prices, costs,
sales totals, or previous calculations as current truth.

SQLite may create `-wal` and `-shm` sidecar files while a database uses
write-ahead logging. They belong to the main SQLite file and should not be
opened or deleted independently while the application is running.

## 9. Human approval workflow

The approval script demonstrates the pause/resume boundary and guarded write
path. Start a request:

```powershell
uv run python scripts/check_approval_workflow.py start
```

Resume the latest paused request and decide interactively:

```powershell
uv run python scripts/check_approval_workflow.py resume
```

The terminal shows the complete validated `LinearIssueDraft` before accepting
`y` or `n`. Rejection makes no network write. Approval connects the opt-in
write MCP endpoint, checks for an existing exact demo title, invokes
`save_issue` without an `id` to create, and verifies the returned issue through
`get_issue`, with title search as a fallback.

The intended sequence for future writes is:

```text
draft action -> interrupt -> human approval -> defensive approval check
             -> authorized Linear write
```

The approved title and description are the same fields sent to Linear; they are
not regenerated after approval. A unique request marker supports duplicate
recovery. If execution restarts after approval, it retries the pending node
without asking for a second approval and searches for the exact title before
another write. Never place the external write before the interrupt or rely
only on prompt instructions for authorization.

Use `check_mcp.py linear-write` to confirm that the full endpoint
initializes and exposes `save_issue` without invoking it. Linear uses the same
tool for create and update: omitting `id` creates, while supplying `id`
updates. The approval workflow never supplies `id`.

### Integrated analyst-to-issue workflow

Run the end-to-end acceptance request and pause on its generated draft:

```powershell
uv run python scripts/check_issue_workflow.py start
```

Resume the latest paused thread and choose `y` or `n`:

```powershell
uv run python scripts/check_issue_workflow.py resume
```

The analyst receives only DuckDB and read-only Linear tools. The write adapter
is bound separately to action nodes and its `save_issue` tool is never exposed
to the general analyst. If current Linear evidence shows an equivalent
initiative, drafting is skipped and no approval interrupt occurs. Otherwise,
the exact Pydantic-validated draft is checkpointed and displayed before any
write. Rejection reports the outcome without creating anything; approval uses
the duplicate-aware write implementation and saves the verified result in the
same conversation thread.

Verify the three persistence layers separately after an approved workflow:

```powershell
uv run python scripts/verify_issue_persistence.py checkpoint THREAD_ID
uv run python scripts/verify_issue_persistence.py conversation THREAD_ID
uv run python scripts/verify_issue_persistence.py memory THREAD_ID
```

Omit `THREAD_ID` to use the newest checkpoint with a verified created issue.
The checkpoint command is local and read-only. The conversation command uses
the original thread and performs fresh read-only source retrieval. The memory
command explicitly records the immutable creation event in the business-memory
store, then verifies retrieval from a newly generated thread. Issue outcomes
are not promoted to long-term memory automatically.

## 10. Streamlit application

Start the local UI from the repository root:

```powershell
uv run streamlit run streamlit_app.py
```

The sidebar creates and switches persistent conversations. Each conversation
uses a LangGraph `thread_id`, so its messages, pending interrupt, approved
draft, and action outcome survive Streamlit reruns and process restarts. The
latest route, action decision, status, and MCP tool calls are shown in the
activity panel.

Streamlit session state stores only the currently selected thread. Durable
state remains in SQLite:

| Database | Purpose |
|---|---|
| `ui_threads.sqlite` | Sidebar titles, ordering, and display status |
| `graph_checkpoints.sqlite` | Authoritative graph state and interrupts |
| `business_memory.sqlite` | Explicit user-scoped cross-thread memory |

Do not cache the live graph, MCP adapter, or async SQLite connections with
`st.cache_resource`. They can be bound to an event loop that no longer exists
after a rerun. The UI instead opens adapters and SQLite resources for one graph
operation, closes them deterministically, and reloads the saved checkpoint for
ordinary redraws. A per-thread process lock prevents duplicate clicks from
starting two operations at once.

Graph operations have a ten-minute UI timeout by default. Override it for a
slower local machine with `AI_PILOT_RUN_TIMEOUT_SECONDS` in `.env`. A timeout
cancels the local operation and closes its resources; saved checkpoints remain
available, and approved writes retain their duplicate-aware retry path.

Approval remains graph-owned. The UI renders the exact checkpointed draft and
resumes the interrupt with `Command(resume=...)`; it does not implement a
second approval state machine. The Linear write adapter is opened only for an
approved resume or retry.

Run the complete serial UI and persistence checks in
[ACCEPTANCE.md](ACCEPTANCE.md). Keep those checks out of pytest because they
depend on Ollama, live MCP connections, and workspace-specific Linear data.

## 11. Troubleshooting

- **The MCP server runs with no output:** expected for a stdio server waiting
  for a client.
- **Ollama rejects the context size:** reduce exposed tool schemas and history
  before increasing the model context window. Confirm the run uses the compact
  `reporter_evidence` state rather than injecting full raw evidence.
- **A Linear issue ID is invented:** expose `linear_find_issue`, not raw
  `get_issue`, to the model.
- **DuckDB is locked:** disconnect VS Code SQL clients and stop other processes
  using `business.duckdb`.
- **A generated query uses a CTE or subquery:** the current guard rejects it;
  simplify the query or deliberately extend the guard with tests.
- **A UI request times out:** inspect its saved activity and tool errors before
  increasing `AI_PILOT_RUN_TIMEOUT_SECONDS`; repeated identical calls should be
  blocked automatically.
- **Old conversation turns reappear:** reuse of the same `thread_id` resumes
  its checkpoint. Generate a new ID for an isolated run.
- **Long-term memories do not appear:** confirm the same `user_id` is passed in
  `BusinessContext` and that the graph was compiled with the store.
- **Linear imports fail after dependency changes:** run `uv sync` and keep the
  MCP SDK and LangChain MCP integration versions locked together in `uv.lock`.

## 12. Definition of done

- [ ] Deterministic behavior has pytest coverage.
- [ ] External services are mocked in automated tests.
- [ ] Relevant manual integration scripts pass.
- [ ] Route and tool traces match the intended sources.
- [ ] Claims are grounded in current evidence rather than history or memory.
- [ ] Writes remain behind explicit human authorization.
- [ ] `make check` passes.
- [ ] README, development guidance, or architecture history is updated when
      behavior or design changes.
