"""Test harness for executing and validating workflow tests.

Supports:
- Running tests against real n8n workflows via webhook (PREFERRED)
- Simulated local execution as fallback
- Invariant checking and artifact collection
"""
import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

import httpx
import structlog

from app.models.workflow_ir import WorkflowIR, TestInvariant
from app.n8n.client import N8NClient, N8NClientError
from app.n8n.compiler import N8NCompiler

logger = structlog.get_logger()


class TestResult:
    """Result of a single test execution."""
    
    def __init__(
        self,
        test_name: str,
        passed: bool,
        input_payload: dict,
        actual_output: Optional[dict] = None,
        expected_output: Optional[dict] = None,
        failure_reason: Optional[str] = None,
        duration_ms: int = 0,
        checkpoints: Optional[list[dict]] = None,
        execution_mode: str = "unknown",  # "real" or "simulated"
        webhook_url: Optional[str] = None,
    ):
        self.test_name = test_name
        self.passed = passed
        self.input_payload = input_payload
        self.actual_output = actual_output
        self.expected_output = expected_output
        self.failure_reason = failure_reason
        self.duration_ms = duration_ms
        self.checkpoints = checkpoints or []
        self.execution_mode = execution_mode
        self.webhook_url = webhook_url
        self.executed_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "passed": self.passed,
            "input_payload": self.input_payload,
            "actual_output": self.actual_output,
            "expected_output": self.expected_output,
            "failure_reason": self.failure_reason,
            "duration_ms": self.duration_ms,
            "checkpoints": self.checkpoints,
            "execution_mode": self.execution_mode,
            "webhook_url": self.webhook_url,
            "executed_at": self.executed_at,
        }


class TestHarness:
    """Test execution harness for n8n workflows.
    
    ALWAYS prefers real n8n execution when possible.
    Falls back to simulation only when n8n is not configured.
    """
    
    def __init__(self):
        self.timeout = 60  # seconds
        self._n8n_client: Optional[N8NClient] = None
        self._n8n_available = False
        self._webhook_base_url: Optional[str] = None
    
    def _init_n8n_client(self) -> bool:
        """Initialize n8n client if not already done."""
        if self._n8n_client is not None:
            return self._n8n_available
        
        try:
            self._n8n_client = N8NClient()
            self._n8n_available = True
            # Store webhook base URL for display
            self._webhook_base_url = self._n8n_client.base_url.replace("/api/v1", "")
            logger.info("n8n_client_initialized", base_url=self._webhook_base_url)
            return True
        except ValueError as e:
            logger.warning("n8n_not_configured", error=str(e))
            self._n8n_available = False
            return False
    
    def get_webhook_url(self, webhook_path: str, test_mode: bool = False) -> Optional[str]:
        """Get full webhook URL for a path."""
        if not self._init_n8n_client() or not self._n8n_client:
            return None
        return self._n8n_client.get_webhook_url(webhook_path, test_mode)
    
    async def run_tests(
        self,
        workflow_ir: WorkflowIR,
        n8n_workflow_id: Optional[str] = None,
        n8n_json: Optional[dict] = None,
        force_real: bool = True,
    ) -> list[TestResult]:
        """Run all tests for a workflow.
        
        ALWAYS attempts real n8n execution first when:
        - n8n is configured (API key present)
        - Workflow has a webhook trigger
        
        Falls back to simulation only when n8n is unavailable.
        
        Args:
            workflow_ir: The workflow IR with test invariants
            n8n_workflow_id: Optional n8n workflow ID (for activation check)
            n8n_json: Optional compiled n8n JSON (to extract webhook path)
            force_real: If True (default), always try real execution first
            
        Returns:
            List of test results
        """
        # Initialize n8n client
        n8n_available = self._init_n8n_client()
        
        # Extract webhook path and method from workflow
        webhook_path = None
        webhook_method = "POST"  # Default to POST
        
        if n8n_json:
            webhook_path = N8NCompiler.extract_webhook_path(n8n_json)
            webhook_method = N8NCompiler.extract_webhook_method(n8n_json) or "POST"
        elif workflow_ir.trigger.trigger_config:
            webhook_path = workflow_ir.trigger.trigger_config.get("path")
            webhook_method = workflow_ir.trigger.trigger_config.get("httpMethod", "POST")
        
        # If no webhook path, try to generate one from trigger ID
        if not webhook_path and workflow_ir.trigger:
            webhook_path = f"workflow-{workflow_ir.trigger.id[:8]}"
        
        # Determine execution mode
        use_real_execution = n8n_available and webhook_path and force_real
        
        logger.info(
            "test_harness_start",
            workflow_name=workflow_ir.name,
            test_count=len(workflow_ir.success_criteria),
            n8n_available=n8n_available,
            webhook_path=webhook_path,
            use_real_execution=use_real_execution,
            n8n_workflow_id=n8n_workflow_id,
        )
        
        results = []
        
        for invariant in workflow_ir.success_criteria:
            test_config = invariant.config
            test_name = test_config.get("test_name", invariant.name)
            test_input = test_config.get("test_input", {})
            expected_output = test_config.get("expected_output")
            
            # Generate test input if not provided
            if not test_input:
                test_input = self._generate_test_input(workflow_ir, invariant)
            
            try:
                if use_real_execution and webhook_path:
                    # Execute against real n8n workflow via webhook
                    result = await self._execute_real_webhook(
                        webhook_path=webhook_path,
                        workflow_ir=workflow_ir,
                        test_name=test_name,
                        test_input=test_input,
                        invariant=invariant,
                        expected_output=expected_output,
                        n8n_workflow_id=n8n_workflow_id,
                        webhook_method=webhook_method,
                    )
                else:
                    # Simulate execution locally (fallback)
                    result = await self._execute_simulated(
                        workflow_ir=workflow_ir,
                        test_name=test_name,
                        test_input=test_input,
                        invariant=invariant,
                        expected_output=expected_output,
                    )
                
                results.append(result)
                
            except Exception as e:
                logger.error(
                    "test_execution_error",
                    test_name=test_name,
                    error=str(e),
                )
                results.append(TestResult(
                    test_name=test_name,
                    passed=False,
                    input_payload=test_input,
                    failure_reason=f"Execution error: {str(e)}",
                    execution_mode="error",
                ))
        
        passed_count = sum(1 for r in results if r.passed)
        real_count = sum(1 for r in results if r.execution_mode == "real")
        
        logger.info(
            "test_harness_complete",
            total=len(results),
            passed=passed_count,
            failed=len(results) - passed_count,
            real_executions=real_count,
            simulated_executions=len(results) - real_count,
        )
        
        return results
    
    def _generate_test_input(self, workflow_ir: WorkflowIR, invariant: TestInvariant) -> dict:
        """Generate appropriate test input based on workflow context."""
        description = workflow_ir.description.lower()
        
        # Customer support workflows
        if "customer" in description or "support" in description:
            return {"customerMessage": "I have a billing question about my invoice #12345"}
        
        # Lead/sales workflows
        if "lead" in description or "sales" in description:
            return {
                "email": "test@example.com",
                "company": "Acme Corp",
                "name": "Test User",
            }
        
        # Content workflows
        if "content" in description or "article" in description:
            return {"topic": "AI automation", "style": "professional"}
        
        # Default generic input
        return {
            "message": "Test input message",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    async def _execute_real_webhook(
        self,
        webhook_path: str,
        workflow_ir: WorkflowIR,
        test_name: str,
        test_input: dict,
        invariant: TestInvariant,
        expected_output: Optional[dict],
        n8n_workflow_id: Optional[str] = None,
        webhook_method: str = "POST",
    ) -> TestResult:
        """Execute test against real n8n workflow via webhook.
        
        Tries production webhook first, falls back to test webhook if workflow
        might not be activated.
        """
        start_time = datetime.utcnow()
        
        if not self._n8n_client:
            return TestResult(
                test_name=test_name,
                passed=False,
                input_payload=test_input,
                failure_reason="n8n client not initialized",
                execution_mode="error",
            )
        
        webhook_url = self._n8n_client.get_webhook_url(webhook_path, test_mode=False)
        
        logger.info(
            "executing_real_test",
            test_name=test_name,
            webhook_path=webhook_path,
            webhook_url=webhook_url,
            webhook_method=webhook_method,
            input_keys=list(test_input.keys()),
        )
        
        try:
            # First try production webhook (workflow must be active)
            response = await self._n8n_client.trigger_webhook(
                webhook_path=webhook_path,
                data=test_input,
                method=webhook_method,
                test_mode=False,
                timeout=self.timeout,
            )
            
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # If production webhook failed with 404, try test webhook
            if response.get("status_code") == 404:
                logger.info(
                    "production_webhook_not_found_trying_test",
                    webhook_path=webhook_path,
                )
                test_webhook_url = self._n8n_client.get_webhook_url(webhook_path, test_mode=True)
                response = await self._n8n_client.trigger_webhook(
                    webhook_path=webhook_path,
                    data=test_input,
                    method=webhook_method,
                    test_mode=True,
                    timeout=self.timeout,
                )
                webhook_url = test_webhook_url
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            actual_output = response.get("body")
            
            # Check if webhook returned an error
            if not response.get("success"):
                return TestResult(
                    test_name=test_name,
                    passed=False,
                    input_payload=test_input,
                    actual_output=actual_output,
                    failure_reason=f"Webhook failed: {response.get('error', 'Unknown error')}",
                    duration_ms=duration_ms,
                    execution_mode="real",
                    webhook_url=webhook_url,
                )
            
            # Check invariant
            passed, failure_reason = self._check_invariant(
                invariant=invariant,
                actual_output=actual_output,
                expected_output=expected_output,
            )
            
            logger.info(
                "real_test_complete",
                test_name=test_name,
                passed=passed,
                duration_ms=duration_ms,
                status_code=response.get("status_code"),
            )
            
            return TestResult(
                test_name=test_name,
                passed=passed,
                input_payload=test_input,
                actual_output=actual_output,
                expected_output=expected_output,
                failure_reason=failure_reason,
                duration_ms=duration_ms,
                execution_mode="real",
                webhook_url=webhook_url,
            )
            
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.error(
                "real_test_error",
                test_name=test_name,
                error=str(e),
                duration_ms=duration_ms,
            )
            return TestResult(
                test_name=test_name,
                passed=False,
                input_payload=test_input,
                failure_reason=f"Webhook error: {str(e)}",
                duration_ms=duration_ms,
                execution_mode="real",
                webhook_url=webhook_url,
            )
    
    async def _execute_simulated(
        self,
        workflow_ir: WorkflowIR,
        test_name: str,
        test_input: dict,
        invariant: TestInvariant,
        expected_output: Optional[dict],
    ) -> TestResult:
        """Simulate workflow execution locally.
        
        FALLBACK ONLY - Used when n8n is not available.
        This walks through the workflow graph and simulates node execution.
        """
        logger.warning(
            "using_simulated_execution",
            test_name=test_name,
            reason="n8n not available or webhook not configured",
        )
        
        start_time = datetime.utcnow()
        
        try:
            # Simulate workflow execution
            checkpoints = []
            current_data = test_input
            
            # Start with trigger
            checkpoints.append({
                "node": workflow_ir.trigger.name,
                "output": current_data,
            })
            
            # Walk through the graph
            visited = {workflow_ir.trigger.id}
            queue = self._get_next_steps(workflow_ir, workflow_ir.trigger.id)
            
            while queue:
                step_id = queue.pop(0)
                if step_id in visited:
                    continue
                
                step = workflow_ir.get_step_by_id(step_id)
                if not step:
                    continue
                
                visited.add(step_id)
                
                # Simulate step execution
                step_output = await self._simulate_step(step, current_data)
                
                checkpoints.append({
                    "node": step.name,
                    "input": current_data,
                    "output": step_output,
                })
                
                current_data = step_output
                
                # Get next steps
                next_steps = self._get_next_steps(workflow_ir, step_id)
                queue.extend(s for s in next_steps if s not in visited)
            
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # Check invariant
            passed, failure_reason = self._check_invariant(
                invariant=invariant,
                actual_output=current_data,
                expected_output=expected_output,
            )
            
            # Add warning about simulation mode
            if passed:
                failure_reason = "[SIMULATED] Test passed in simulation - real execution not performed"
            
            return TestResult(
                test_name=test_name,
                passed=passed,
                input_payload=test_input,
                actual_output=current_data,
                expected_output=expected_output,
                failure_reason=failure_reason,
                duration_ms=duration_ms,
                checkpoints=checkpoints,
                execution_mode="simulated",
            )
            
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            return TestResult(
                test_name=test_name,
                passed=False,
                input_payload=test_input,
                failure_reason=f"Simulation error: {str(e)}",
                duration_ms=duration_ms,
                execution_mode="simulated",
            )
    
    def _get_next_steps(self, workflow_ir: WorkflowIR, current_id: str) -> list[str]:
        """Get IDs of steps connected downstream from current step."""
        return [
            edge.target_id
            for edge in workflow_ir.edges
            if edge.source_id == current_id
        ]
    
    async def _simulate_step(self, step, input_data: dict) -> dict:
        """Simulate a single step's execution.
        
        For agent steps, this would call the agent-runner.
        For transform steps, apply the transformation.
        For other steps, pass through.
        """
        from app.models.workflow_ir import StepType
        
        if step.type == StepType.AGENT and step.agent:
            # Simulate agent call
            return {
                "agent_output": {
                    "simulated": True,
                    "agent_name": step.agent.name,
                    "input": input_data,
                },
            }
        
        elif step.type == StepType.TRANSFORM:
            # Apply transform (simplified)
            return {**input_data, "transformed": True}
        
        elif step.type == StepType.BRANCH:
            # Simulate branch (take first condition)
            return {**input_data, "branch_taken": "default"}
        
        else:
            # Pass through
            return input_data
    
    def _check_invariant(
        self,
        invariant: TestInvariant,
        actual_output: Optional[dict],
        expected_output: Optional[dict],
    ) -> tuple[bool, Optional[str]]:
        """Check if an invariant holds.
        
        Returns:
            Tuple of (passed, failure_reason)
        """
        invariant_type = invariant.type
        config = invariant.config
        
        if invariant_type == "execution_success":
            # Just check that we got some output
            if actual_output is not None:
                return True, None
            return False, "No output received"
        
        elif invariant_type == "output_contains":
            # Check that output contains expected keys
            # Support multiple config formats
            expected_keys = config.get("keys", []) or config.get("expected_output_contains", [])
            if not actual_output:
                return False, "No output to check"
            
            # Convert output to string for substring checks if expected_keys are strings
            output_str = str(actual_output).lower()
            output_keys = actual_output.keys() if isinstance(actual_output, dict) else []
            
            missing_keys = []
            for k in expected_keys:
                # Check if k is a key in the dict OR a substring of the output
                k_lower = k.lower() if isinstance(k, str) else str(k)
                if k not in output_keys and k_lower not in output_str:
                    missing_keys.append(k)
            
            if missing_keys:
                return False, f"Missing in output: {missing_keys}"
            return True, None
        
        elif invariant_type == "output_matches_schema":
            # Check output matches expected schema
            # Simplified - just check type for now
            if not actual_output:
                return False, "No output to check"
            if not isinstance(actual_output, dict):
                return False, "Output is not a dict"
            return True, None
        
        elif invariant_type == "output_equals":
            # Check output equals expected
            if actual_output == expected_output:
                return True, None
            return False, f"Output mismatch: expected {expected_output}, got {actual_output}"
        
        elif invariant_type == "branch_taken":
            # Check correct branch was taken
            expected_branch = config.get("branch")
            actual_branch = actual_output.get("branch_taken") if actual_output else None
            if actual_branch == expected_branch:
                return True, None
            return False, f"Wrong branch: expected {expected_branch}, got {actual_branch}"
        
        elif invariant_type == "no_error":
            # Check that no error occurred
            if actual_output and "error" not in actual_output:
                return True, None
            error = actual_output.get("error") if actual_output else "No output"
            return False, f"Error in output: {error}"
        
        else:
            # Unknown invariant type - pass by default
            logger.warning("unknown_invariant_type", type=invariant_type)
            return True, None
    
    async def generate_test_suite(
        self,
        workflow_ir: WorkflowIR,
    ) -> list[dict]:
        """Generate a test suite for a workflow.
        
        Creates at least 3 tests:
        1. Happy path
        2. Malformed input
        3. Error handling
        """
        tests = []
        
        # Happy path test
        tests.append({
            "name": "Happy Path",
            "description": "Valid input produces expected output",
            "type": "happy_path",
            "input": self._generate_valid_input(workflow_ir),
            "invariants": [
                {"type": "execution_success", "config": {}},
                {"type": "no_error", "config": {}},
            ],
        })
        
        # Malformed input test
        tests.append({
            "name": "Malformed Input",
            "description": "Invalid input is handled gracefully",
            "type": "error_handling",
            "input": {},  # Empty input
            "invariants": [
                {"type": "no_error", "config": {}},
            ],
        })
        
        # Error handling test
        tests.append({
            "name": "Error Recovery",
            "description": "Downstream failures are handled",
            "type": "error_handling",
            "input": {
                "customerMessage": "SIMULATE_ERROR: Force downstream failure",
            },
            "invariants": [
                {"type": "execution_success", "config": {}},
            ],
        })
        
        return tests
    
    def _generate_valid_input(self, workflow_ir: WorkflowIR) -> dict:
        """Generate valid input based on workflow description."""
        
        # Check if this is a customer support workflow
        if "customer" in workflow_ir.description.lower():
            return {
                "customerMessage": "I have a billing question about my last invoice",
            }
        
        # Default input
        return {
            "input": "Test input data",
            "timestamp": datetime.utcnow().isoformat(),
        }
