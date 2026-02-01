"""Test API endpoint - run tests on a workflow.

Tests are ALWAYS run against the real n8n workflow via webhook when possible.
Simulation is only used as a fallback when n8n is not configured.
"""
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.testing.harness import TestHarness, TestResult
from app.models.workflow_ir import WorkflowIR
from app.n8n.compiler import N8NCompiler

logger = structlog.get_logger()

router = APIRouter()


class TestRequest(BaseModel):
    """Request body for running tests."""
    
    workflow_ir: WorkflowIR = Field(
        ...,
        description="The WorkflowIR to test",
    )
    n8n_workflow_id: Optional[str] = Field(
        None,
        description="n8n workflow ID (for reference)",
    )
    n8n_json: Optional[dict] = Field(
        None,
        description="Compiled n8n JSON (to extract webhook path)",
    )
    force_real: bool = Field(
        True,
        description="If True (default), always try real webhook execution",
    )


class TestResultResponse(BaseModel):
    """Single test result."""
    
    test_name: str
    passed: bool
    failure_reason: Optional[str] = None
    duration_ms: int
    execution_mode: str = "unknown"  # "real" or "simulated"
    webhook_url: Optional[str] = None


class TestResponse(BaseModel):
    """Response body for test execution."""
    
    results: list[TestResultResponse]
    passed_count: int
    total_count: int
    all_passed: bool
    real_execution_count: int
    simulated_execution_count: int
    webhook_url: Optional[str] = None


@router.post("/test", response_model=TestResponse)
async def run_tests(request: TestRequest) -> TestResponse:
    """
    Run tests on a workflow.
    
    Tests are ALWAYS run against real n8n workflows via webhook when possible.
    This triggers the actual workflow in n8n and validates the real output.
    
    Simulation is only used as a fallback when:
    - n8n API key is not configured
    - Webhook path cannot be determined
    """
    logger.info(
        "test_request",
        workflow_name=request.workflow_ir.name,
        n8n_workflow_id=request.n8n_workflow_id,
        force_real=request.force_real,
    )
    
    try:
        harness = TestHarness()
        
        # Run tests - harness will automatically use real execution when possible
        results: list[TestResult] = await harness.run_tests(
            workflow_ir=request.workflow_ir,
            n8n_workflow_id=request.n8n_workflow_id,
            n8n_json=request.n8n_json,
            force_real=request.force_real,
        )
        
        response_results = [
            TestResultResponse(
                test_name=r.test_name,
                passed=r.passed,
                failure_reason=r.failure_reason,
                duration_ms=r.duration_ms,
                execution_mode=r.execution_mode,
                webhook_url=r.webhook_url,
            )
            for r in results
        ]
        
        passed_count = sum(1 for r in results if r.passed)
        real_count = sum(1 for r in results if r.execution_mode == "real")
        simulated_count = len(results) - real_count
        
        # Get webhook URL from first result if available
        webhook_url = next((r.webhook_url for r in results if r.webhook_url), None)
        
        logger.info(
            "test_complete",
            passed=passed_count,
            total=len(results),
            real_executions=real_count,
            simulated_executions=simulated_count,
        )
        
        return TestResponse(
            results=response_results,
            passed_count=passed_count,
            total_count=len(results),
            all_passed=passed_count == len(results),
            real_execution_count=real_count,
            simulated_execution_count=simulated_count,
            webhook_url=webhook_url,
        )
        
    except Exception as e:
        logger.error("test_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
