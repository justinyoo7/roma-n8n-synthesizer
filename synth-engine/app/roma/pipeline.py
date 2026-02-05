"""ROMA Pipeline - Orchestrates the full synthesis process.

The pipeline coordinates:
1. Atomizer - Complexity analysis and initial structure
2. Planner - Task decomposition
3. Executor Pool - Artifact generation
4. Aggregator - Merge into WorkflowIR
5. Verifier - Validation and testing
6. Simplifier - Post-pass optimization

Supports iteration cycles when verification fails.
"""
from typing import Optional
from uuid import UUID, uuid4

import structlog

from app.models.workflow_ir import WorkflowIR
from app.models.task_tree import (
    TaskTree,
    SynthesisResult,
    IterationResult,
    SubtaskType,
)
from app.roma.atomizer import Atomizer
from app.roma.planner import Planner
from app.roma.executor import ExecutorPool
from app.roma.aggregator import Aggregator
from app.roma.verifier import Verifier
from app.roma.simplifier import Simplifier
from app.n8n.compiler import N8NCompiler
from app.testing.harness import TestHarness

logger = structlog.get_logger()


class ROMAPipeline:
    """Main orchestrator for the ROMA synthesis pipeline."""
    
    def __init__(self):
        self.atomizer = Atomizer()
        self.planner = Planner()
        self.executor_pool = ExecutorPool()
        self.aggregator = Aggregator()
        self.verifier = Verifier()
        self.simplifier = Simplifier()
        self.compiler = N8NCompiler()
        self.test_harness = TestHarness()
    
    async def synthesize(
        self,
        prompt: str,
        workflow_id: Optional[UUID] = None,
        previous_iteration_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> SynthesisResult:
        """Run the full synthesis pipeline.
        
        Args:
            prompt: Natural language workflow description
            workflow_id: Existing workflow ID (for refinement)
            previous_iteration_id: Previous iteration to build on
            user_id: User ID for tracking
            
        Returns:
            SynthesisResult with WorkflowIR, n8n JSON, and metadata
        """
        logger.info(
            "pipeline_start",
            prompt_length=len(prompt),
            workflow_id=str(workflow_id) if workflow_id else None,
        )
        
        # Generate IDs
        if not workflow_id:
            workflow_id = uuid4()
        iteration_id = uuid4()
        iteration_version = 1
        
        # Step 1: Atomizer - Analyze complexity
        is_atomic, analysis = await self.atomizer.analyze(prompt, workflow_id=workflow_id)
        
        if is_atomic:
            # Direct synthesis for simple workflows
            logger.info("atomic_synthesis")
            workflow_ir = await self.atomizer.generate_atomic_workflow(prompt, workflow_id=workflow_id)
            task_tree = None
        else:
            # Decomposition for complex workflows
            logger.info("composite_synthesis")
            
            # Create initial task tree
            task_tree = await self.atomizer.create_task_tree(prompt, analysis)
            
            # Step 2: Planner - Decompose into subtasks
            task_tree = await self.planner.plan(task_tree)
            
            # Step 3: Executor Pool - Generate artifacts
            context = {
                "prompt": prompt,
                "analysis": analysis,
                "workflow_id": workflow_id,
            }
            
            # Execute tasks in dependency order
            max_iterations = len(task_tree.tasks) + 5  # Safety limit
            iteration_count = 0
            
            while not task_tree.is_complete() and iteration_count < max_iterations:
                iteration_count += 1
                ready_tasks = self.planner.get_next_tasks(task_tree)
                
                logger.info(
                    "task_execution_loop",
                    iteration=iteration_count,
                    ready_count=len(ready_tasks),
                    completed_count=len(task_tree.completed_task_ids),
                    total_tasks=len(task_tree.tasks),
                )
                
                if not ready_tasks:
                    # No ready tasks but not complete - check for stuck tasks
                    pending = [t for t in task_tree.tasks if t.status.value == "pending"]
                    if pending:
                        logger.warning(
                            "no_ready_tasks_but_pending",
                            pending_count=len(pending),
                            pending_types=[t.type.value for t in pending],
                        )
                        # Force execute the first pending task if stuck
                        ready_tasks = [pending[0]]
                    else:
                        break
                
                # Execute ready tasks (possibly in parallel)
                parallel_groups = self.planner.can_parallelize(ready_tasks)
                
                for group in parallel_groups:
                    if len(group) > 1:
                        # Parallel execution
                        results = await self.executor_pool.execute_parallel(
                            group,
                            context,
                        )
                        for task_id, artifacts in results.items():
                            task_tree.mark_completed(UUID(task_id), artifacts)
                            # Update context with artifacts
                            self._update_context(context, artifacts)
                    else:
                        # Sequential execution
                        for task in group:
                            try:
                                artifacts = await self.executor_pool.execute(
                                    task,
                                    context,
                                )
                                task_tree.mark_completed(task.id, artifacts)
                                self._update_context(context, artifacts)
                            except Exception as e:
                                logger.error(
                                    "task_execution_failed",
                                    task_type=task.type.value,
                                    error=str(e),
                                )
                                task_tree.mark_failed(task.id, str(e))
            
            # Step 4: Aggregator - Merge artifacts into WorkflowIR
            workflow_ir = self.aggregator.aggregate(task_tree, prompt)
            task_tree.final_workflow_ir = workflow_ir
        
        # Step 5: Verifier - Validate, compile, and test
        verification = await self.verifier.verify(
            workflow_ir=workflow_ir,
            iteration_id=iteration_id,
            push_to_n8n=True,
            run_tests=True,
        )
        
        # Compile n8n JSON
        n8n_json = verification.n8n_json or self.compiler.compile(workflow_ir)
        
        # Generate test plan
        test_plan = await self.test_harness.generate_test_suite(workflow_ir)
        
        # Calculate score
        score, score_breakdown = self._calculate_score(
            workflow_ir,
            verification,
        )
        
        # Build rationale
        rationale = self._build_rationale(analysis, task_tree)
        
        logger.info(
            "pipeline_complete",
            workflow_id=str(workflow_id),
            iteration_id=str(iteration_id),
            score=score,
            verified=verification.all_valid,
        )
        
        return SynthesisResult(
            workflow_id=workflow_id,
            iteration_id=iteration_id,
            iteration_version=iteration_version,
            workflow_ir=workflow_ir,
            n8n_json=n8n_json,
            rationale=rationale,
            test_plan=test_plan,
            task_tree=task_tree,
            score=score,
            score_breakdown=score_breakdown,
        )
    
    async def iterate(
        self,
        workflow_id: UUID,
        iteration_id: UUID,
        failure_traces: list[dict],
        user_feedback: Optional[str] = None,
    ) -> IterationResult:
        """Iterate on a workflow based on failures or feedback.
        
        Args:
            workflow_id: Workflow to iterate on
            iteration_id: Current iteration
            failure_traces: Test failures to address
            user_feedback: Optional user guidance
            
        Returns:
            IterationResult with improved WorkflowIR
        """
        logger.info(
            "iteration_start",
            workflow_id=str(workflow_id),
            failure_count=len(failure_traces),
        )
        
        # In a real implementation, we would:
        # 1. Load the previous iteration from database
        # 2. Analyze failures to generate a FixPlan
        # 3. Route fixes through appropriate modules
        # 4. Generate new iteration
        
        # For now, return a placeholder
        raise NotImplementedError("Iteration requires database access")
    
    def _update_context(self, context: dict, artifacts: list) -> None:
        """Update execution context with new artifacts."""
        
        for artifact in artifacts:
            if artifact.type == SubtaskType.CHOOSE_TRIGGER:
                context["trigger"] = artifact.content
            elif artifact.type == SubtaskType.DEFINE_AGENTS:
                context["agents"] = artifact.content.get("agents", [])
            elif artifact.type == SubtaskType.DEFINE_DATA_CONTRACTS:
                context["contracts"] = artifact.content.get("contracts", [])
            elif artifact.type == SubtaskType.SELECT_N8N_NODES:
                context["nodes"] = artifact.content.get("node_selections", [])
            elif artifact.type == SubtaskType.DEFINE_ERROR_HANDLING:
                context["error_strategy"] = artifact.content.get("error_strategy", {})
            elif artifact.type == SubtaskType.GENERATE_TESTS:
                context["tests"] = artifact.content.get("tests", [])
            elif artifact.type == SubtaskType.DEFINE_LAYOUT:
                context["layout"] = artifact.content.get("positions", {})
    
    def _calculate_score(
        self,
        workflow_ir: WorkflowIR,
        verification,
    ) -> tuple[int, dict]:
        """Calculate workflow quality score.
        
        Score components:
        - Correctness (50%): Tests passing
        - Simplicity (25%): Node/edge count
        - Clarity (15%): Naming quality
        - Robustness (10%): Error handling
        """
        # Correctness: All tests passing
        if verification.test_results:
            passed = sum(1 for t in verification.test_results if t.passed)
            total = len(verification.test_results)
            correctness = (passed / total) * 50 if total > 0 else 0
        else:
            correctness = 25  # Partial credit if no tests
        
        # Simplicity: Fewer nodes = better
        node_count = len(workflow_ir.steps) + 1  # +1 for trigger
        if node_count <= 3:
            simplicity = 25
        elif node_count <= 6:
            simplicity = 20
        elif node_count <= 10:
            simplicity = 15
        else:
            simplicity = max(5, 25 - (node_count - 3) * 2)
        
        # Clarity: Check naming
        clarity = 15  # Full marks by default
        for step in workflow_ir.steps:
            if not step.description:
                clarity -= 1
            if step.name.startswith("Step "):
                clarity -= 1
        clarity = max(0, clarity)
        
        # Robustness: Error handling present
        robustness = 5
        if workflow_ir.error_strategy.retry_config:
            robustness = 10
        
        total = int(correctness + simplicity + clarity + robustness)
        
        return total, {
            "correctness": int(correctness),
            "simplicity": simplicity,
            "clarity": clarity,
            "robustness": robustness,
        }
    
    def _build_rationale(
        self,
        analysis: dict,
        task_tree: Optional[TaskTree],
    ) -> str:
        """Build human-readable rationale for synthesis decisions."""
        
        parts = []
        
        # Complexity assessment
        complexity = analysis.get("complexity", "unknown")
        parts.append(f"Workflow assessed as {complexity}.")
        
        reasoning = analysis.get("reasoning", "")
        if reasoning:
            parts.append(reasoning)
        
        # Components identified
        components = analysis.get("key_components", [])
        if components:
            parts.append(f"Identified components: {', '.join(components)}.")
        
        # Task tree summary
        if task_tree:
            completed = len(task_tree.completed_task_ids)
            total = len(task_tree.tasks)
            parts.append(f"Executed {completed}/{total} planning tasks.")
        
        return " ".join(parts)
