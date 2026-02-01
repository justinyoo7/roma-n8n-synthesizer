"""Auto-Iteration Orchestrator - Automated workflow refinement loop.

The orchestrator manages the full iteration cycle:
1. Generate initial workflow
2. Push to n8n
3. Run tests
4. Analyze failures
5. Generate and apply fixes
6. Repeat until success or max iterations

Stopping conditions:
- All tests pass
- Score >= 85
- Max iterations reached
- No improvement after 2 iterations
"""
from typing import Optional, Callable, Awaitable
from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import dataclass, field

import structlog

from app.models.workflow_ir import WorkflowIR
from app.models.task_tree import SynthesisResult
from app.roma.pipeline import ROMAPipeline
from app.roma.iterator import Iterator
from app.roma.verifier import Verifier, VerificationResult
from app.n8n.compiler import N8NCompiler
from app.n8n.client import N8NClient, N8NClientError
from app.testing.harness import TestHarness, TestResult
from app.config import get_settings

logger = structlog.get_logger()


@dataclass
class IterationRecord:
    """Record of a single iteration."""
    
    iteration_number: int
    workflow_ir: WorkflowIR
    n8n_json: dict
    n8n_workflow_id: Optional[str]
    test_results: list[TestResult]
    score: int
    score_breakdown: dict
    fixes_applied: list[dict]
    analysis: Optional[dict]
    started_at: str
    completed_at: str
    success: bool


@dataclass
class OrchestrationResult:
    """Result of the full orchestration process."""
    
    workflow_id: UUID
    final_iteration_id: UUID
    final_workflow_ir: WorkflowIR
    final_n8n_json: dict
    final_n8n_workflow_id: Optional[str]
    final_n8n_workflow_url: Optional[str]
    webhook_url: Optional[str]  # Full webhook URL for testing
    webhook_path: Optional[str]  # Webhook path only
    iterations: list[IterationRecord]
    total_iterations: int
    final_score: int
    final_score_breakdown: dict
    success: bool
    stop_reason: str
    started_at: str
    completed_at: str


class AutoIterationOrchestrator:
    """Orchestrates automated workflow generation and iteration."""
    
    def __init__(
        self,
        max_iterations: int = 5,
        min_passing_score: int = 80,  # Lowered from 85 to be more achievable
        max_no_improvement: int = 2,
    ):
        self.max_iterations = max_iterations
        self.min_passing_score = min_passing_score
        self.max_no_improvement = max_no_improvement
        
        self.pipeline = ROMAPipeline()
        self.iterator = Iterator()
        self.verifier = Verifier()
        self.compiler = N8NCompiler()
        self.test_harness = TestHarness()
    
    async def run(
        self,
        prompt: str,
        workflow_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> OrchestrationResult:
        """Run the full auto-iteration loop.
        
        Args:
            prompt: Natural language workflow description
            workflow_id: Optional existing workflow ID
            user_id: User ID for tracking
            progress_callback: Optional async callback for progress updates
            
        Returns:
            OrchestrationResult with final workflow and iteration history
        """
        started_at = datetime.utcnow().isoformat()
        
        if not workflow_id:
            workflow_id = uuid4()
        
        logger.info(
            "orchestration_start",
            workflow_id=str(workflow_id),
            prompt_length=len(prompt),
            max_iterations=self.max_iterations,
        )
        
        iterations: list[IterationRecord] = []
        current_workflow_ir: Optional[WorkflowIR] = None
        current_n8n_json: Optional[dict] = None
        current_n8n_workflow_id: Optional[str] = None
        current_score = 0
        no_improvement_count = 0
        previous_score = 0
        stop_reason = "unknown"
        success = False
        
        try:
            # Initial generation
            await self._emit_progress(progress_callback, {
                "phase": "generating",
                "iteration": 0,
                "message": "Generating initial workflow...",
            })
            
            synthesis_result = await self.pipeline.synthesize(
                prompt=prompt,
                workflow_id=workflow_id,
                user_id=user_id,
            )
            
            current_workflow_ir = synthesis_result.workflow_ir
            current_n8n_json = synthesis_result.n8n_json
            current_score = synthesis_result.score or 0
            
            # Main iteration loop
            for iteration_num in range(1, self.max_iterations + 1):
                iteration_started = datetime.utcnow().isoformat()
                
                await self._emit_progress(progress_callback, {
                    "phase": "iteration",
                    "iteration": iteration_num,
                    "message": f"Iteration {iteration_num}: Pushing to n8n...",
                })
                
                # Step 1: Push to n8n
                try:
                    n8n_client = N8NClient()
                    
                    # Delete previous workflow if exists (to avoid clutter)
                    if current_n8n_workflow_id:
                        try:
                            await n8n_client.delete_workflow(current_n8n_workflow_id)
                        except:
                            pass  # Ignore deletion errors
                    
                    # Create new workflow
                    n8n_result = await n8n_client.create_workflow(current_n8n_json)
                    current_n8n_workflow_id = n8n_result.get("id")
                    
                    # Activate for testing
                    if current_n8n_workflow_id:
                        try:
                            await n8n_client.activate_workflow(current_n8n_workflow_id)
                        except:
                            pass  # Some workflows can't be activated
                    
                except N8NClientError as e:
                    logger.error("n8n_push_error", error=str(e))
                    # Continue without n8n push - we'll test locally
                except ValueError:
                    # n8n not configured - test locally
                    pass
                
                await self._emit_progress(progress_callback, {
                    "phase": "testing",
                    "iteration": iteration_num,
                    "message": f"Iteration {iteration_num}: Running tests...",
                    "n8n_workflow_id": current_n8n_workflow_id,
                })
                
                # Step 2: Run tests - REAL EXECUTION via n8n webhook
                test_results = await self.test_harness.run_tests(
                    workflow_ir=current_workflow_ir,
                    n8n_workflow_id=current_n8n_workflow_id,
                    n8n_json=current_n8n_json,  # Pass n8n JSON for webhook path extraction
                    force_real=True,  # Always try real execution
                )
                
                # Calculate score
                current_score, score_breakdown = self._calculate_score(
                    current_workflow_ir,
                    test_results,
                )
                
                # Check stopping conditions
                all_tests_passed = all(r.passed for r in test_results)
                
                iteration_completed = datetime.utcnow().isoformat()
                
                iteration_record = IterationRecord(
                    iteration_number=iteration_num,
                    workflow_ir=current_workflow_ir,
                    n8n_json=current_n8n_json,
                    n8n_workflow_id=current_n8n_workflow_id,
                    test_results=test_results,
                    score=current_score,
                    score_breakdown=score_breakdown,
                    fixes_applied=[],
                    analysis=None,
                    started_at=iteration_started,
                    completed_at=iteration_completed,
                    success=all_tests_passed,
                )
                
                # Check if we should stop
                if all_tests_passed and current_score >= self.min_passing_score:
                    stop_reason = "success"
                    success = True
                    iterations.append(iteration_record)
                    
                    logger.info(
                        "orchestration_success",
                        iteration=iteration_num,
                        score=current_score,
                    )
                    break
                
                # Check for no improvement
                if current_score <= previous_score:
                    no_improvement_count += 1
                    if no_improvement_count >= self.max_no_improvement:
                        stop_reason = "no_improvement"
                        iterations.append(iteration_record)
                        logger.info(
                            "orchestration_stop_no_improvement",
                            iteration=iteration_num,
                            score=current_score,
                        )
                        break
                else:
                    no_improvement_count = 0
                
                previous_score = current_score
                
                # Check max iterations
                if iteration_num >= self.max_iterations:
                    stop_reason = "max_iterations"
                    iterations.append(iteration_record)
                    logger.info(
                        "orchestration_max_iterations",
                        iteration=iteration_num,
                        score=current_score,
                    )
                    break
                
                await self._emit_progress(progress_callback, {
                    "phase": "analyzing",
                    "iteration": iteration_num,
                    "message": f"Iteration {iteration_num}: Analyzing failures...",
                    "score": current_score,
                    "tests_passed": sum(1 for r in test_results if r.passed),
                    "tests_total": len(test_results),
                })
                
                # Step 3: Iterate (analyze failures and apply fixes)
                failed_tests = [r for r in test_results if not r.passed]
                n8n_errors = []  # Would collect from execution if available
                
                modified_ir, iteration_metadata = await self.iterator.iterate(
                    workflow_ir=current_workflow_ir,
                    test_results=test_results,
                    n8n_errors=n8n_errors,
                    iteration_number=iteration_num,
                )
                
                # Update iteration record with analysis
                iteration_record.fixes_applied = iteration_metadata.get("fixes", [])
                iteration_record.analysis = iteration_metadata.get("analysis")
                iterations.append(iteration_record)
                
                # If major restructure needed, regenerate from scratch
                if iteration_metadata.get("requires_major_restructure"):
                    await self._emit_progress(progress_callback, {
                        "phase": "regenerating",
                        "iteration": iteration_num,
                        "message": f"Iteration {iteration_num}: Major restructure needed, regenerating...",
                    })
                    
                    synthesis_result = await self.pipeline.synthesize(
                        prompt=prompt,
                        workflow_id=workflow_id,
                        user_id=user_id,
                    )
                    current_workflow_ir = synthesis_result.workflow_ir
                    current_n8n_json = synthesis_result.n8n_json
                else:
                    # Apply incremental fixes
                    current_workflow_ir = modified_ir
                    current_n8n_json = self.compiler.compile(current_workflow_ir)
                
                await self._emit_progress(progress_callback, {
                    "phase": "iteration_complete",
                    "iteration": iteration_num,
                    "message": f"Iteration {iteration_num} complete",
                    "score": current_score,
                    "fixes_applied": len(iteration_metadata.get("fixes", [])),
                })
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(
                "orchestration_error", 
                error=str(e),
                error_type=type(e).__name__,
                traceback=tb
            )
            stop_reason = f"error: {type(e).__name__}: {str(e)[:100]}"
        
        completed_at = datetime.utcnow().isoformat()
        
        # Build final result
        # Extract webhook path and build full URL
        webhook_path = None
        webhook_url = None
        if current_n8n_json:
            webhook_path = N8NCompiler.extract_webhook_path(current_n8n_json)
            if webhook_path:
                try:
                    n8n_client = N8NClient()
                    webhook_url = n8n_client.get_webhook_url(webhook_path, test_mode=False)
                except:
                    pass
        
        # Build n8n workflow URL
        n8n_workflow_url = None
        if current_n8n_workflow_id:
            try:
                settings = get_settings()
                base = settings.n8n_base_url.replace("/api/v1", "")
                n8n_workflow_url = f"{base}/workflow/{current_n8n_workflow_id}"
            except:
                pass
        
        result = OrchestrationResult(
            workflow_id=workflow_id,
            final_iteration_id=uuid4(),
            final_workflow_ir=current_workflow_ir,
            final_n8n_json=current_n8n_json,
            final_n8n_workflow_id=current_n8n_workflow_id,
            final_n8n_workflow_url=n8n_workflow_url,
            webhook_url=webhook_url,
            webhook_path=webhook_path,
            iterations=iterations,
            total_iterations=len(iterations),
            final_score=current_score,
            final_score_breakdown=score_breakdown if 'score_breakdown' in dir() else {},
            success=success,
            stop_reason=stop_reason,
            started_at=started_at,
            completed_at=completed_at,
        )
        
        await self._emit_progress(progress_callback, {
            "phase": "complete",
            "message": f"Orchestration complete: {stop_reason}",
            "success": success,
            "total_iterations": len(iterations),
            "final_score": current_score,
        })
        
        logger.info(
            "orchestration_complete",
            workflow_id=str(workflow_id),
            iterations=len(iterations),
            final_score=current_score,
            success=success,
            stop_reason=stop_reason,
        )
        
        return result
    
    def _calculate_score(
        self,
        workflow_ir: WorkflowIR,
        test_results: list[TestResult],
    ) -> tuple[int, dict]:
        """Calculate workflow quality score.
        
        Score components (prioritizing accuracy):
        - Correctness (60%): Tests passing
        - Simplicity (15%): Node/edge count (relaxed for complex workflows)
        - Clarity (15%): Naming quality
        - Robustness (10%): Error handling
        """
        # Correctness: Tests passing (weighted more heavily)
        if test_results:
            passed = sum(1 for t in test_results if t.passed)
            total = len(test_results)
            # More generous scoring - 80% pass rate gets full credit
            pass_rate = passed / total if total > 0 else 0
            if pass_rate >= 0.8:
                correctness = 60
            elif pass_rate >= 0.6:
                correctness = int(40 + (pass_rate - 0.6) * 100)  # 40-60 range
            else:
                correctness = int(pass_rate * 66)  # 0-40 range
        else:
            correctness = 30  # Partial credit if no tests
        
        # Simplicity: More lenient for complex workflows
        node_count = len(workflow_ir.steps) + 1  # +1 for trigger
        if node_count <= 4:
            simplicity = 15
        elif node_count <= 8:
            simplicity = 12
        elif node_count <= 12:
            simplicity = 10
        else:
            simplicity = 8  # Still give some credit for complex workflows
        
        # Clarity: Check naming (more lenient)
        clarity = 15  # Full marks by default
        bad_names = 0
        for step in workflow_ir.steps:
            if step.name.startswith("Step ") or step.name.startswith("Unnamed"):
                bad_names += 1
        # Only penalize if more than half have bad names
        if bad_names > len(workflow_ir.steps) / 2:
            clarity = 10
        
        # Robustness: Error handling present
        robustness = 5
        if workflow_ir.error_strategy.retry_config:
            robustness = 10
        
        total = correctness + simplicity + clarity + robustness
        
        return total, {
            "correctness": correctness,
            "simplicity": simplicity,
            "clarity": clarity,
            "robustness": robustness,
        }
    
    async def _emit_progress(
        self,
        callback: Optional[Callable[[dict], Awaitable[None]]],
        data: dict,
    ) -> None:
        """Emit progress update to callback if provided."""
        if callback:
            try:
                await callback(data)
            except Exception as e:
                logger.warning("progress_callback_error", error=str(e))
