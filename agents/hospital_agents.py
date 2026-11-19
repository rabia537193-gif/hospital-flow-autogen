import json
import os
from typing import Any
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.messages import BaseChatMessage, ToolCallExecutionEvent, ToolCallRequestEvent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import ModelFamily
from autogen_ext.models.openai import OpenAIChatCompletionClient
from tools.hospital_tools import (
    load_hospital_snapshot,
    analyze_capacity_and_staffing,
    simulate_surge_and_discharge,
)


def build_model_client() -> OpenAIChatCompletionClient:
    """Create a Groq-backed OpenAI-compatible model client for AutoGen."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip()

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing or empty in .env")

    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        include_name_in_message=False,
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": False,
            "family": ModelFamily.UNKNOWN,
        },
    )


def create_hospital_team(model_client: OpenAIChatCompletionClient) -> list[AssistantAgent]:
    """Instantiate specialized AutoGen agents for hospital resource & flow optimization."""
    resource_analyst = AssistantAgent(
        name="ResourceAnalyst",
        model_client=model_client,
        tools=[load_hospital_snapshot, analyze_capacity_and_staffing],
        system_message=(
            "You are the Hospital Resource & Capacity Analyst. Use your tools to inspect bed "
            "occupancy, open beds, and nurse staffing deficits across units. Highlight exact "
            "numbers and safety constraints (such as nurse-to-patient load in ICU and surgical wards)."
        ),
    )

    flow_specialist = AssistantAgent(
        name="FlowSpecialist",
        model_client=model_client,
        tools=[analyze_capacity_and_staffing],
        system_message=(
            "You are the Patient Flow & Bottleneck Specialist. Identify where patients are getting "
            "stuck (ED backlog, ICU step-down delays, discharge bottlenecks) and recommend concrete "
            "flow interventions such as discharge prioritization, transfer sequencing, or boarding relief. "
            "When writing Markdown tables, ensure every row has the exact same number of '|' columns "
            "as the header with non-empty values in every cell."
        ),
    )

    contingency_coordinator = AssistantAgent(
        name="ContingencyCoordinator",
        model_client=model_client,
        tools=[simulate_surge_and_discharge],
        system_message=(
            "You are the Contingency & Risk Coordinator. Explicitly flag any missing or null data "
            "fields and state conservative fallback assumptions. Run surge simulations for unexpected "
            "admission spikes and propose fallback protocols when staffing or beds are tight."
        ),
    )

    operations_lead = AssistantAgent(
        name="OperationsLead",
        model_client=model_client,
        system_message=(
            "You are the Hospital Operations Lead. Synthesize findings from ResourceAnalyst, "
            "FlowSpecialist, and ContingencyCoordinator into a clear, prioritized action plan with: "
            "1) Top Bottlenecks, 2) Immediate Actions (0-2 hrs), 3) Short-Term Adjustments (2-6 hrs), "
            "and 4) Data Gaps & Risk Mitigations. "
            "STRICT TABLE RULE: Every Markdown table row MUST contain the exact same number of '|' cells "
            "as its header row, and NO table cell may be left empty. In Section 1, populate 'Current Impact' "
            "for every single row (e.g., High / Critical / Moderate + brief metric). In Section 3, fill "
            "Action, Detail, Owner, and KPI/Metric for every row without shifting columns. "
            "End your final response with TERMINATE."
        ),
    )

    return [resource_analyst, flow_specialist, contingency_coordinator, operations_lead]


async def run_hospital_optimization(
    extra_admissions_next_4h: int = 12,
    expedited_discharges_next_4h: int = 6,
    snapshot_path: str = "data/hospital_snapshot.json",
    max_messages: int = 10,
) -> dict[str, Any]:
    """Execute the AutoGen multi-agent team and return structured trace + final plan."""
    model_client = build_model_client()
    try:
        agents = create_hospital_team(model_client)
        termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(max_messages=max_messages)
        team = RoundRobinGroupChat(participants=agents, termination_condition=termination)

        task = (
            f"Load the hospital snapshot from '{snapshot_path}', analyze bed capacity, "
            f"staffing gaps, and patient flow bottlenecks, account for missing data, simulate a "
            f"4-hour surge of {extra_admissions_next_4h} extra admissions with "
            f"{expedited_discharges_next_4h} expedited discharges, and produce a "
            f"prioritized operational action plan."
        )

        result = await team.run(task=task)
        trace: list[dict[str, str]] = []
        final_plan = ""

        for msg in result.messages:
            if isinstance(msg, BaseChatMessage):
                source = getattr(msg, "source", "system")
                msg_type = type(msg).__name__

                if isinstance(msg, ToolCallRequestEvent):
                    calls = [f"{c.name}({c.arguments})" for c in msg.content]
                    content_str = " | ".join(calls)
                elif isinstance(msg, ToolCallExecutionEvent):
                    results = [f"{r.name}: {r.content}" for r in msg.content]
                    content_str = " | ".join(results)
                else:
                    content_str = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)

                trace.append({
                    "source": source,
                    "type": msg_type,
                    "content": content_str,
                })

                if source == "OperationsLead" and content_str.strip():
                    final_plan = content_str

        return {
            "status": "ok",
            "final_plan": final_plan,
            "trace": trace,
        }
    finally:
        await model_client.close()