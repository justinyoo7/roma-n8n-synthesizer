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


class ExecutionDetail(BaseModel):
    """Detailed execution data including node outputs."""
    
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


@router.get("/n8n/executions/{workflow_id}/{execution_id}", response_model=ExecutionDetail)
async def get_execution_detail(workflow_id: str, execution_id: str) -> ExecutionDetail:
    """
    Get detailed execution data including node outputs.
    
    Args:
        workflow_id: The n8n workflow ID (for validation)
        execution_id: The execution ID
    """
    settings = get_settings()
    
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=400,
            detail="n8n API key not configured"
        )
    
    try:
        client = N8NClient()
        exec_data = await client.get_execution(execution_id)
        
        return ExecutionDetail(
            id=str(exec_data.get("id")),
            status=exec_data.get("status", "unknown"),
            started_at=exec_data.get("startedAt"),
            stopped_at=exec_data.get("stoppedAt"),
            finished_at=exec_data.get("finishedAt"),
            mode=exec_data.get("mode"),
            workflow_id=exec_data.get("workflowId"),
            data=exec_data.get("data"),
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
