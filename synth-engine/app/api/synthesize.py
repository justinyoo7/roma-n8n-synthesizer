"""Synthesis API endpoint - orchestrates the full ROMA pipeline."""
from typing import Optional, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.workflow_ir import WorkflowIR
from app.models.task_tree import SynthesisResult
from app.roma.pipeline import ROMAPipeline
from app.roma.orchestrator import AutoIterationOrchestrator, OrchestrationResult

logger = structlog.get_logger()

router = APIRouter()


class SynthesizeRequest(BaseModel):
    """Request body for workflow synthesis."""
    
    prompt: str = Field(
        ...,
        description="Natural language description of the desired workflow",
        min_length=10,
        max_length=5000,
    )
    workflow_id: Optional[UUID] = Field(
        None,
        description="Existing workflow ID to iterate on (for refinement)",
    )
    previous_iteration_id: Optional[UUID] = Field(
        None,
        description="Previous iteration ID to build upon",
    )
    user_id: Optional[UUID] = Field(
        None,
        description="User ID for tracking ownership",
    )
    auto_iterate: bool = Field(
        False,
        description="Automatically iterate until tests pass or max iterations reached",
    )
    max_iterations: int = Field(
        5,
        description="Maximum number of iterations (if auto_iterate is True)",
        ge=1,
        le=10,
    )


class IterationSummary(BaseModel):
    """Summary of a single iteration."""
    
    iteration_number: int
    score: int
    tests_passed: int
    tests_total: int
    fixes_applied: int
    success: bool


class SynthesizeResponse(BaseModel):
    """Response body for workflow synthesis."""
    
    workflow_id: UUID
    iteration_id: UUID
    iteration_version: int
    workflow_ir: WorkflowIR
    n8n_json: dict
    rationale: str
    test_plan: list[dict]
    score: Optional[int] = None
    score_breakdown: Optional[dict] = None
    # Auto-iteration fields
    auto_iterated: bool = False
    total_iterations: int = 1
    iteration_history: List[IterationSummary] = []
    n8n_workflow_id: Optional[str] = None
    n8n_workflow_url: Optional[str] = None
    # Webhook fields for real testing
    webhook_url: Optional[str] = None  # Full webhook URL (e.g., https://xxx.n8n.cloud/webhook/path)
    webhook_path: Optional[str] = None  # Just the webhook path
    success: bool = True
    stop_reason: Optional[str] = None


@router.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize_workflow(request: SynthesizeRequest) -> SynthesizeResponse:
    """
    Synthesize an n8n workflow from a natural language description.
    
    Uses the ROMA (Recursive Open Meta-Agent) pipeline:
    1. Atomizer - Classify complexity and create initial structure
    2. Planner - Decompose into subtasks with dependencies
    3. Executor - Generate artifacts for each subtask
    4. Aggregator - Merge into coherent WorkflowIR
    5. Verifier - Validate and compile to n8n JSON
    
    If auto_iterate=True, will automatically:
    - Push to n8n
    - Run tests
    - Analyze failures
    - Generate and apply fixes
    - Repeat until success or max iterations
    """
    logger.info(
        "synthesize_request",
        prompt_length=len(request.prompt),
        workflow_id=str(request.workflow_id) if request.workflow_id else None,
        auto_iterate=request.auto_iterate,
    )
    
    try:
        if request.auto_iterate:
            # Use the auto-iteration orchestrator
            orchestrator = AutoIterationOrchestrator(
                max_iterations=request.max_iterations,
            )
            
            result: OrchestrationResult = await orchestrator.run(
                prompt=request.prompt,
                workflow_id=request.workflow_id,
                user_id=request.user_id,
            )
            
            # Build iteration history
            iteration_history = []
            for record in result.iterations:
                iteration_history.append(IterationSummary(
                    iteration_number=record.iteration_number,
                    score=record.score,
                    tests_passed=sum(1 for t in record.test_results if t.passed),
                    tests_total=len(record.test_results),
                    fixes_applied=len(record.fixes_applied),
                    success=record.success,
                ))
            
            # Build n8n URL if we have a workflow ID
            n8n_workflow_url = None
            if result.final_n8n_workflow_id:
                from app.config import get_settings
                settings = get_settings()
                if settings.n8n_base_url:
                    base_ui_url = settings.n8n_base_url.replace("/api/v1", "")
                    n8n_workflow_url = f"{base_ui_url}/workflow/{result.final_n8n_workflow_id}"
            
            logger.info(
                "synthesize_auto_iterate_complete",
                workflow_id=str(result.workflow_id),
                iterations=result.total_iterations,
                final_score=result.final_score,
                success=result.success,
            )
            
            return SynthesizeResponse(
                workflow_id=result.workflow_id,
                iteration_id=result.final_iteration_id,
                iteration_version=result.total_iterations,
                workflow_ir=result.final_workflow_ir,
                n8n_json=result.final_n8n_json,
                rationale=f"Auto-iterated {result.total_iterations} times. {result.stop_reason}",
                test_plan=[],
                score=result.final_score,
                score_breakdown=result.final_score_breakdown,
                auto_iterated=True,
                total_iterations=result.total_iterations,
                iteration_history=iteration_history,
                n8n_workflow_id=result.final_n8n_workflow_id,
                n8n_workflow_url=result.final_n8n_workflow_url or n8n_workflow_url,
                webhook_url=result.webhook_url,
                webhook_path=result.webhook_path,
                success=result.success,
                stop_reason=result.stop_reason,
            )
        
        else:
            # Standard single-shot synthesis
            pipeline = ROMAPipeline()
            result: SynthesisResult = await pipeline.synthesize(
                prompt=request.prompt,
                workflow_id=request.workflow_id,
                previous_iteration_id=request.previous_iteration_id,
                user_id=request.user_id,
            )
            
            logger.info(
                "synthesize_success",
                workflow_id=str(result.workflow_id),
                iteration_id=str(result.iteration_id),
                score=result.score,
            )
            
            # Extract webhook info from workflow IR if it's a webhook trigger
            webhook_url = None
            webhook_path = None
            n8n_workflow_id = None
            n8n_workflow_url = None
            
            if result.workflow_ir.trigger and result.workflow_ir.trigger.trigger_type.value == "webhook":
                from app.config import get_settings
                settings = get_settings()
                trigger_params = result.workflow_ir.trigger.parameters or {}
                webhook_path = trigger_params.get("path", "webhook")
                if settings.n8n_base_url:
                    base_webhook_url = settings.n8n_base_url.replace("/api/v1", "")
                    webhook_url = f"{base_webhook_url}/webhook/{webhook_path}"
            
            # Auto-push to n8n and activate for immediate testing
            if result.n8n_json:
                try:
                    from app.n8n.client import N8NClient
                    from app.config import get_settings
                    settings = get_settings()
                    
                    client = N8NClient()
                    push_result = await client.create_workflow(result.n8n_json)
                    n8n_workflow_id = push_result.get("id")
                    
                    if n8n_workflow_id:
                        # Activate the workflow for immediate use
                        try:
                            await client.activate_workflow(n8n_workflow_id)
                            logger.info("workflow_activated", n8n_workflow_id=n8n_workflow_id)
                        except Exception as e:
                            logger.warning("workflow_activation_failed", error=str(e))
                        
                        # Build n8n URL
                        if settings.n8n_base_url:
                            base_url = settings.n8n_base_url.replace("/api/v1", "")
                            n8n_workflow_url = f"{base_url}/workflow/{n8n_workflow_id}"
                        
                        logger.info(
                            "workflow_pushed_to_n8n",
                            n8n_workflow_id=n8n_workflow_id,
                            webhook_url=webhook_url,
                        )
                except Exception as e:
                    logger.warning("n8n_push_failed", error=str(e))
            
            return SynthesizeResponse(
                workflow_id=result.workflow_id,
                iteration_id=result.iteration_id,
                iteration_version=result.iteration_version,
                workflow_ir=result.workflow_ir,
                n8n_json=result.n8n_json,
                rationale=result.rationale,
                test_plan=result.test_plan,
                score=result.score,
                score_breakdown=result.score_breakdown,
                webhook_url=webhook_url,
                webhook_path=webhook_path,
                n8n_workflow_id=n8n_workflow_id,
                n8n_workflow_url=n8n_workflow_url,
            )
        
    except Exception as e:
        logger.error("synthesize_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
