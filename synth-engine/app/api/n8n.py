"""n8n API endpoints for workflow management."""
from typing import Optional, Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.n8n.client import N8NClient, N8NClientError

logger = structlog.get_logger()

router = APIRouter()


class PushToN8NRequest(BaseModel):
    """Request to push a workflow to n8n."""
    
    workflow_json: dict = Field(..., description="The compiled n8n workflow JSON")
    workflow_name: Optional[str] = Field(None, description="Override the workflow name")
    activate: bool = Field(False, description="Whether to activate the workflow after creation")


class PushToN8NResponse(BaseModel):
    """Response from pushing to n8n."""
    
    success: bool
    n8n_workflow_id: Optional[str] = None
    n8n_workflow_url: Optional[str] = None
    message: str


class N8NStatusResponse(BaseModel):
    """Response for n8n connection status."""
    
    connected: bool
    base_url: Optional[str] = None
    message: str


@router.get("/n8n/status", response_model=N8NStatusResponse)
async def check_n8n_status() -> N8NStatusResponse:
    """Check if n8n is configured and accessible."""
    settings = get_settings()
    
    if not settings.n8n_api_key:
        return N8NStatusResponse(
            connected=False,
            message="n8n API key not configured. Set N8N_API_KEY in environment."
        )
    
    if not settings.n8n_base_url:
        return N8NStatusResponse(
            connected=False,
            message="n8n base URL not configured. Set N8N_BASE_URL in environment."
        )
    
    try:
        client = N8NClient()
        # Try to list workflows to verify connection
        await client.list_workflows(limit=1)
        
        return N8NStatusResponse(
            connected=True,
            base_url=settings.n8n_base_url.replace("/api/v1", ""),
            message="Connected to n8n successfully"
        )
    except N8NClientError as e:
        logger.error("n8n_connection_error", error=str(e))
        return N8NStatusResponse(
            connected=False,
            base_url=settings.n8n_base_url,
            message=f"Failed to connect to n8n: {str(e)}"
        )
    except Exception as e:
        logger.error("n8n_status_error", error=str(e))
        return N8NStatusResponse(
            connected=False,
            message=f"Error checking n8n status: {str(e)}"
        )


@router.post("/n8n/push", response_model=PushToN8NResponse)
async def push_to_n8n(request: PushToN8NRequest) -> PushToN8NResponse:
    """
    Push a workflow to n8n.
    
    Creates a new workflow in n8n from the compiled workflow JSON.
    Optionally activates the workflow after creation.
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=400,
            detail="n8n API key not configured. Set N8N_API_KEY in environment."
        )
    
    try:
        client = N8NClient()
        
        # Override name if provided
        workflow_json = request.workflow_json.copy()
        if request.workflow_name:
            workflow_json["name"] = request.workflow_name
        
        # Create the workflow
        result = await client.create_workflow(workflow_json)
        
        n8n_workflow_id = result.get("id")
        logger.info("workflow_pushed_to_n8n", n8n_workflow_id=n8n_workflow_id)
        
        # Optionally activate
        if request.activate and n8n_workflow_id:
            try:
                await client.activate_workflow(n8n_workflow_id)
                logger.info("workflow_activated", n8n_workflow_id=n8n_workflow_id)
            except N8NClientError as e:
                logger.warning("workflow_activation_failed", error=str(e))
        
        # Build the workflow URL
        base_url = settings.n8n_base_url.replace("/api/v1", "")
        workflow_url = f"{base_url}/workflow/{n8n_workflow_id}"
        
        return PushToN8NResponse(
            success=True,
            n8n_workflow_id=n8n_workflow_id,
            n8n_workflow_url=workflow_url,
            message=f"Workflow created successfully in n8n"
        )
        
    except N8NClientError as e:
        # Include the actual n8n error response for better debugging
        error_detail = str(e)
        if e.response_body:
            error_detail = f"{e}: {e.response_body}"
        logger.error("n8n_push_error", error=str(e), status_code=e.status_code, response_body=e.response_body)
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to push to n8n: {error_detail}"
        )
    except Exception as e:
        logger.error("n8n_push_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error pushing to n8n: {str(e)}"
        )


class UpdateWorkflowRequest(BaseModel):
    """Request to update an existing workflow in n8n."""
    
    workflow_json: dict = Field(..., description="The updated n8n workflow JSON")
    workflow_name: Optional[str] = Field(None, description="Override the workflow name")


class UpdateWorkflowResponse(BaseModel):
    """Response from updating a workflow."""
    
    success: bool
    n8n_workflow_id: str
    n8n_workflow_url: str
    message: str


@router.put("/n8n/workflows/{workflow_id}", response_model=UpdateWorkflowResponse)
async def update_workflow(workflow_id: str, request: UpdateWorkflowRequest) -> UpdateWorkflowResponse:
    """
    Update an existing workflow in n8n.
    
    This endpoint updates the workflow instead of creating a new one.
    Use this when you've edited a workflow and want to sync changes to n8n.
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=400,
            detail="n8n API key not configured. Set N8N_API_KEY in environment."
        )
    
    try:
        client = N8NClient()
        
        # Override name if provided
        workflow_json = request.workflow_json.copy()
        if request.workflow_name:
            workflow_json["name"] = request.workflow_name
        
        # Ensure the workflow has the correct ID
        workflow_json["id"] = workflow_id
        
        # Update the workflow
        result = await client.update_workflow(workflow_id, workflow_json)
        
        updated_workflow_id = result.get("id")
        logger.info("workflow_updated_in_n8n", n8n_workflow_id=updated_workflow_id)
        
        # Build the workflow URL
        base_url = settings.n8n_base_url.replace("/api/v1", "")
        workflow_url = f"{base_url}/workflow/{updated_workflow_id}"
        
        return UpdateWorkflowResponse(
            success=True,
            n8n_workflow_id=updated_workflow_id,
            n8n_workflow_url=workflow_url,
            message=f"Workflow updated successfully in n8n"
        )
        
    except N8NClientError as e:
        error_detail = str(e)
        if e.response_body:
            error_detail = f"{e}: {e.response_body}"
        logger.error("n8n_update_error", workflow_id=workflow_id, error=str(e), status_code=e.status_code, response_body=e.response_body)
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to update workflow in n8n: {error_detail}"
        )
    except Exception as e:
        logger.error("n8n_update_error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error updating workflow in n8n: {str(e)}"
        )


# ============================================================================
# WorkflowIR to n8n Compilation Endpoint
# ============================================================================

class CompileIRRequest(BaseModel):
    """Request to compile WorkflowIR to n8n JSON."""
    
    workflow_ir: dict = Field(..., description="The WorkflowIR object to compile")
    route_apis_through_perseus: bool = Field(True, description="Whether to route API calls through Perseus backend")


class CompileIRResponse(BaseModel):
    """Response from compiling WorkflowIR."""
    
    success: bool
    workflow_json: Optional[dict] = None
    message: str


@router.post("/n8n/compile", response_model=CompileIRResponse)
async def compile_workflow_ir(request: CompileIRRequest) -> CompileIRResponse:
    """
    Compile a WorkflowIR to n8n workflow JSON.
    
    This endpoint takes a WorkflowIR (the internal workflow representation)
    and compiles it to n8n-compatible JSON that can be pushed to n8n.
    
    Use this when you've edited a workflow and need to generate updated n8n JSON.
    """
    from app.n8n.compiler import N8NCompiler
    from app.models.workflow_ir import WorkflowIR
    
    try:
        # Parse the WorkflowIR from the dict
        workflow_ir = WorkflowIR.model_validate(request.workflow_ir)
        
        # Create compiler and compile
        compiler = N8NCompiler(route_apis_through_perseus=request.route_apis_through_perseus)
        n8n_json = compiler.compile(workflow_ir)
        
        logger.info("workflow_ir_compiled", workflow_name=workflow_ir.name)
        
        return CompileIRResponse(
            success=True,
            workflow_json=n8n_json,
            message="WorkflowIR compiled to n8n format successfully"
        )
        
    except Exception as e:
        logger.error("compile_ir_error", error=str(e))
        raise HTTPException(
            status_code=400,
            detail=f"Failed to compile WorkflowIR: {str(e)}"
        )


class WebhookProxyRequest(BaseModel):
    """Request to proxy a webhook call through the backend (avoids CORS)."""
    
    webhook_url: str = Field(..., description="The full webhook URL to call")
    payload: dict = Field(..., description="The JSON payload to send")
    method: str = Field("POST", description="HTTP method to use")


class WebhookProxyResponse(BaseModel):
    """Response from proxied webhook call."""
    
    status_code: int
    body: Any
    success: bool
    error: Optional[str] = None


@router.post("/webhook/proxy", response_model=WebhookProxyResponse)
async def proxy_webhook(request: WebhookProxyRequest) -> WebhookProxyResponse:
    """
    Proxy a webhook request to n8n.
    
    This endpoint allows the frontend to call n8n webhooks without CORS issues.
    The backend makes the request on behalf of the frontend and returns the response.
    """
    logger.info(
        "webhook_proxy_request",
        url=request.webhook_url,
        method=request.method,
        payload_keys=list(request.payload.keys()),
    )
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=request.method,
                url=request.webhook_url,
                json=request.payload,
                headers={"Content-Type": "application/json"},
            )
            
            # Try to parse response as JSON
            try:
                body = response.json()
            except Exception:
                body = response.text
            
            logger.info(
                "webhook_proxy_response",
                status_code=response.status_code,
                success=response.is_success,
            )
            
            return WebhookProxyResponse(
                status_code=response.status_code,
                body=body,
                success=response.is_success,
            )
            
    except httpx.TimeoutException:
        logger.error("webhook_proxy_timeout", url=request.webhook_url)
        return WebhookProxyResponse(
            status_code=504,
            body=None,
            success=False,
            error="Request timed out after 60 seconds",
        )
    except httpx.RequestError as e:
        logger.error("webhook_proxy_error", url=request.webhook_url, error=str(e))
        return WebhookProxyResponse(
            status_code=502,
            body=None,
            success=False,
            error=f"Request failed: {str(e)}",
        )
    except Exception as e:
        logger.error("webhook_proxy_error", url=request.webhook_url, error=str(e))
        return WebhookProxyResponse(
            status_code=500,
            body=None,
            success=False,
            error=f"Unexpected error: {str(e)}",
        )


# ============================================================================
# Execution History Endpoints
# ============================================================================

class ExecutionSummary(BaseModel):
    """Summary of a single execution."""
    
    id: str
    status: str  # waiting, running, success, error
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    finished_at: Optional[str] = None
    mode: Optional[str] = None  # webhook, manual, trigger
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    duration_ms: Optional[int] = None
    retry_of: Optional[str] = None
    retry_success_id: Optional[str] = None


class ExecutionData(BaseModel):
    """Execution data structure with node run results."""
    
    resultData: Optional[dict] = None  # Contains runData with node outputs
    startData: Optional[dict] = None
    executionData: Optional[dict] = None


class ExecutionInfo(BaseModel):
    """Full execution information including node outputs."""
    
    id: str
    status: str
    startedAt: Optional[str] = None
    stoppedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    mode: Optional[str] = None
    workflowId: Optional[str] = None
    data: Optional[ExecutionData] = None  # Full execution data including node outputs


class ExecutionDetailResponse(BaseModel):
    """Response for execution detail endpoint - matches frontend expectations."""
    
    execution: ExecutionInfo
    workflow_id: str
    execution_id: str


# Keep legacy model for backwards compatibility
class ExecutionDetail(BaseModel):
    """Detailed execution data including node outputs (legacy format)."""
    
    id: str
    status: str
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    finished_at: Optional[str] = None
    mode: Optional[str] = None
    workflow_id: Optional[str] = None
    data: Optional[dict] = None  # Full execution data including node outputs


class ExecutionsResponse(BaseModel):
    """Response containing execution list."""
    
    executions: list[ExecutionSummary]
    workflow_id: Optional[str] = None
    total_count: int


@router.get("/n8n/executions/{workflow_id}", response_model=ExecutionsResponse)
async def get_executions(workflow_id: str, limit: int = 20, status: Optional[str] = None) -> ExecutionsResponse:
    """
    Get execution history for a workflow from n8n.
    
    Args:
        workflow_id: The n8n workflow ID
        limit: Maximum number of executions to return (default 20)
        status: Filter by status (waiting, running, success, error)
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=400,
            detail="n8n API key not configured"
        )
    
    try:
        client = N8NClient()
        result = await client.get_executions(
            workflow_id=workflow_id,
            status=status,
            limit=limit,
        )
        
        executions = []
        for exec_data in result.get("data", []):
            # Calculate duration
            duration_ms = None
            started = exec_data.get("startedAt")
            stopped = exec_data.get("stoppedAt") or exec_data.get("finishedAt")
            
            if started and stopped:
                try:
                    from datetime import datetime
                    start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    stop_dt = datetime.fromisoformat(stopped.replace("Z", "+00:00"))
                    duration_ms = int((stop_dt - start_dt).total_seconds() * 1000)
                except Exception:
                    pass
            
            executions.append(ExecutionSummary(
                id=str(exec_data.get("id")),
                status=exec_data.get("status", "unknown"),
                started_at=exec_data.get("startedAt"),
                stopped_at=exec_data.get("stoppedAt"),
                finished_at=exec_data.get("finishedAt"),
                mode=exec_data.get("mode"),
                workflow_id=exec_data.get("workflowId"),
                workflow_name=exec_data.get("workflowName"),
                duration_ms=duration_ms,
                retry_of=exec_data.get("retryOf"),
                retry_success_id=exec_data.get("retrySuccessId"),
            ))
        
        return ExecutionsResponse(
            executions=executions,
            workflow_id=workflow_id,
            total_count=len(executions),
        )
        
    except N8NClientError as e:
        logger.error("get_executions_error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to get executions: {str(e)}"
        )
    except Exception as e:
        logger.error("get_executions_error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error getting executions: {str(e)}"
        )


@router.get("/n8n/executions/{workflow_id}/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution_detail(workflow_id: str, execution_id: str) -> ExecutionDetailResponse:
    """
    Get detailed execution data including node outputs.
    
    Args:
        workflow_id: The n8n workflow ID (for validation)
        execution_id: The execution ID
        
    Returns:
        Full execution details with data.resultData.runData containing node outputs
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=400,
            detail="n8n API key not configured"
        )
    
    try:
        client = N8NClient()
        # Request full execution data with includeData=true
        exec_data = await client.get_execution(execution_id, include_data=True)
        
        # Enhanced debug logging to diagnose data: null issue
        has_data = exec_data.get("data") is not None
        logger.info(
            "execution_detail_fetched",
            execution_id=execution_id,
            workflow_id=workflow_id,
            status=exec_data.get("status"),
            has_data=has_data,
            data_keys=list(exec_data.get("data", {}).keys()) if has_data else [],
            all_keys=list(exec_data.keys()),
            mode=exec_data.get("mode"),
        )
        
        if not has_data:
            logger.warning(
                "execution_data_null",
                execution_id=execution_id,
                workflow_id=workflow_id,
                hint="n8n may not save execution data. Check n8n Settings > Executions > 'Save Data on Success' = All",
            )
        
        # Build execution data structure
        raw_data = exec_data.get("data")
        execution_data = None
        if raw_data:
            execution_data = ExecutionData(
                resultData=raw_data.get("resultData"),
                startData=raw_data.get("startData"),
                executionData=raw_data.get("executionData"),
            )
        
        execution_info = ExecutionInfo(
            id=str(exec_data.get("id")),
            status=exec_data.get("status", "unknown"),
            startedAt=exec_data.get("startedAt"),
            stoppedAt=exec_data.get("stoppedAt"),
            finishedAt=exec_data.get("finishedAt"),
            mode=exec_data.get("mode"),
            workflowId=exec_data.get("workflowId"),
            data=execution_data,
        )
        
        return ExecutionDetailResponse(
            execution=execution_info,
            workflow_id=workflow_id,
            execution_id=execution_id,
        )
        
    except N8NClientError as e:
        logger.error("get_execution_detail_error", execution_id=execution_id, error=str(e))
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to get execution: {str(e)}"
        )
    except Exception as e:
        logger.error("get_execution_detail_error", execution_id=execution_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error getting execution: {str(e)}"
        )


# ============================================================================
# Workflow Activation Endpoints
# ============================================================================

class ActivateRequest(BaseModel):
    """Request to activate/deactivate a workflow."""
    
    active: bool = Field(..., description="Whether to activate (true) or deactivate (false)")


class ActivateResponse(BaseModel):
    """Response from activation request."""
    
    success: bool
    active: bool
    workflow_id: str
    message: str


@router.post("/n8n/activate/{workflow_id}", response_model=ActivateResponse)
async def activate_workflow(workflow_id: str, request: ActivateRequest) -> ActivateResponse:
    """
    Activate or deactivate a workflow in n8n.
    
    Args:
        workflow_id: The n8n workflow ID
        request: Contains 'active' boolean
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=400,
            detail="n8n API key not configured"
        )
    
    try:
        client = N8NClient()
        
        if request.active:
            await client.activate_workflow(workflow_id)
            logger.info("workflow_activated", workflow_id=workflow_id)
            return ActivateResponse(
                success=True,
                active=True,
                workflow_id=workflow_id,
                message="Workflow activated successfully"
            )
        else:
            await client.deactivate_workflow(workflow_id)
            logger.info("workflow_deactivated", workflow_id=workflow_id)
            return ActivateResponse(
                success=True,
                active=False,
                workflow_id=workflow_id,
                message="Workflow deactivated successfully"
            )
            
    except N8NClientError as e:
        logger.error("activation_error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to {'activate' if request.active else 'deactivate'} workflow: {str(e)}"
        )
    except Exception as e:
        logger.error("activation_error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error: {str(e)}"
        )


# ============================================================================
# Workflow Printing Endpoints
# ============================================================================

class PrintWorkflowRequest(BaseModel):
    """Request to print a workflow in text format."""
    workflow_json: dict = Field(..., description="n8n workflow JSON to print")
    include_params: bool = Field(False, description="Include node parameters")
    format: str = Field("full", description="Output format: 'full', 'compact', or 'ir'")


class PrintWorkflowResponse(BaseModel):
    """Response with text representation."""
    text: str
    format: str


@router.post("/n8n/print", response_model=PrintWorkflowResponse)
async def print_workflow_text(request: PrintWorkflowRequest) -> PrintWorkflowResponse:
    """
    Print an n8n workflow in a clean text representation.
    
    Formats:
    - "full": Detailed view with all nodes and connections
    - "compact": One-line-per-node summary
    - "ir": WorkflowIR format (if workflow_json is actually a WorkflowIR)
    """
    from app.utils.workflow_printer import print_workflow, print_workflow_compact, print_workflow_ir
    
    try:
        if request.format == "compact":
            text = print_workflow_compact(request.workflow_json)
        elif request.format == "ir":
            text = print_workflow_ir(request.workflow_json)
        else:
            text = print_workflow(request.workflow_json, include_params=request.include_params)
        
        return PrintWorkflowResponse(text=text, format=request.format)
    
    except Exception as e:
        logger.error("print_workflow_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Failed to print workflow: {str(e)}")


@router.get("/n8n/print/{workflow_id}")
async def print_workflow_by_id(
    workflow_id: str,
    include_params: bool = False,
    format: str = "full"
) -> PrintWorkflowResponse:
    """
    Fetch a workflow from n8n and print it in text format.
    
    Args:
        workflow_id: n8n workflow ID
        include_params: Include node parameters (default: False)
        format: Output format - 'full' or 'compact' (default: 'full')
    """
    from app.utils.workflow_printer import print_workflow, print_workflow_compact
    
    try:
        client = N8NClient()
        workflow = await client.get_workflow(workflow_id)
        
        if format == "compact":
            text = print_workflow_compact(workflow)
        else:
            text = print_workflow(workflow, include_params=include_params)
        
        return PrintWorkflowResponse(text=text, format=format)
    
    except N8NClientError as e:
        raise HTTPException(status_code=e.status_code or 404, detail=str(e))
    except Exception as e:
        logger.error("print_workflow_error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Debug Endpoint for n8n Execution Data
# ============================================================================

@router.get("/n8n/debug/execution/{execution_id}")
async def debug_execution(execution_id: str):
    """
    Debug endpoint to see raw n8n execution response.
    
    This helps diagnose why data might be null.
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(status_code=400, detail="n8n API key not configured")
    
    try:
        client = N8NClient()
        
        # Try with includeData=true (string)
        result_with_data = await client.get_execution(execution_id, include_data=True)
        
        # Also try fetching without the param to compare
        result_without = await client._request(
            method="GET",
            endpoint=f"/executions/{execution_id}",
        )
        
        return {
            "debug_info": {
                "execution_id": execution_id,
                "n8n_base_url": settings.n8n_base_url,
            },
            "with_includeData_true": {
                "keys": list(result_with_data.keys()),
                "has_data": result_with_data.get("data") is not None,
                "data_keys": list(result_with_data.get("data", {}).keys()) if result_with_data.get("data") else None,
                "status": result_with_data.get("status"),
                "mode": result_with_data.get("mode"),
                "raw_data_preview": str(result_with_data.get("data"))[:500] if result_with_data.get("data") else None,
            },
            "without_param": {
                "keys": list(result_without.keys()),
                "has_data": result_without.get("data") is not None,
                "data_keys": list(result_without.get("data", {}).keys()) if result_without.get("data") else None,
            },
            "hint": "If both show data: null, check n8n Settings > Executions > 'Save Data on Success' = All",
        }
        
    except N8NClientError as e:
        return {
            "error": str(e),
            "status_code": e.status_code,
            "response_body": e.response_body,
        }
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__,
        }
