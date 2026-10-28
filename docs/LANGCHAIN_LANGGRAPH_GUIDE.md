# LangChain and LangGraph Concepts in This Project

This guide is the learning map for AI Business Pilot. It explains which
LangChain and LangGraph concepts the project uses, what each one does, and
where to find a concrete example.

It is intentionally different from the other documents:

- `README.md` describes the product.
- `DEVELOPMENT.md` explains how to run and maintain it.
- `ARCHITECTURE.md` records why the design evolved.
- `ACCEPTANCE.md` verifies the live system.
- this guide explains the framework concepts demonstrated by the code.

## 1. LangChain versus LangGraph

The two libraries solve related but different problems.

**LangChain** provides the model and tool layer:

- the Ollama chat model;
- system and human messages;
- tools and tool schemas;
- tool-calling agents;
- structured model output;
- middleware around model and tool calls.

**LangGraph** provides the workflow and durable state layer:

- nodes and edges;
- conditional routing;
- shared graph state;
- checkpointed conversation threads;
- cross-thread stores;
- pause and resume with human approval;
- retries and recursion limits.

In short:

```text
LangChain: let a model reason with tools
LangGraph: control when that reasoning runs and preserve workflow state
```

## 2. The chat model

`src/ai_business_pilot/model.py` creates a `ChatOllama` instance. A chat model
accepts a sequence of messages and returns an AI message.

The important configuration is:

- `model`: which local Ollama model to run;
- `temperature=0`: reduce randomness, although it does not make the model fully
  deterministic;
- context settings: how much prompt, tool-schema, history, and evidence text
  the model can receive at once.

The project reuses the model configuration, but it makes several distinct
model calls during one graph run. There is not one continuously running “AI
agent mind.” For example, the planner, selected analyst, issue drafter, and
reporter may each invoke the model for a different purpose.

## 3. Messages and roles

Calls such as this appear in `graph/nodes.py`:

```python
response = await model.ainvoke(
    [
        ("system", REPORTER_PROMPT),
        ("human", prompt),
    ]
)
```

The roles mean:

- **system**: stable behavior and constraints for this particular call;
- **human**: the current input and context supplied to the model;
- **AI**: the model's returned message;
- **tool**: a result returned from a tool call.

The human message can contain generated application context; it does not have
to be text typed verbatim by a person.

Message history is not hidden model reasoning. In this project, `history` is a
small list of previous user questions and final assistant answers, for example:

```text
User: What is the pricing initiative proposing?
Assistant: It proposes a 5% increase...
User: What would that do to gross profit?
Assistant: ...
```

The model's private internal reasoning is neither stored nor passed between
nodes. Tool calls and tool results are visible messages and are collected as
evidence separately.

## 4. Asynchronous calls

The project uses `async def`, `await`, and methods beginning with `a`, such as:

- `model.ainvoke(...)`;
- `agent.ainvoke(...)`;
- `tool.ainvoke(...)`;
- `store.asearch(...)`.

These are asynchronous versions of invocation methods. They allow Python to
wait for Ollama, MCP, SQLite, or a remote service without blocking the event
loop. Async does not mean that every operation automatically runs in parallel.
It means the caller can yield control while waiting.

`async with adapter` is especially important. It opens the MCP connections,
keeps them alive while tools and the graph use them, and closes them afterward.
The Streamlit runtime uses `AsyncExitStack` because it must manage several
optional async resources together.

At a synchronous boundary, such as Streamlit calling the runtime, the project
uses `asyncio.run(...)` to create an event loop for one complete operation.

## 5. Tools

A LangChain tool is a named callable with a description and an argument
schema. The model sees that schema and can request a call; application code
executes it and returns a `ToolMessage`.

The project obtains most tools from MCP through `MCPAdapter`. It also creates a
composed application tool in `mcp_tools.py`:

```python
@tool("linear_find_issue")
async def find_linear_issue(query: str) -> str:
    ...
```

This wrapper is important because it enforces a safe sequence:

```text
search by title -> choose a real result -> retrieve its real ID
```

The model therefore cannot directly invent a plausible Linear ID. This is an
example of a recurring design rule: use model judgment for interpretation, but
put mandatory sequences and guarantees in ordinary code.

`BaseTool` is the common type used when functions accept any LangChain tool.
Calling `tool.ainvoke(arguments)` executes the tool directly without asking a
model to choose it.

## 6. MCP adapters and tool filtering

MCP is the protocol boundary between the application and its capabilities.
`mcp_client.py` configures:

- a local stdio DuckDB MCP server;
- a remote read-only Linear MCP server;
- a separately authorized Linear write connection when needed.

The adapter discovers tools from a server and converts them into LangChain
tools. Discovery does not mean every discovered tool must be exposed to every
agent.

`create_nodes()` builds three route-specific tool sets:

- DuckDB analyst: approved DuckDB read tools;
- Linear analyst: only the composed `linear_find_issue` tool;
- combined analyst: both filtered sets.

Filtering reduces model context, makes provenance clear, and limits accidental
capabilities. Linear write tools are never given to the general analyst.

## 7. Tool-calling agents

`create_agent(...)` in `graph/nodes.py` builds a LangChain agent. An agent is a
small internal loop that can alternate between model and tool calls:

```text
model decides next step
  -> tool call
  -> tool result
  -> model reviews result
  -> another tool call or final analyst findings
```

The project creates three agents with the same analyst instructions but
different tool access. Only the agent selected by the outer LangGraph route is
invoked for a question.

This internal agent loop is different from the outer business graph. The agent
figures out how to investigate with its allowed tools; LangGraph decides which
business stage runs next.

## 8. Structured output with Pydantic

Free-form text is useful for reports but unreliable for control decisions.
`with_structured_output(PydanticModel)` asks the model to produce data matching
a schema.

The project uses this for:

- `PlannerDecision`: source route plus action intent;
- `IssueDraftDecision`: whether a new issue is justified and its proposed
  fields;
- `LinearIssueDraft`: final validation of the exact draft shown for approval.

For example, the planner must return values equivalent to:

```python
PlannerDecision(source="both", action="draft_issue")
```

Pydantic validates types, allowed literal values, required fields, string
lengths, and priority ranges. Structured output narrows model variability; it
does not itself authorize an external action.

## 9. Middleware and guardrails

Middleware is code wrapped around agent model or tool calls. It can inspect a
request, call the original handler, inspect the result, or return a replacement
result.

`graph/agent_safety.py` defines the analyst middleware:

1. **Duplicate-call guard**: blocks an exact repeated tool name and argument
   set, while allowing a corrected query.
2. **Empty-result guard**: changes a zero-row analytical result into a tool
   error requiring identifier verification. One query using the wrong column
   is not accepted as proof that data is absent.
3. **Tool-call limit**: bounds how many tools one analyst may call.
4. **Model-call limit**: bounds how many internal model turns it may take.

These safeguards do not create additional agents. They constrain the internal
loop of the one selected analyst.

The SQL guard is separate from LangChain middleware. It validates SQL at the
DuckDB execution boundary, so even a model that ignores its prompt cannot run
writes or unsupported query structures.

## 10. Tool evidence versus analyst findings

After an agent finishes, `run_analysis()` walks through its returned messages:

- requested tool calls become `tool_calls` for activity display;
- tool messages become `evidence`;
- the last AI message becomes the internal `analysis`.

These fields serve different purposes:

- **evidence**: normalized source results from tools;
- **analysis**: the analyst model's interpretation of those results;
- **final_answer**: the reporter model's audience-facing synthesis;
- **history**: previous questions and final answers for follow-up context.

Full evidence is saved in the checkpoint. `reporter_evidence` is a compact,
source-balanced projection built by `evidence.py` to fit the local model's
context window. The compact copy favors final DuckDB calculations and Linear
results over large schemas. Compaction changes the reporter prompt, not the
saved audit trace.

## 11. Graph state

`BusinessState` in `graph/state.py` is the shared data shape passed between
LangGraph nodes. A node receives the current state and returns only the fields
it wants to add or update.

For example, the planner returns route, action, plan, and status. The analyst
later adds analysis, evidence, and tool calls. The reporter adds the final
answer and updated history.

State is not a global Python variable. LangGraph manages how node updates are
merged and, when configured, checkpointed.

`BusinessContext` is different from state. It contains runtime identity—in
this project, `user_id` for memory isolation. Context is supplied to a run but
is not ordinary evolving conversation state.

## 12. Nodes, edges, and compilation

`graph/builder.py` creates a `StateGraph(BusinessState)`. A node is an ordinary
Python callable registered under a name:

```python
workflow.add_node("planner", planner_node)
```

An ordinary edge always follows the same path:

```python
workflow.add_edge("memory", "planner")
```

A conditional edge calls a routing function and maps its result to a node:

```python
workflow.add_conditional_edges(
    "planner",
    route_question,
    {"duckdb": "duckdb", "linear": "linear", "both": "both"},
)
```

`START` and `END` are special graph boundaries. `compile(...)` validates the
workflow and produces the runnable graph. Passing a checkpointer or store at
compile time enables those persistence features for the compiled graph.

## 13. Planning and routing

The planner makes two independent decisions:

```text
source: duckdb | linear | both
action: none | draft_issue
```

This separation matters. “Use both sources” does not imply “write something,”
and asking for a draft does not authorize its creation.

The route functions are normal deterministic Python functions. They validate
the selected value and choose the next edge. The explicit-action check is a
code-level fallback for clear phrases such as “create a Linear issue,” because
a small model can occasionally classify explicit action intent incorrectly.

The validation inside the router is still useful even after planner
validation: checkpointed state, tests, future callers, or code changes can
introduce invalid values. Each boundary protects its own assumption.

## 14. Invoking the graph

The common execution form is:

```python
result = await graph.ainvoke(
    {"question": question},
    config={"configurable": {"thread_id": thread_id}},
    context=BusinessContext(user_id=user_id),
)
```

- the first argument is the input state update;
- `thread_id` selects the checkpointed conversation;
- `context` supplies the user identity used for long-term memory;
- the returned mapping contains the latest graph state when the run completes.

`configurable` is LangGraph's standard configuration namespace for runtime
values such as checkpoint thread identity. It is configuration, not business
state, so it is kept outside `BusinessState`.

## 15. Checkpointing and conversation threads

`AsyncSqliteSaver` is the checkpointer. It persists graph state after graph
steps under a `thread_id`.

This enables:

- multiple turns in the same conversation;
- browser refresh and process restart recovery;
- pending approval interrupts;
- inspection of route, evidence, status, and action outcome;
- resuming from the correct graph position.

A new `thread_id` starts an independent conversation. Reusing one continues
its saved graph state.

Checkpointing does not automatically mean that old facts are current. The
project passes recent history as linguistic context, then instructs analysts
to retrieve required DuckDB or Linear evidence again.

## 16. Long-term memory with a store

`AsyncSqliteStore` is different from the checkpointer. The store holds explicit
records under a namespace such as:

```python
("business_memory", user_id)
```

This allows multiple threads belonging to the same user to retrieve durable
preferences and conventions. Suitable memories include:

- preferred scenario assumptions;
- reporting conventions;
- approved decision rules;
- internal terminology.

Changing operational facts—prices, sales totals, calculations, and issue
statuses—do not belong in long-term memory as current truth.

The current project writes memories explicitly. It does not automatically ask
the model to extract everything worth remembering, because that would require
deduplication, conflict handling, deletion, privacy, and stale-memory policies.

## 17. Human-in-the-loop interrupts

`interrupt(payload)` inside the approval node pauses graph execution and saves
the checkpoint. The payload contains the exact validated draft displayed to
the user.

The process can stop at this point. Later, the terminal script or Streamlit UI
resumes the same thread with:

```python
Command(resume={"approved": True})
```

LangGraph returns that resume value to the interrupted node, which records the
decision and routes to execution or rejection.

Approval is therefore part of the graph, not duplicated as UI-only state. The
UI merely displays the saved interrupt and sends the human decision back.

## 18. Retries, idempotency, and write isolation

`RetryPolicy(max_attempts=2)` allows the write and verification nodes to retry
after a transient failure. Retrying a remote write can create duplicates, so a
retry policy alone is not enough.

Before writing, the action node searches for the exact unique approved title.
If it already exists, it reuses that issue. The approved draft is frozen and
is not regenerated after approval.

The runtime opens Linear write tools only while resuming an approved action.
The analyst that gathered evidence never receives those tools. This is both a
LangGraph workflow boundary and a capability-security boundary.

## 19. Recursion limits

LangGraph uses “recursion” to describe repeated graph steps; it does not
necessarily mean a Python function recursively calling itself.

There are two relevant levels:

- the internal LangChain agent graph loops between model and tool calls;
- the outer business graph moves between memory, planner, analyst, action, and
  reporter nodes.

The internal analyst has model/tool limits plus a technical recursion ceiling.
The UI invocation also has an outer recursion limit. These limits turn an
unproductive loop into an explicit error instead of allowing it to run
indefinitely.

Increasing a recursion limit can be appropriate when valid work needs more
steps, but it does not fix a repeated bad tool call. That is why the project
also has duplicate-call and empty-result guards.

## 20. How one request moves through the system

For a cross-system action request, the complete lifecycle is:

```text
1. Streamlit supplies question + thread_id + user_id
2. memory node loads explicit user memories
3. planner returns source=both and action=draft_issue
4. conditional edge selects the combined analyst
5. LangChain agent calls filtered DuckDB and Linear tools
6. middleware constrains retries and empty-result claims
7. graph saves findings, full evidence, compact evidence, and tool trace
8. issue drafter uses structured output to propose or decline a draft
9. approval node interrupts with the exact validated draft
10. UI resumes the same checkpoint with approve or reject
11. approved path opens isolated write tools, checks duplicates, and writes
12. verification node confirms the remote issue
13. reporter produces the final answer
14. checkpointer saves the completed state and conversation history
```

For an analytical question, steps 8–12 are skipped and the analyst goes
directly to the reporter.

## 21. What the project deliberately does not delegate to the model

The model interprets language, selects tools within a narrow set, drafts text,
and synthesizes results. Ordinary code remains responsible for:

- SQL allowlisting and read-only access;
- route-value validation;
- exact action-intent fallback;
- Linear ID resolution order;
- tool and model call limits;
- empty-result verification requirements;
- Pydantic field validation;
- approval state;
- write-tool isolation;
- duplicate checks and verification;
- persistence namespaces and resource lifetimes.

That division is the central lesson of the project: agents are useful inside
well-defined software boundaries, not as replacements for those boundaries.

## 22. Best files to revisit while learning

Read these in order:

1. `graph/state.py` — what travels through the workflow.
2. `graph/builder.py` — nodes, edges, routing, retries, and compilation.
3. `graph/nodes.py` — model calls, agents, history, memory, and reporting.
4. `graph/agent_safety.py` — middleware around tool use.
5. `mcp_tools.py` — composing a safer high-level tool.
6. `approval.py` — interrupt, resume, guarded execution, and verification.
7. `ui/runtime.py` — checkpointer, store, MCP resource lifetime, and invocation.
8. `tests/test_agent_safety.py` and `tests/test_approval.py` — the same concepts
   in small deterministic examples.
