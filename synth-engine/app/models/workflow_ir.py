"""WorkflowIR - Intermediate Representation for n8n workflows.

This schema defines the structure that sits between natural language
descriptions and compiled n8n JSON. It provides:
- Strong typing for all workflow components
- Validation rules ensuring graph integrity
- Clear separation between logical structure and n8n specifics
"""
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class StepType(str, Enum):
    """Types of workflow steps."""
    TRIGGER = "trigger"
    ACTION = "action"
    BRANCH = "branch"
    MERGE = "merge"
    AGENT = "agent"
    TRANSFORM = "transform"


class TriggerType(str, Enum):
    """Types of workflow triggers."""
    WEBHOOK = "webhook"
    MANUAL = "manual"
    SCHEDULE = "schedule"
    APP_EVENT = "app_event"


class ErrorAction(str, Enum):
    """Actions to take on error."""
    RETRY = "retry"
    FALLBACK = "fallback"
    ABORT = "abort"
    CONTINUE = "continue"


class DataType(str, Enum):
    """Data types for contract schemas."""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    ANY = "any"


class FieldSchema(BaseModel):
    """Schema for a single field in a data contract."""
    
    name: str = Field(..., description="Field name")
    type: DataType = Field(..., description="Field data type")
    required: bool = Field(True, description="Whether field is required")
    description: Optional[str] = Field(None, description="Field description")
    default: Optional[Any] = Field(None, description="Default value")
    items_type: Optional[DataType] = Field(
        None,
        description="Type of array items (if type is array)",
    )


class DataContract(BaseModel):
    """Contract defining data shape between workflow steps."""
    
    name: str = Field(..., description="Contract name for reference")
    description: Optional[str] = Field(None, description="Human description")
    fields: list[FieldSchema] = Field(
        default_factory=list,
        description="Fields in this contract",
    )
    
    def to_json_schema(self) -> dict:
        """Convert to JSON Schema format."""
        properties = {}
        required = []
        
        for field in self.fields:
            prop = {"type": field.type.value}
            if field.description:
                prop["description"] = field.description
            if field.default is not None:
                prop["default"] = field.default
            if field.type == DataType.ARRAY and field.items_type:
                prop["items"] = {"type": field.items_type.value}
            
            properties[field.name] = prop
            if field.required:
                required.append(field.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }


class AgentSpec(BaseModel):
    """Specification for an agent within a workflow."""
    
    name: str = Field(..., description="Agent identifier")
    role: str = Field(..., description="Agent's role/purpose in the workflow")
    system_prompt: Optional[str] = Field(
        None,
        description="Custom system prompt for the agent",
    )
    tools_allowed: list[str] = Field(
        default_factory=list,
        description="Tools this agent can use",
    )
    input_schema: DataContract = Field(
        ...,
        description="Expected input data contract",
    )
    output_schema: DataContract = Field(
        ...,
        description="Produced output data contract",
    )
    max_tokens: int = Field(2048, description="Max tokens for agent response")
    temperature: float = Field(0.7, description="LLM temperature setting")


class RetryConfig(BaseModel):
    """Retry configuration for error handling."""
    
    max_retries: int = Field(3, ge=0, le=10)
    backoff_ms: int = Field(1000, ge=100)
    backoff_multiplier: float = Field(2.0, ge=1.0)


class ErrorStrategy(BaseModel):
    """Error handling strategy for the workflow."""
    
    default_action: ErrorAction = Field(
        ErrorAction.RETRY,
        description="Default action when an error occurs",
    )
    retry_config: Optional[RetryConfig] = Field(
        default_factory=lambda: RetryConfig(),
        description="Retry configuration",
    )
    fallback_step_id: Optional[str] = Field(
        None,
        description="Step to execute on fatal error",
    )
    error_workflow_id: Optional[str] = Field(
        None,
        description="External error handling workflow",
    )


class TestInvariant(BaseModel):
    """Invariant that must hold true for a test to pass."""
    
    name: str = Field(..., description="Invariant name")
    description: str = Field(..., description="What this invariant checks")
    type: str = Field(
        ...,
        description="Type: output_contains, output_matches_schema, branch_taken, etc.",
    )
    config: dict = Field(
        default_factory=dict,
        description="Type-specific configuration",
    )


class Position(BaseModel):
    """2D position for node layout."""
    
    x: int = Field(0, description="X coordinate")
    y: int = Field(0, description="Y coordinate")


class StepSpec(BaseModel):
    """Specification for a workflow step/node."""
    
    id: str = Field(
        default_factory=lambda: str(uuid4())[:8],
        description="Unique step identifier",
    )
    name: str = Field(..., description="Human-readable step name")
    type: StepType = Field(..., description="Step type")
    description: Optional[str] = Field(None, description="Step description")
    
    # Agent-specific (only for AGENT type)
    agent: Optional[AgentSpec] = Field(None, description="Agent specification")
    
    # n8n mapping
    n8n_node_type: str = Field(..., description="n8n node type string")
    n8n_type_version: int = Field(1, description="n8n node type version")
    parameters: dict = Field(
        default_factory=dict,
        description="n8n node parameters",
    )
    
    # Trigger-specific
    trigger_type: Optional[TriggerType] = Field(
        None,
        description="Trigger type (for TRIGGER steps)",
    )
    trigger_config: Optional[dict] = Field(
        None,
        description="Trigger-specific configuration",
    )
    
    # Branch-specific
    branch_conditions: Optional[list[dict]] = Field(
        None,
        description="Branching conditions (for BRANCH steps)",
    )
    
    # Layout
    position: Position = Field(
        default_factory=Position,
        description="Node position for layout",
    )
    
    @field_validator("agent")
    @classmethod
    def validate_agent(cls, v, info):
        """Ensure agent is provided for AGENT type steps."""
        if info.data.get("type") == StepType.AGENT and v is None:
            raise ValueError("Agent specification required for AGENT type steps")
        return v


class EdgeSpec(BaseModel):
    """Specification for an edge connecting two steps."""
    
    id: str = Field(
        default_factory=lambda: str(uuid4())[:8],
        description="Unique edge identifier",
    )
    source_id: str = Field(..., description="Source step ID")
    target_id: str = Field(..., description="Target step ID")
    source_output: str = Field("main", description="Source output name")
    target_input: str = Field("main", description="Target input name")
    
    # Data contract
    data_contract: Optional[DataContract] = Field(
        None,
        description="Data contract for this edge",
    )
    
    # Transform expression (n8n expression syntax)
    transform_expression: Optional[str] = Field(
        None,
        description="Expression to transform data on this edge",
    )
    
    # Branch condition (for conditional edges)
    condition: Optional[str] = Field(
        None,
        description="Condition for this edge (branch output name)",
    )
    
    # Label for UI
    label: Optional[str] = Field(None, description="Display label for the edge")


class WorkflowIR(BaseModel):
    """Intermediate Representation for an n8n workflow.
    
    This is the core data structure that captures the logical workflow
    structure before compilation to n8n JSON.
    """
    
    id: UUID = Field(default_factory=uuid4, description="Workflow IR ID")
    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="Workflow description")
    
    # Workflow structure
    trigger: StepSpec = Field(..., description="Trigger step (entry point)")
    steps: list[StepSpec] = Field(
        default_factory=list,
        description="All non-trigger steps",
    )
    edges: list[EdgeSpec] = Field(
        default_factory=list,
        description="Connections between steps",
    )
    
    # Error handling
    error_strategy: ErrorStrategy = Field(
        default_factory=ErrorStrategy,
        description="Error handling configuration",
    )
    
    # Success criteria for testing
    success_criteria: list[TestInvariant] = Field(
        default_factory=list,
        description="Invariants that define success",
    )
    
    # Metadata
    metadata: dict = Field(
        default_factory=dict,
        description="Additional metadata",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization",
    )
    
    @model_validator(mode="after")
    def validate_graph_integrity(self):
        """Ensure the workflow graph is valid."""
        # Collect all step IDs
        all_step_ids = {self.trigger.id}
        all_step_ids.update(step.id for step in self.steps)
        
        # Validate edges reference existing steps
        for edge in self.edges:
            if edge.source_id not in all_step_ids:
                raise ValueError(f"Edge source '{edge.source_id}' not found")
            if edge.target_id not in all_step_ids:
                raise ValueError(f"Edge target '{edge.target_id}' not found")
        
        # Check for dangling nodes (except trigger, which is always entry)
        referenced_targets = {edge.target_id for edge in self.edges}
        for step in self.steps:
            if step.id not in referenced_targets:
                raise ValueError(f"Step '{step.id}' ({step.name}) is not reachable")
        
        return self
    
    def get_step_by_id(self, step_id: str) -> Optional[StepSpec]:
        """Get a step by its ID."""
        if self.trigger.id == step_id:
            return self.trigger
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def get_downstream_steps(self, step_id: str) -> list[StepSpec]:
        """Get all steps downstream of a given step."""
        downstream_ids = [
            edge.target_id for edge in self.edges
            if edge.source_id == step_id
        ]
        return [
            step for step in self.steps
            if step.id in downstream_ids
        ]
    
    def get_upstream_steps(self, step_id: str) -> list[StepSpec]:
        """Get all steps upstream of a given step."""
        upstream_ids = [
            edge.source_id for edge in self.edges
            if edge.target_id == step_id
        ]
        result = []
        if self.trigger.id in upstream_ids:
            result.append(self.trigger)
        result.extend(step for step in self.steps if step.id in upstream_ids)
        return result
