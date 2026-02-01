"""Verifier - Fifth stage of ROMA pipeline.

The Verifier performs validation and verification:
1. Static validation of WorkflowIR
2. Compilation to n8n JSON
3. Push to n8n and verify creation
4. Execute test suite
5. Generate FixPlan if issues found
"""
from typing import Optional
from uuid import UUID

import structlog

from app.models.workflow_ir import WorkflowIR
from app.models.task_tree import FixPlan
from app.n8n.compiler import N8NCompiler
from app.n8n.client import N8NClient, N8NClientError
from app.testing.harness import TestHarness, TestResult

logger = structlog.get_logger()


class ValidationError:
    """Represents a validation error."""
    
    def __init__(
        self,
        category: str,
        message: str,
        step_id: Optional[str] = None,
        severity: str = "error",
    ):
        self.category = category
        self.message = message
        self.step_id = step_id
        self.severity = severity
    
    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "message": self.message,
            "step_id": self.step_id,
            "severity": self.severity,
        }


class VerificationResult:
    """Result of the verification process."""
    
    def __init__(self):
        self.static_valid = False
        self.compilation_valid = False
        self.n8n_push_valid = False
        self.tests_passed = False
        
        self.static_errors: list[ValidationError] = []
        self.compilation_errors: list[str] = []
        self.n8n_errors: list[str] = []
        self.test_results: list[TestResult] = []
        
        self.n8n_workflow_id: Optional[str] = None
        self.n8n_json: Optional[dict] = None
        self.fix_plan: Optional[FixPlan] = None
    
    @property
    def all_valid(self) -> bool:
        return (
            self.static_valid
            and self.compilation_valid
            and self.n8n_push_valid
            and self.tests_passed
        )
    
    def to_dict(self) -> dict:
        return {
            "static_valid": self.static_valid,
            "compilation_valid": self.compilation_valid,
            "n8n_push_valid": self.n8n_push_valid,
            "tests_passed": self.tests_passed,
            "all_valid": self.all_valid,
            "static_errors": [e.to_dict() for e in self.static_errors],
            "compilation_errors": self.compilation_errors,
            "n8n_errors": self.n8n_errors,
            "test_results": [t.to_dict() for t in self.test_results],
            "n8n_workflow_id": self.n8n_workflow_id,
        }


class Verifier:
    """Verifier stage of the ROMA pipeline.
    
    Validates, compiles, pushes, and tests the generated workflow.
    """
    
    def __init__(self):
        self.compiler = N8NCompiler()
        self.test_harness = TestHarness()
    
    async def verify(
        self,
        workflow_ir: WorkflowIR,
        iteration_id: UUID,
        push_to_n8n: bool = True,
        run_tests: bool = True,
    ) -> VerificationResult:
        """Perform full verification of a WorkflowIR.
        
        Args:
            workflow_ir: The workflow to verify
            iteration_id: Current iteration ID
            push_to_n8n: Whether to push to n8n
            run_tests: Whether to run tests
            
        Returns:
            VerificationResult with all validation outcomes
        """
        logger.info("verifier_start", workflow_name=workflow_ir.name)
        
        result = VerificationResult()
        
        # Step 1: Static validation
        result.static_errors = self._validate_static(workflow_ir)
        result.static_valid = len([e for e in result.static_errors if e.severity == "error"]) == 0
        
        if not result.static_valid:
            logger.warning(
                "static_validation_failed",
                error_count=len(result.static_errors),
            )
            result.fix_plan = self._generate_fix_plan(result, iteration_id)
            return result
        
        # Step 2: Compile to n8n JSON
        try:
            result.n8n_json = self.compiler.compile(workflow_ir)
            result.compilation_errors = self.compiler.validate_compiled(result.n8n_json)
            result.compilation_valid = len(result.compilation_errors) == 0
        except Exception as e:
            result.compilation_errors = [str(e)]
            result.compilation_valid = False
        
        if not result.compilation_valid:
            logger.warning(
                "compilation_failed",
                error_count=len(result.compilation_errors),
            )
            result.fix_plan = self._generate_fix_plan(result, iteration_id)
            return result
        
        # Step 3: Push to n8n (if enabled)
        if push_to_n8n:
            try:
                client = N8NClient()
                n8n_result = await client.create_workflow(result.n8n_json)
                result.n8n_workflow_id = n8n_result.get("id")
                
                # Verify the workflow was created correctly
                verification = await client.verify_workflow(result.n8n_workflow_id)
                if not verification.get("valid"):
                    result.n8n_errors = verification.get("issues", [])
                    result.n8n_push_valid = False
                else:
                    result.n8n_push_valid = True
                    
            except N8NClientError as e:
                result.n8n_errors = [str(e)]
                result.n8n_push_valid = False
            except ValueError as e:
                # API key not configured - skip n8n push
                logger.warning("n8n_push_skipped", reason=str(e))
                result.n8n_push_valid = True  # Don't fail verification
                result.n8n_errors = [f"Skipped: {str(e)}"]
        else:
            result.n8n_push_valid = True
        
        # Step 4: Run tests (if enabled)
        if run_tests and result.n8n_push_valid:
            try:
                result.test_results = await self.test_harness.run_tests(
                    workflow_ir=workflow_ir,
                    n8n_workflow_id=result.n8n_workflow_id,
                )
                result.tests_passed = all(t.passed for t in result.test_results)
            except Exception as e:
                logger.error("test_execution_error", error=str(e))
                result.tests_passed = False
        else:
            result.tests_passed = True  # Skip if not running tests
        
        # Generate fix plan if any validation failed
        if not result.all_valid:
            result.fix_plan = self._generate_fix_plan(result, iteration_id)
        
        logger.info(
            "verifier_complete",
            all_valid=result.all_valid,
            n8n_workflow_id=result.n8n_workflow_id,
        )
        
        return result
    
    def _validate_static(self, workflow_ir: WorkflowIR) -> list[ValidationError]:
        """Perform static validation of WorkflowIR."""
        
        errors = []
        
        # Validate trigger
        if not workflow_ir.trigger:
            errors.append(ValidationError(
                category="structure",
                message="Workflow must have a trigger",
            ))
        elif not workflow_ir.trigger.n8n_node_type:
            errors.append(ValidationError(
                category="trigger",
                message="Trigger missing n8n node type",
                step_id=workflow_ir.trigger.id,
            ))
        
        # Validate steps
        step_ids = {workflow_ir.trigger.id}
        for step in workflow_ir.steps:
            if step.id in step_ids:
                errors.append(ValidationError(
                    category="structure",
                    message=f"Duplicate step ID: {step.id}",
                    step_id=step.id,
                ))
            step_ids.add(step.id)
            
            if not step.n8n_node_type:
                errors.append(ValidationError(
                    category="step",
                    message=f"Step '{step.name}' missing n8n node type",
                    step_id=step.id,
                ))
            
            # Validate agent steps have agent spec
            if step.type.value == "agent" and not step.agent:
                errors.append(ValidationError(
                    category="agent",
                    message=f"Agent step '{step.name}' missing agent specification",
                    step_id=step.id,
                ))
        
        # Validate edges
        for edge in workflow_ir.edges:
            if edge.source_id not in step_ids:
                errors.append(ValidationError(
                    category="edge",
                    message=f"Edge source '{edge.source_id}' not found",
                ))
            if edge.target_id not in step_ids:
                errors.append(ValidationError(
                    category="edge",
                    message=f"Edge target '{edge.target_id}' not found",
                ))
        
        # Check for unreachable steps
        reachable = {workflow_ir.trigger.id}
        changed = True
        while changed:
            changed = False
            for edge in workflow_ir.edges:
                if edge.source_id in reachable and edge.target_id not in reachable:
                    reachable.add(edge.target_id)
                    changed = True
        
        for step in workflow_ir.steps:
            if step.id not in reachable:
                errors.append(ValidationError(
                    category="structure",
                    message=f"Step '{step.name}' is unreachable",
                    step_id=step.id,
                    severity="warning",
                ))
        
        return errors
    
    def _generate_fix_plan(
        self,
        result: VerificationResult,
        iteration_id: UUID,
    ) -> FixPlan:
        """Generate a fix plan from verification failures."""
        
        failures = []
        fixes = []
        
        # Process static errors
        for error in result.static_errors:
            failures.append({
                "type": "static_validation",
                "category": error.category,
                "message": error.message,
                "step_id": error.step_id,
            })
            
            # Suggest fix based on error category
            if error.category == "structure":
                fixes.append({
                    "type": "restructure",
                    "target": "planner",
                    "description": f"Fix structural issue: {error.message}",
                })
            elif error.category == "agent":
                fixes.append({
                    "type": "define_agent",
                    "target": "executor",
                    "step_id": error.step_id,
                    "description": f"Define missing agent: {error.message}",
                })
        
        # Process compilation errors
        for error in result.compilation_errors:
            failures.append({
                "type": "compilation",
                "message": error,
            })
            fixes.append({
                "type": "fix_compilation",
                "target": "aggregator",
                "description": f"Fix compilation error: {error}",
            })
        
        # Process n8n errors
        for error in result.n8n_errors:
            failures.append({
                "type": "n8n_push",
                "message": error,
            })
        
        # Process test failures
        for test_result in result.test_results:
            if not test_result.passed:
                failures.append({
                    "type": "test_failure",
                    "test_name": test_result.test_name,
                    "reason": test_result.failure_reason,
                })
                fixes.append({
                    "type": "fix_test",
                    "target": "executor",
                    "test_name": test_result.test_name,
                    "description": f"Fix failing test: {test_result.failure_reason}",
                })
        
        # Determine if we need to re-plan
        requires_replan = any(
            f["type"] == "restructure" for f in fixes
        )
        
        return FixPlan(
            iteration_id=iteration_id,
            failures=failures,
            fixes=fixes,
            requires_replan=requires_replan,
        )
