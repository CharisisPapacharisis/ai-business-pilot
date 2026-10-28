"""Construct the planner-analyst-reporter business-analysis graph."""

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ai_business_pilot.graph.action_nodes import create_action_nodes, route_draft
from ai_business_pilot.graph.nodes import create_nodes
from ai_business_pilot.graph.routing import route_after_analysis, route_question
from ai_business_pilot.graph.state import BusinessContext, BusinessState
from ai_business_pilot.model import create_chat_model


def build_graph(
    tools: list[BaseTool],
    checkpointer=None,
    store=None,
    *,
    action_tools: list[BaseTool] | None = None,
    model=None,
):
    """Compile the workflow with optional short- and long-term persistence."""
    model = model or create_chat_model()

    nodes = create_nodes(
        model=model,
        tools=tools,
    )
    action_nodes = create_action_nodes(model, action_tools or [])
    workflow = StateGraph(BusinessState, context_schema=BusinessContext)
    for name, node in nodes.items():
        workflow.add_node(name, node)
    workflow.add_node("issue_draft", action_nodes["issue_draft"])
    workflow.add_node("approval", action_nodes["approval"])
    workflow.add_node(
        "execute_action",
        action_nodes["execute_action"],
        retry_policy=RetryPolicy(max_attempts=2),
    )
    workflow.add_node(
        "verify_action",
        action_nodes["verify_action"],
        retry_policy=RetryPolicy(max_attempts=2),
    )
    workflow.add_node("reject_action", action_nodes["reject_action"])

    workflow.add_edge(START, "memory")
    workflow.add_edge("memory", "planner")
    workflow.add_conditional_edges(
        "planner",
        route_question,
        {
            "duckdb": "duckdb",
            "linear": "linear",
            "both": "both",
        },
    )
    for analyst in ("duckdb", "linear", "both"):
        workflow.add_conditional_edges(
            analyst,
            route_after_analysis,
            {"none": "reporter", "draft_issue": "issue_draft"},
        )
    workflow.add_conditional_edges(
        "issue_draft",
        route_draft,
        {"approval": "approval", "reporter": "reporter"},
    )
    workflow.add_conditional_edges(
        "approval",
        action_nodes["approval_router"],
        {"execute": "execute_action", "reject": "reject_action"},
    )
    workflow.add_edge("execute_action", "verify_action")
    workflow.add_edge("verify_action", "reporter")
    workflow.add_edge("reject_action", "reporter")
    workflow.add_edge("reporter", END)

    return workflow.compile(checkpointer=checkpointer, store=store)
