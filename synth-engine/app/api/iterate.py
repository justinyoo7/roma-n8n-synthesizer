"""Iteration API endpoint - refine workflow based on test failures."""
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.workflow_ir import WorkflowIR
from app.roma.pipeline import ROMAPipeline

logger = structlog.get_logger()

router = APIRouter()


class IterateRequest(BaseModel):
    """Request body for workflow iteration."""
    
    workflow_id: UUID = Field(..., description="Workflow to iterate on")
    iteration_id: UUID = Field(..., description="Current iteration to improve")
    failure_traces: list[dict] = Field(
        default_factory=list,
        description="Test failure traces from previous iteration",
    )
    user_feedback: Optional[str] = Field(
        None,
        description="Optional user feedback for targeted improvements",
    )


class IterateResponse(BaseModel):
    """Response body for workflow iteration."""
    
    iteration_id: UUID
    iteration_version: int
    workflow_ir: WorkflowIR
    n8n_json: dict
    changes_made: list[str]
    rationale: str
    score: Optional[int] = None
    score_breakdown: Optional[dict] = None


@router.post("/iterate", response_model=IterateResponse)
async def iterate_workflow(request: IterateRequest) -> IterateResponse:
    """
    Iterate on a workflow to fix test failures or apply user feedback.
    
    The iteration process:
    1. Analyze failure traces to identify root causes
    2. Generate a FixPlan targeting specific issues
    3. Route back through relevant ROMA modules
    4. Produce an improved WorkflowIR
    """
    logger.info(
        "iterate_request",
        workflow_id=str(request.workflow_id),
        iteration_id=str(request.iteration_id),
        failure_count=len(request.failure_traces),
    )
    
    try:
        pipeline = ROMAPipeline()
        result = await pipeline.iterate(
            workflow_id=request.workflow_id,
            iteration_id=request.iteration_id,
            failure_traces=request.failure_traces,
            user_feedback=request.user_feedback,
        )
        
        logger.info(
            "iterate_success",
            new_iteration_id=str(result.iteration_id),
            changes_count=len(result.changes_made),
            score=result.score,
        )
        
        return IterateResponse(
            iteration_id=result.iteration_id,
            iteration_version=result.iteration_version,
            workflow_ir=result.workflow_ir,
            n8n_json=result.n8n_json,
            changes_made=result.changes_made,
            rationale=result.rationale,
            score=result.score,
            score_breakdown=result.score_breakdown,
        )
        
    except Exception as e:
        logger.error("iterate_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
