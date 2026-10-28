"""Define the model and agent nodes used by the analysis graph."""

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama
from langgraph.runtime import Runtime
from pydantic import BaseModel

from ai_business_pilot.evidence import compact_evidence, compact_text, content_text
from ai_business_pilot.graph.agent_safety import analyst_middleware
from ai_business_pilot.graph.routing import explicit_action_intent
from ai_business_pilot.graph.state import Action, BusinessContext, BusinessState, Route
from ai_business_pilot.mcp_tools import create_linear_find_issue_tool
from ai_business_pilot.memory import memory_namespace

ROUTER_PROMPT = """
You plan business requests using two independent decisions:

1. source: which evidence source is required
2. action: whether the user requests a proposed external action

Available sources:

duckdb:
- Historical sales
- Product prices and costs
- Orders, customers, revenue, gross profit

linear:
- Business initiatives
- Issue descriptions and statuses
- Proposed commercial changes and decisions
- Questions asking what a proposal says, without calculating its impact

both:
- Questions that require proposal context AND measured business data
- Calculating the financial impact of a proposed pricing or cost change
- Comparing historical performance with an ongoing initiative

A question remains linear-only when it asks for a proposal's status or
contents, even if that proposal mentions prices or costs. Choose both only
when answering also requires actual sales, prices, costs, revenue or profit
from the business database.

Actions:
- none: answer or analyze only
- draft_issue: the user asks to propose, prepare, draft, or create a Linear issue

Selecting draft_issue never authorizes a write. Analysis, a validated draft,
and explicit human approval still happen before any external action.
"""


class PlannerDecision(BaseModel):
    """Independent source and action decisions returned by the planner."""

    source: Route
    action: Action


ANALYST_PROMPT = """
You are an AI Business Intelligence Analyst.

Use the available MCP tools to investigate the question.

Rules:
1. Retrieve actual evidence using tools.
   Conversation history is context only, never current evidence.
   Long-term memory contains preferences and conventions, not current facts.
2. Never invent figures, proposals or issue statuses.
3. Search for Linear issues by title or keywords with linear_find_issue.
4. Inspect database schemas before generating SQL.
5. Use execute_readonly_query for custom SQL calculations. Match the SQL to
   the requested business measure: totals, averages, counts, unit values and
   percentages are not interchangeable. Follow SQL grouping rules.
6. Distinguish actual results from hypothetical scenarios.
7. State assumptions when calculating business scenarios.
8. Do not create or modify Linear issues.
9. Monetary values are fictional and in USD.
10. If a tool fails, report the problem rather than guessing.
11. Use execute_readonly_query when the question includes a date or other
    filter; do not use an unfiltered summary for a filtered question.
12. Query the required MCP source on every turn, even when conversation
    history contains an earlier answer. Source data may have changed.
13. Apply relevant long-term preferences when they do not conflict with the
    current question. Never use memory as proof of an operational fact.
14. When a tool returns an error, use its details to change the query or
    arguments. Never repeat the same tool call with unchanged arguments.
15. Every derived numerical result must be calculated by
    execute_readonly_query and appear in tool evidence. Do not perform
    arithmetic in prose, including apparently simple multiplication,
    percentages or scenario calculations.
16. Before finishing a numerical analysis, run a final verification query
    that returns the inputs, assumptions and requested calculated outputs
    together. The final findings may use only verified values from that result.
17. An empty query result does not prove that an entity or data does not
    exist. Before making an absence claim, verify likely identifier columns
    and distinct values, then retry with the correct column and spelling.
    A result marked UNVERIFIED_EMPTY_RESULT requires this verification.

Finish with compact findings, calculations and assumptions for the reporter.
Do not write the audience-facing final report.

For cross-system questions, retrieve evidence from BOTH
DuckDB and Linear before producing the final analysis.
"""


REPORTER_PROMPT = """
You write concise, evidence-based business reports.

Given the original question, the analyst's findings,
and retrieved evidence:

- Answer the question directly.
- Include important numerical results.
- Explain relevant business initiatives and their status.
- Clearly distinguish facts, proposals and assumptions.
- Synthesize the findings into a polished answer rather than repeating the
  analyst's wording.
- Never fabricate missing evidence.
- Treat retrieved facts and calculated results differently. Clearly label
  scenario assumptions.
- Copy calculated values from tool evidence. Do not calculate, adjust, round
  or infer new numerical values yourself. If the requested final metric is
  absent from evidence, say that it was not verified.
- Do not mention initiatives unless Linear evidence describes them.
- When Requested action is none, do not invent an issue draft or recommend
  that an issue was prepared. Answer only the analytical question.
- Never describe UNVERIFIED_EMPTY_RESULT as proof that data is absent. State
  that absence was not verified if no later successful evidence resolves it.
- If retrieval failed, acknowledge the limitation.

All monetary values are fictional and in USD.
"""

DUCKDB_ANALYST_TOOLS = {
    "duckdb_list_tables",
    "duckdb_describe_table",
    "duckdb_execute_readonly_query",
}


def create_nodes(model: ChatOllama, tools: list[BaseTool]) -> dict:
    """Create the router, source-specific analysts, and reporter nodes."""

    # Separate tools by the MCP server that provides them.
    duckdb_tools = [tool for tool in tools if tool.name in DUCKDB_ANALYST_TOOLS]
    linear_tools = [create_linear_find_issue_tool(tools)]

    if not duckdb_tools:
        raise ValueError("No DuckDB MCP tools discovered")

    print(f"DuckDB tools: {len(duckdb_tools)}")
    print(f"Linear tools: {len(linear_tools)}")

    # Build a LangChain agent for each tool set.
    duckdb_agent = create_agent(
        model=model,
        tools=duckdb_tools,
        system_prompt=ANALYST_PROMPT,
        middleware=analyst_middleware(),
    )

    linear_agent = create_agent(
        model=model,
        tools=linear_tools,
        system_prompt=ANALYST_PROMPT,
        middleware=analyst_middleware(),
    )

    combined_agent = create_agent(
        model=model,
        tools=duckdb_tools + linear_tools,
        system_prompt=ANALYST_PROMPT,
        middleware=analyst_middleware(),
    )

    def conversation_context(state: BusinessState) -> str:
        """Return a small recent-history window for follow-up interpretation."""
        history = state.get("history", [])[-6:]
        return "\n".join(history) if history else "No previous conversation."

    def memory_context(state: BusinessState) -> str:
        """Format the user memories retrieved for the current run."""
        memories = state.get("memories", [])
        return "\n".join(f"- {memory}" for memory in memories) or "No saved memory."

    async def memory_node(
        state: BusinessState,
        runtime: Runtime[BusinessContext],
    ) -> dict:
        """Load user-scoped durable preferences before planning."""
        if runtime.store is None or runtime.context is None:
            return {"memories": []}

        items = await runtime.store.asearch(
            memory_namespace(runtime.context.user_id),
            limit=10,
        )
        memories = [
            f"{item.value.get('category', 'memory')}: {item.value['content']}"
            for item in items
            if isinstance(item.value.get("content"), str)
        ]
        print(f"\n[MEMORY] Loaded {len(memories)} long-term memories.")
        return {"memories": memories}

    async def planner_node(state: BusinessState) -> dict:
        """Classify both required evidence and requested external action."""
        print("\n[PLANNER] Selecting information sources and action intent...")

        response = await model.with_structured_output(PlannerDecision).ainvoke(
            [
                ("system", ROUTER_PROMPT),
                (
                    "human",
                    f"""Previous conversation (context only):
{conversation_context(state)}

Current question:
{state["question"]}

Long-term business preferences (context only):
{memory_context(state)}

Choose the evidence source and action for the current question. Use history
only to resolve follow-up references such as "it" or "that proposal".""",
                ),
            ]
        )
        decision = (
            response
            if isinstance(response, PlannerDecision)
            else PlannerDecision.model_validate(response)
        )

        explicit_action = explicit_action_intent(state["question"])
        if explicit_action is not None and decision.action != explicit_action:
            print("Explicit issue request detected; selecting draft_issue.")
            decision = decision.model_copy(update={"action": explicit_action})

        print(f"Selected route: {decision.source}")
        print(f"Selected action: {decision.action}")

        return {
            "route": decision.source,
            "action": decision.action,
            "plan": (f"Use {decision.source} MCP source(s); action={decision.action}."),
            "draft": None,
            "draft_reason": "",
            "approved": None,
            "status": "analysis_pending",
            "created_issue": None,
        }

    async def run_analysis(
        state: BusinessState,
        agent,
        path_name: str,
    ) -> dict:
        """Run one configured agent and collect its tool evidence."""
        print(f"\n[ANALYST] Executing {path_name} path...")

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": f"""Previous conversation (context only):
{conversation_context(state)}

Current question:
{state["question"]}

Long-term business preferences and conventions:
{memory_context(state)}

Investigate the current question using fresh MCP tool results. Do not treat
facts or figures from the previous conversation as current evidence.""",
                    }
                ]
            },
            # Middleware adds internal graph steps around every model/tool cycle.
            # Behavioral limits below bound the work; this is only a technical ceiling.
            config={"recursion_limit": 80},
        )

        tool_calls = []
        evidence = []

        for message in result["messages"]:
            for call in getattr(message, "tool_calls", []):
                tool_calls.append(f"{call['name']}: {call['args']}")

            if message.type == "tool":
                evidence.append(f"{message.name}: {content_text(message.content)}")

        analysis = str(result["messages"][-1].content)

        print(f"Executed {len(tool_calls)} tool calls.")

        return {
            "analysis": analysis,
            "evidence": "\n".join(evidence),
            "reporter_evidence": compact_evidence(evidence),
            "tool_calls": tool_calls,
        }

    async def duckdb_node(state: BusinessState) -> dict:
        """Analyze a question using only DuckDB tools."""
        return await run_analysis(state, duckdb_agent, "DuckDB")

    async def linear_node(state: BusinessState) -> dict:
        """Analyze a question using only Linear tools."""
        return await run_analysis(state, linear_agent, "Linear")

    async def both_node(state: BusinessState) -> dict:
        """Analyze a question using DuckDB and Linear tools."""
        return await run_analysis(state, combined_agent, "Combined")

    async def reporter_node(state: BusinessState) -> dict:
        """Turn the analysis and retrieved evidence into the final answer."""
        print("\n[REPORTER] Preparing answer...")

        if state.get("evidence"):
            prompt = f"""
Question:
{state["question"]}

Selected route:
{state["route"]}

Analyst findings:
{compact_text(state["analysis"], 2500)}

Retrieved tool evidence:
{state.get("reporter_evidence") or compact_text(state["evidence"], 5000)}

Relevant long-term preferences and conventions:
{memory_context(state)}

Requested action:
{state.get("action", "none")}

Action outcome:
- Status: {state.get("status", "analysis_only")}
- Drafting decision: {state.get("draft_reason", "Not applicable")}
- Approved: {state.get("approved")}
- Created issue: {state.get("created_issue")}

Write the final business answer.
"""
            response = await model.ainvoke(
                [
                    ("system", REPORTER_PROMPT),
                    ("human", prompt),
                ]
            )
            answer = str(response.content)
        else:
            answer = "I could not verify the answer using the available MCP tools."

        updated_history = state.get("history", []) + [
            f"User: {state['question']}",
            f"Assistant: {answer}",
        ]
        action_outcomes = state.get("action_outcomes", [])
        terminal_action_statuses = {
            "created_verified",
            "rejected",
            "issue_not_proposed",
        }
        if (
            state.get("action") == "draft_issue"
            and state.get("status") in terminal_action_statuses
        ):
            draft = state.get("draft") or {}
            outcome = {
                "request_id": draft.get("request_id"),
                "question": state["question"],
                "status": state.get("status"),
                "approved": state.get("approved"),
                "issue": state.get("created_issue"),
            }
            if not any(
                existing.get("request_id") == outcome["request_id"]
                and existing.get("status") == outcome["status"]
                and existing.get("question") == outcome["question"]
                for existing in action_outcomes
            ):
                action_outcomes = [*action_outcomes, outcome]
        result = {
            "final_answer": answer,
            "history": updated_history,
            "action_outcomes": action_outcomes,
        }
        if state.get("action") == "none":
            result["status"] = "completed"
        return result

    return {
        "memory": memory_node,
        "planner": planner_node,
        "duckdb": duckdb_node,
        "linear": linear_node,
        "both": both_node,
        "reporter": reporter_node,
    }
