"""Planner - Second stage of ROMA pipeline.

The Planner takes the TaskTree from the Atomizer and:
1. Decomposes complex tasks into specific subtasks
2. Determines dependencies between subtasks
3. Identifies which subtasks can be parallelized
4. Assigns priorities for execution order
"""
from typing import Optional
from uuid import UUID

import structlog

from app.llm.adapter import get_llm_adapter
from app.models.task_tree import (
    TaskTree,
    TaskNode,
    TaskStatus,
    SubtaskType,
)

logger = structlog.get_logger()


PLANNING_PROMPT = """You are a workflow planning expert. Given a user's workflow description, decompose it into concrete subtasks.

For each identified component, create subtasks that specify:
1. What needs to be done
2. What information is needed
3. What the output should be

Focus on these aspects:
- Trigger selection (webhook, manual, schedule)
- Agent definitions (if AI agents are involved)
- Data flow between steps
- Branching logic (if any)
- Error handling requirements
- Test case generation

Respond with JSON:
{
    "subtasks": [
        {
            "type": "choose_trigger|define_agents|define_data_contracts|select_n8n_nodes|define_error_handling|generate_tests|define_layout",
            "name": "Task name",
            "description": "What needs to be done",
            "details": {
                // Task-specific details
            },
            "depends_on_types": ["list of task types this depends on"],
            "priority": 1-10 (higher = more important)
        }
    ],
    "parallelizable_groups": [
        ["task_type_1", "task_type_2"]  // Tasks that can run in parallel
    ],
    "workflow_structure": {
        "trigger_type": "webhook|manual|schedule",
        "has_branching": true|false,
        "branch_count": 0,
        "agent_count": 0,
        "needs_merge": true|false
    }
}"""


class Planner:
    """Planner stage of the ROMA pipeline.
    
    Responsibilities:
    - Decompose complex tasks into subtasks
    - Determine task dependencies
    - Identify parallelization opportunities
    - Assign execution priorities
    """
    
    def __init__(self):
        self.llm = get_llm_adapter()
    
    async def plan(self, tree: TaskTree) -> TaskTree:
        """Plan the execution of a task tree.
        
        Enriches the task tree with:
        - Detailed subtask specifications
        - Dependency relationships
        - Priority ordering
        """
        logger.info("planner_start", task_count=len(tree.tasks))
        
        # Use LLM to generate detailed plan
        response = await self.llm.generate(
            system_prompt=PLANNING_PROMPT,
            user_message=f"""Plan the workflow synthesis for:

{tree.root_prompt}

Current task tree has these high-level tasks:
{[{"type": t.type.value, "name": t.name} for t in tree.tasks]}

Provide detailed subtask specifications.""",
            response_format="json",
            temperature=0.4,
        )
        
        plan_data = response.content
        
        # Enrich existing tasks with planning details
        tree = self._enrich_tasks(tree, plan_data)
        
        # Add any missing subtasks
        tree = self._add_missing_subtasks(tree, plan_data)
        
        # Resolve dependencies
        tree = self._resolve_dependencies(tree, plan_data)
        
        # Set priorities
        tree = self._set_priorities(tree, plan_data)
        
        logger.info(
            "planner_complete",
            final_task_count=len(tree.tasks),
            parallelizable_groups=plan_data.get("parallelizable_groups", []),
        )
        
        return tree
    
    def _enrich_tasks(self, tree: TaskTree, plan_data: dict) -> TaskTree:
        """Enrich existing tasks with planning details."""
        
        subtasks_by_type = {
            s["type"]: s
            for s in plan_data.get("subtasks", [])
        }
        
        for task in tree.tasks:
            type_key = task.type.value
            if type_key in subtasks_by_type:
                details = subtasks_by_type[type_key]
                task.input_data = {
                    **task.input_data,
                    "planning_details": details.get("details", {}),
                }
                if details.get("description"):
                    task.description = details["description"]
        
        return tree
    
    def _add_missing_subtasks(self, tree: TaskTree, plan_data: dict) -> TaskTree:
        """Add any subtasks identified by planning that weren't in the original tree."""
        
        existing_types = {task.type for task in tree.tasks}
        
        type_mapping = {
            "choose_trigger": SubtaskType.CHOOSE_TRIGGER,
            "define_agents": SubtaskType.DEFINE_AGENTS,
            "define_data_contracts": SubtaskType.DEFINE_DATA_CONTRACTS,
            "select_n8n_nodes": SubtaskType.SELECT_N8N_NODES,
            "define_error_handling": SubtaskType.DEFINE_ERROR_HANDLING,
            "generate_tests": SubtaskType.GENERATE_TESTS,
            "define_layout": SubtaskType.DEFINE_LAYOUT,
        }
        
        for subtask in plan_data.get("subtasks", []):
            subtask_type = type_mapping.get(subtask["type"])
            if subtask_type and subtask_type not in existing_types:
                new_task = TaskNode(
                    type=subtask_type,
                    name=subtask.get("name", subtask["type"]),
                    description=subtask.get("description", ""),
                    input_data={"planning_details": subtask.get("details", {})},
                    priority=subtask.get("priority", 5),
                )
                tree.tasks.append(new_task)
                existing_types.add(subtask_type)
        
        return tree
    
    def _resolve_dependencies(self, tree: TaskTree, plan_data: dict) -> TaskTree:
        """Resolve task dependencies based on planning output."""
        
        # Build type -> task ID mapping
        type_to_id = {task.type.value: task.id for task in tree.tasks}
        
        # Process dependency specifications from plan
        subtasks_by_type = {
            s["type"]: s
            for s in plan_data.get("subtasks", [])
        }
        
        for task in tree.tasks:
            type_key = task.type.value
            if type_key in subtasks_by_type:
                depends_on_types = subtasks_by_type[type_key].get("depends_on_types", [])
                for dep_type in depends_on_types:
                    if dep_type in type_to_id:
                        dep_id = type_to_id[dep_type]
                        if dep_id not in task.depends_on:
                            task.depends_on.append(dep_id)
        
        # Ensure logical ordering if not specified
        # Trigger -> Agents -> Data Contracts -> Nodes -> Error Handling -> Tests -> Layout
        logical_order = [
            SubtaskType.CHOOSE_TRIGGER,
            SubtaskType.DEFINE_AGENTS,
            SubtaskType.DEFINE_DATA_CONTRACTS,
            SubtaskType.SELECT_N8N_NODES,
            SubtaskType.DEFINE_ERROR_HANDLING,
            SubtaskType.GENERATE_TESTS,
            SubtaskType.DEFINE_LAYOUT,
        ]
        
        tasks_by_type = {task.type: task for task in tree.tasks}
        
        for i, task_type in enumerate(logical_order[1:], 1):
            if task_type in tasks_by_type:
                task = tasks_by_type[task_type]
                # Add dependency on previous task type if it exists and not already dependent
                prev_type = logical_order[i - 1]
                if prev_type in tasks_by_type:
                    prev_id = tasks_by_type[prev_type].id
                    if prev_id not in task.depends_on:
                        task.depends_on.append(prev_id)
        
        return tree
    
    def _set_priorities(self, tree: TaskTree, plan_data: dict) -> TaskTree:
        """Set task priorities based on planning output and logical order."""
        
        subtasks_by_type = {
            s["type"]: s
            for s in plan_data.get("subtasks", [])
        }
        
        # Default priorities by type
        default_priorities = {
            SubtaskType.CHOOSE_TRIGGER: 10,
            SubtaskType.DEFINE_AGENTS: 9,
            SubtaskType.DEFINE_DATA_CONTRACTS: 8,
            SubtaskType.SELECT_N8N_NODES: 7,
            SubtaskType.DEFINE_ERROR_HANDLING: 6,
            SubtaskType.GENERATE_TESTS: 5,
            SubtaskType.DEFINE_LAYOUT: 4,
        }
        
        for task in tree.tasks:
            type_key = task.type.value
            if type_key in subtasks_by_type:
                task.priority = subtasks_by_type[type_key].get("priority", 5)
            elif task.type in default_priorities:
                task.priority = default_priorities[task.type]
        
        return tree
    
    def get_next_tasks(self, tree: TaskTree) -> list[TaskNode]:
        """Get the next tasks ready for execution.
        
        Returns tasks that:
        - Are pending
        - Have all dependencies satisfied
        - Sorted by priority (highest first)
        """
        ready = tree.get_ready_tasks()
        return sorted(ready, key=lambda t: t.priority, reverse=True)
    
    def can_parallelize(
        self,
        tasks: list[TaskNode],
        plan_data: Optional[dict] = None,
    ) -> list[list[TaskNode]]:
        """Group tasks that can be executed in parallel.
        
        Returns groups of tasks where tasks within a group have no
        dependencies on each other.
        """
        if not tasks:
            return []
        
        # Simple grouping: tasks at the same "level" can parallelize
        # A task's level is determined by its maximum dependency depth
        task_levels: dict[UUID, int] = {}
        
        def get_level(task: TaskNode, visited: set) -> int:
            if task.id in task_levels:
                return task_levels[task.id]
            if task.id in visited:
                return 0  # Cycle detected, shouldn't happen
            
            visited.add(task.id)
            
            if not task.depends_on:
                level = 0
            else:
                dep_levels = []
                for dep_id in task.depends_on:
                    dep_task = next((t for t in tasks if t.id == dep_id), None)
                    if dep_task:
                        dep_levels.append(get_level(dep_task, visited))
                level = max(dep_levels, default=-1) + 1
            
            task_levels[task.id] = level
            return level
        
        for task in tasks:
            get_level(task, set())
        
        # Group by level
        level_groups: dict[int, list[TaskNode]] = {}
        for task in tasks:
            level = task_levels.get(task.id, 0)
            if level not in level_groups:
                level_groups[level] = []
            level_groups[level].append(task)
        
        return [
            level_groups[level]
            for level in sorted(level_groups.keys())
        ]
