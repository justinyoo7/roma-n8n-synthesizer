"""Task Tree models for ROMA-style recursive decomposition.

The task tree represents the hierarchical breakdown of a workflow
synthesis task into subtasks that can be executed by specialized modules.
"""
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.workflow_ir import WorkflowIR


class SubtaskType(str, Enum):
    """Types of subtasks in the ROMA pipeline."""
    
    # Atomizer outputs
    COMPLEXITY_ASSESSMENT = "complexity_assessment"
    INITIAL_DRAFT = "initial_draft"
    
    # Planner subtasks
    CHOOSE_TRIGGER = "choose_trigger"
    DEFINE_AGENTS = "define_agents"
    DEFINE_DATA_CONTRACTS = "define_data_contracts"
    SELECT_N8N_NODES = "select_n8n_nodes"
    DEFINE_ERROR_HANDLING = "define_error_handling"
    GENERATE_TESTS = "generate_tests"
    DEFINE_LAYOUT = "define_layout"
    
    # Executor artifact types
    NODE_SELECTION = "node_selection"
    DATA_CONTRACT = "data_contract"
    MAPPING = "mapping"
    TEST_CASE = "test_case"
    
    # Verifier outputs
    VALIDATION_RESULT = "validation_result"
    COMPILATION_RESULT = "compilation_result"
    TEST_EXECUTION = "test_execution"
    FIX_PLAN = "fix_plan"
    
    # Simplifier outputs
    SIMPLIFICATION_CANDIDATE = "simplification_candidate"
    SIMPLIFICATION_RESULT = "simplification_result"


class TaskStatus(str, Enum):
    """Status of a task node."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Artifact(BaseModel):
    """An artifact produced by a task executor."""
    
    id: UUID = Field(default_factory=uuid4)
    type: SubtaskType
    content: Any
    metadata: dict = Field(default_factory=dict)
    created_at: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True


class TaskNode(BaseModel):
    """A node in the task tree representing a subtask."""
    
    id: UUID = Field(default_factory=uuid4)
    type: SubtaskType
    name: str
    description: str
    
    # Dependencies
    depends_on: list[UUID] = Field(
        default_factory=list,
        description="IDs of tasks this task depends on",
    )
    
    # Execution state
    status: TaskStatus = Field(TaskStatus.PENDING)
    priority: int = Field(0, description="Higher = execute first among siblings")
    
    # Inputs and outputs
    input_data: dict = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    error: Optional[str] = None
    
    def is_ready(self, completed_tasks: set[UUID]) -> bool:
        """Check if this task is ready to execute."""
        return all(dep in completed_tasks for dep in self.depends_on)


class TaskTree(BaseModel):
    """A tree of tasks for workflow synthesis.
    
    The tree represents the hierarchical decomposition of the synthesis
    problem, with dependencies between tasks forming a DAG.
    """
    
    id: UUID = Field(default_factory=uuid4)
    root_prompt: str = Field(..., description="Original user prompt")
    
    # Task nodes
    tasks: list[TaskNode] = Field(default_factory=list)
    
    # Execution tracking
    completed_task_ids: set[UUID] = Field(default_factory=set)
    current_task_id: Optional[UUID] = None
    
    # Results
    is_atomic: bool = Field(
        False,
        description="True if task was handled atomically (no decomposition)",
    )
    final_workflow_ir: Optional[WorkflowIR] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def get_task(self, task_id: UUID) -> Optional[TaskNode]:
        """Get a task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def get_ready_tasks(self) -> list[TaskNode]:
        """Get all tasks ready for execution (dependencies met, not started)."""
        return [
            task for task in self.tasks
            if task.status == TaskStatus.PENDING
            and task.is_ready(self.completed_task_ids)
        ]
    
    def mark_completed(self, task_id: UUID, artifacts: list[Artifact]) -> None:
        """Mark a task as completed with its artifacts."""
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.artifacts = artifacts
            self.completed_task_ids.add(task_id)
    
    def mark_failed(self, task_id: UUID, error: str) -> None:
        """Mark a task as failed."""
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error = error
    
    def is_complete(self) -> bool:
        """Check if all tasks are complete."""
        return all(
            task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            for task in self.tasks
        )
    
    def has_failures(self) -> bool:
        """Check if any tasks failed."""
        return any(task.status == TaskStatus.FAILED for task in self.tasks)
    
    def get_all_artifacts(self) -> list[Artifact]:
        """Collect all artifacts from completed tasks."""
        artifacts = []
        for task in self.tasks:
            if task.status == TaskStatus.COMPLETED:
                artifacts.extend(task.artifacts)
        return artifacts


class SynthesisResult(BaseModel):
    """Result of the synthesis pipeline."""
    
    workflow_id: UUID
    iteration_id: UUID
    iteration_version: int
    
    workflow_ir: WorkflowIR
    n8n_json: dict
    
    rationale: str
    test_plan: list[dict]
    
    task_tree: Optional[TaskTree] = None
    
    score: Optional[int] = None
    score_breakdown: Optional[dict] = None
    
    class Config:
        arbitrary_types_allowed = True


class IterationResult(BaseModel):
    """Result of an iteration cycle."""
    
    iteration_id: UUID
    iteration_version: int
    
    workflow_ir: WorkflowIR
    n8n_json: dict
    
    changes_made: list[str]
    rationale: str
    
    score: Optional[int] = None
    score_breakdown: Optional[dict] = None
    
    class Config:
        arbitrary_types_allowed = True


class SimplificationResult(BaseModel):
    """Result of the simplification pass."""
    
    iteration_id: UUID
    iteration_version: int
    
    workflow_ir: WorkflowIR
    n8n_json: dict
    
    simplifications_applied: list[str]
    nodes_removed: int
    edges_removed: int
    
    original_score: int
    new_score: int
    
    class Config:
        arbitrary_types_allowed = True


class FixPlan(BaseModel):
    """Plan for fixing failures identified by the Verifier."""
    
    id: UUID = Field(default_factory=uuid4)
    iteration_id: UUID
    
    failures: list[dict] = Field(
        ...,
        description="List of failures to address",
    )
    
    fixes: list[dict] = Field(
        ...,
        description="Proposed fixes with target modules",
    )
    
    priority_order: list[UUID] = Field(
        default_factory=list,
        description="Order to apply fixes",
    )
    
    requires_replan: bool = Field(
        False,
        description="True if fix requires going back to Planner",
    )
