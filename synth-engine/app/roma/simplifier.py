"""Simplifier - Post-pass optimization stage.

The Simplifier attempts to reduce workflow complexity while preserving
behavior. It applies simplification strategies iteratively, re-running
tests after each change to ensure correctness.
"""
from typing import Optional
from uuid import UUID, uuid4
from copy import deepcopy

import structlog

from app.models.workflow_ir import WorkflowIR, StepSpec, StepType
from app.models.task_tree import SimplificationResult
from app.n8n.compiler import N8NCompiler
from app.testing.harness import TestHarness

logger = structlog.get_logger()


class SimplificationStrategy:
    """Base class for simplification strategies."""
    
    name: str = "base"
    
    def can_apply(self, workflow_ir: WorkflowIR) -> bool:
        """Check if this strategy can be applied."""
        return False
    
    def apply(self, workflow_ir: WorkflowIR) -> tuple[WorkflowIR, str]:
        """Apply the simplification.
        
        Returns:
            Tuple of (modified WorkflowIR, description of change)
        """
        return workflow_ir, "No change"


class RemovePassthroughNodes(SimplificationStrategy):
    """Remove nodes that just pass data through without modification."""
    
    name = "remove_passthrough"
    
    def can_apply(self, workflow_ir: WorkflowIR) -> bool:
        for step in workflow_ir.steps:
            if self._is_passthrough(step):
                return True
        return False
    
    def _is_passthrough(self, step: StepSpec) -> bool:
        """Check if a step is a passthrough node."""
        # NoOp nodes are always passthrough
        if step.n8n_node_type == "n8n-nodes-base.noOp":
            return True
        
        # Set nodes with no assignments are passthrough
        if step.n8n_node_type == "n8n-nodes-base.set":
            assignments = step.parameters.get("assignments", {})
            if not assignments or not assignments.get("assignments"):
                return True
        
        return False
    
    def apply(self, workflow_ir: WorkflowIR) -> tuple[WorkflowIR, str]:
        ir = deepcopy(workflow_ir)
        removed = []
        
        for step in list(ir.steps):
            if self._is_passthrough(step):
                # Rewire edges around this node
                incoming = [e for e in ir.edges if e.target_id == step.id]
                outgoing = [e for e in ir.edges if e.source_id == step.id]
                
                # Connect incoming sources directly to outgoing targets
                new_edges = []
                for inc in incoming:
                    for out in outgoing:
                        # Create bypass edge
                        new_edge = deepcopy(inc)
                        new_edge.id = str(uuid4())[:8]
                        new_edge.target_id = out.target_id
                        new_edges.append(new_edge)
                
                # Remove old edges
                ir.edges = [
                    e for e in ir.edges
                    if e.target_id != step.id and e.source_id != step.id
                ]
                ir.edges.extend(new_edges)
                
                # Remove node
                ir.steps = [s for s in ir.steps if s.id != step.id]
                removed.append(step.name)
        
        description = f"Removed passthrough nodes: {', '.join(removed)}" if removed else "No passthrough nodes found"
        return ir, description


class MergeConsecutiveTransforms(SimplificationStrategy):
    """Merge consecutive transform/set nodes into one."""
    
    name = "merge_transforms"
    
    def can_apply(self, workflow_ir: WorkflowIR) -> bool:
        # Check for consecutive set/transform nodes
        for step in workflow_ir.steps:
            if step.n8n_node_type != "n8n-nodes-base.set":
                continue
            
            # Find downstream steps
            downstream = [
                e.target_id for e in workflow_ir.edges
                if e.source_id == step.id
            ]
            
            for target_id in downstream:
                target = workflow_ir.get_step_by_id(target_id)
                if target and target.n8n_node_type == "n8n-nodes-base.set":
                    # Check if target has only this one input
                    inputs = [e for e in workflow_ir.edges if e.target_id == target_id]
                    if len(inputs) == 1:
                        return True
        
        return False
    
    def apply(self, workflow_ir: WorkflowIR) -> tuple[WorkflowIR, str]:
        ir = deepcopy(workflow_ir)
        merged = []
        
        # Find mergeable pairs
        for step in list(ir.steps):
            if step.n8n_node_type != "n8n-nodes-base.set":
                continue
            
            downstream_edges = [
                e for e in ir.edges
                if e.source_id == step.id
            ]
            
            for edge in downstream_edges:
                target = ir.get_step_by_id(edge.target_id)
                if not target or target.n8n_node_type != "n8n-nodes-base.set":
                    continue
                
                # Check target has single input
                inputs = [e for e in ir.edges if e.target_id == target.id]
                if len(inputs) != 1:
                    continue
                
                # Merge assignments
                step_assignments = step.parameters.get("assignments", {}).get("assignments", [])
                target_assignments = target.parameters.get("assignments", {}).get("assignments", [])
                
                merged_assignments = step_assignments + target_assignments
                step.parameters["assignments"] = {"assignments": merged_assignments}
                step.name = f"{step.name} + {target.name}"
                
                # Rewire edges
                target_outgoing = [e for e in ir.edges if e.source_id == target.id]
                for out_edge in target_outgoing:
                    out_edge.source_id = step.id
                
                # Remove merge edge and target
                ir.edges = [e for e in ir.edges if e.target_id != target.id]
                ir.steps = [s for s in ir.steps if s.id != target.id]
                
                merged.append(f"{step.name}")
                break  # One merge at a time
        
        description = f"Merged transform nodes: {', '.join(merged)}" if merged else "No transforms merged"
        return ir, description


class RemoveUnusedBranches(SimplificationStrategy):
    """Remove branches that are never taken or have empty outputs."""
    
    name = "remove_unused_branches"
    
    def can_apply(self, workflow_ir: WorkflowIR) -> bool:
        for step in workflow_ir.steps:
            if step.type == StepType.BRANCH:
                # Check if all branches have targets
                outgoing = [e for e in workflow_ir.edges if e.source_id == step.id]
                if len(outgoing) < 2:
                    return True
        return False
    
    def apply(self, workflow_ir: WorkflowIR) -> tuple[WorkflowIR, str]:
        ir = deepcopy(workflow_ir)
        simplified = []
        
        for step in list(ir.steps):
            if step.type != StepType.BRANCH:
                continue
            
            outgoing = [e for e in ir.edges if e.source_id == step.id]
            
            # If only one branch, convert to passthrough
            if len(outgoing) == 1:
                step.type = StepType.ACTION
                step.n8n_node_type = "n8n-nodes-base.noOp"
                step.parameters = {}
                step.branch_conditions = None
                simplified.append(step.name)
        
        description = f"Simplified branches: {', '.join(simplified)}" if simplified else "No branches simplified"
        return ir, description


class Simplifier:
    """Simplifier stage - reduces workflow complexity while preserving behavior."""
    
    def __init__(self):
        self.compiler = N8NCompiler()
        self.test_harness = TestHarness()
        self.strategies: list[SimplificationStrategy] = [
            RemovePassthroughNodes(),
            MergeConsecutiveTransforms(),
            RemoveUnusedBranches(),
        ]
    
    async def simplify(
        self,
        workflow_id: UUID,
        iteration_id: UUID,
        preserve_tests: bool = True,
        max_iterations: int = 10,
    ) -> SimplificationResult:
        """Simplify a workflow while preserving test behavior.
        
        Args:
            workflow_id: The workflow to simplify
            iteration_id: Current iteration ID
            preserve_tests: Whether to verify tests still pass
            max_iterations: Maximum simplification iterations
            
        Returns:
            SimplificationResult with the simplified workflow
        """
        # For now, we need to load the workflow from storage
        # This would come from Supabase in the real implementation
        raise NotImplementedError("Simplifier requires database access")
    
    async def simplify_ir(
        self,
        workflow_ir: WorkflowIR,
        iteration_id: UUID,
        preserve_tests: bool = True,
        max_iterations: int = 10,
    ) -> SimplificationResult:
        """Simplify a WorkflowIR directly.
        
        This is the core simplification logic.
        """
        logger.info(
            "simplifier_start",
            workflow_name=workflow_ir.name,
            initial_nodes=len(workflow_ir.steps) + 1,
        )
        
        original_node_count = len(workflow_ir.steps) + 1
        original_edge_count = len(workflow_ir.edges)
        
        # Calculate original score
        original_score = self._calculate_simplicity_score(workflow_ir)
        
        current_ir = deepcopy(workflow_ir)
        simplifications_applied = []
        iterations = 0
        
        while iterations < max_iterations:
            iterations += 1
            applied_this_round = False
            
            for strategy in self.strategies:
                if not strategy.can_apply(current_ir):
                    continue
                
                # Apply simplification
                candidate_ir, description = strategy.apply(current_ir)
                
                if preserve_tests:
                    # Verify tests still pass
                    try:
                        test_results = await self.test_harness.run_tests(
                            workflow_ir=candidate_ir,
                            n8n_workflow_id=None,  # Run locally
                        )
                        
                        if all(t.passed for t in test_results):
                            current_ir = candidate_ir
                            simplifications_applied.append(f"{strategy.name}: {description}")
                            applied_this_round = True
                            logger.info(
                                "simplification_applied",
                                strategy=strategy.name,
                                description=description,
                            )
                        else:
                            logger.info(
                                "simplification_rejected",
                                strategy=strategy.name,
                                reason="Tests failed",
                            )
                    except Exception as e:
                        logger.warning(
                            "simplification_test_error",
                            strategy=strategy.name,
                            error=str(e),
                        )
                else:
                    # Apply without test verification
                    current_ir = candidate_ir
                    simplifications_applied.append(f"{strategy.name}: {description}")
                    applied_this_round = True
            
            if not applied_this_round:
                break
        
        # Calculate final metrics
        final_node_count = len(current_ir.steps) + 1
        final_edge_count = len(current_ir.edges)
        new_score = self._calculate_simplicity_score(current_ir)
        
        # Compile final result
        n8n_json = self.compiler.compile(current_ir)
        
        logger.info(
            "simplifier_complete",
            nodes_removed=original_node_count - final_node_count,
            edges_removed=original_edge_count - final_edge_count,
            simplifications=len(simplifications_applied),
        )
        
        return SimplificationResult(
            iteration_id=uuid4(),
            iteration_version=1,
            workflow_ir=current_ir,
            n8n_json=n8n_json,
            simplifications_applied=simplifications_applied,
            nodes_removed=original_node_count - final_node_count,
            edges_removed=original_edge_count - final_edge_count,
            original_score=original_score,
            new_score=new_score,
        )
    
    def _calculate_simplicity_score(self, workflow_ir: WorkflowIR) -> int:
        """Calculate a simplicity score for the workflow.
        
        Higher score = simpler workflow.
        """
        base_score = 100
        
        # Penalize for number of steps
        step_penalty = len(workflow_ir.steps) * 3
        
        # Penalize for branches
        branch_count = sum(
            1 for step in workflow_ir.steps
            if step.type == StepType.BRANCH
        )
        branch_penalty = branch_count * 5
        
        # Penalize for complex edges
        edge_penalty = max(0, len(workflow_ir.edges) - len(workflow_ir.steps)) * 2
        
        return max(0, base_score - step_penalty - branch_penalty - edge_penalty)
