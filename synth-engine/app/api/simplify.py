"""Simplification API endpoint - minimize workflow while preserving behavior."""
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.workflow_ir import WorkflowIR
from app.roma.simplifier import Simplifier

logger = structlog.get_logger()

router = APIRouter()


class SimplifyRequest(BaseModel):
    """Request body for workflow simplification."""
    
    workflow_id: UUID = Field(..., description="Workflow to simplify")
    iteration_id: UUID = Field(..., description="Iteration to simplify")
    preserve_tests: bool = Field(
        True,
        description="Ensure all tests still pass after simplification",
    )


class SimplifyResponse(BaseModel):
    """Response body for workflow simplification."""
    
    iteration_id: UUID
    iteration_version: int
    workflow_ir: WorkflowIR
    n8n_json: dict
    simplifications_applied: list[str]
    nodes_removed: int
    edges_removed: int
    original_score: int
    new_score: int


@router.post("/simplify", response_model=SimplifyResponse)
async def simplify_workflow(request: SimplifyRequest) -> SimplifyResponse:
    """
    Simplify a workflow by removing redundant nodes and merging transforms.
    
    Simplification strategies:
    - Remove redundant passthrough nodes
    - Merge consecutive transform nodes
    - Eliminate unused branches
    - Consolidate error handling
    
    After each simplification step, tests are re-run to verify behavior is preserved.
    """
    logger.info(
        "simplify_request",
        workflow_id=str(request.workflow_id),
        iteration_id=str(request.iteration_id),
    )
    
    try:
        simplifier = Simplifier()
        result = await simplifier.simplify(
            workflow_id=request.workflow_id,
            iteration_id=request.iteration_id,
            preserve_tests=request.preserve_tests,
        )
        
        logger.info(
            "simplify_success",
            new_iteration_id=str(result.iteration_id),
            nodes_removed=result.nodes_removed,
            new_score=result.new_score,
        )
        
        return SimplifyResponse(
            iteration_id=result.iteration_id,
            iteration_version=result.iteration_version,
            workflow_ir=result.workflow_ir,
            n8n_json=result.n8n_json,
            simplifications_applied=result.simplifications_applied,
            nodes_removed=result.nodes_removed,
            edges_removed=result.edges_removed,
            original_score=result.original_score,
            new_score=result.new_score,
        )
        
    except Exception as e:
        logger.error("simplify_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
