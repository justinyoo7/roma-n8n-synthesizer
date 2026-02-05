"""Tests for registry-based tool resolution and compiler integration."""
import pytest

from app.n8n.capability_resolver import resolve_tool_id
from app.n8n.compiler import N8NCompiler
from app.models.workflow_ir import (
    WorkflowIR,
    StepSpec,
    EdgeSpec,
    StepType,
    TriggerType,
    AgentSpec,
    DataContract,
    FieldSchema,
    DataType,
    Position,
    ErrorStrategy,
)


def _build_minimal_agent() -> AgentSpec:
    return AgentSpec(
        name="apollo_search",
        role="Search for prospects",
        tools_allowed=[],
        input_schema=DataContract(
            name="input",
            fields=[FieldSchema(name="data", type=DataType.OBJECT, required=True)],
        ),
        output_schema=DataContract(
            name="output",
            fields=[FieldSchema(name="result", type=DataType.OBJECT, required=True)],
        ),
        max_tokens=256,
        temperature=0.2,
    )


def test_resolve_tool_id_with_hint():
    resolved = resolve_tool_id("people_search", "apollo")
    assert resolved is not None
    assert resolved["tool_id"] == "apollo.search_people"


def test_resolve_tool_id_without_hint():
    resolved = resolve_tool_id("company_enrichment")
    assert resolved is not None
    assert resolved["api_name"] in ["apollo", "clearbit", "clay", "zoominfo"]


def test_compiler_embeds_tool_id_in_agent_call():
    trigger = StepSpec(
        id="trigger",
        name="Trigger",
        type=StepType.TRIGGER,
        description="Start",
        n8n_node_type="n8n-nodes-base.webhook",
        n8n_type_version=1,
        parameters={},
        trigger_type=TriggerType.WEBHOOK,
        trigger_config={"httpMethod": "POST"},
        position=Position(x=0, y=200),
        capability="trigger",
    )

    step = StepSpec(
        id="step1",
        name="Search Apollo for Prospects",
        type=StepType.AGENT,
        description="Search prospects",
        agent=_build_minimal_agent(),
        n8n_node_type="@n8n/n8n-nodes-langchain.agent",
        n8n_type_version=1,
        parameters={},
        position=Position(x=200, y=200),
        capability="people_search",
        integration_hint="apollo",
    )

    ir = WorkflowIR(
        id="00000000-0000-0000-0000-000000000001",
        name="Test Workflow",
        description="Test",
        trigger=trigger,
        steps=[step],
        edges=[EdgeSpec(id="e1", source_id="trigger", target_id="step1", source_output="main", target_input="main")],
        error_strategy=ErrorStrategy(),
        success_criteria=[],
        metadata={},
        tags=[],
    )

    compiler = N8NCompiler()
    compiled = compiler.compile(ir)
    node = next(n for n in compiled["nodes"] if n["name"] == step.name)
    assert node["type"] == "n8n-nodes-base.httpRequest"
    assert "tool_id" in node["parameters"]["body"]
    assert "apollo.search_people" in node["parameters"]["body"]
