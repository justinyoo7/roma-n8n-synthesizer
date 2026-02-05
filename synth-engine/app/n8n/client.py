"""n8n Cloud API client for workflow management.

Handles:
- Creating new workflows
- Updating existing workflows
- Retrieving workflow details
- Executing workflows for testing
"""
from typing import Optional

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()


class N8NClientError(Exception):
    """Exception for n8n API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class N8NClient:
    """Client for n8n Cloud REST API."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.n8n_base_url).rstrip("/")
        self.api_key = api_key or settings.n8n_api_key
        
        if not self.api_key:
            raise ValueError("n8n API key not configured")
        
        self.headers = {
            "X-N8N-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make an HTTP request to the n8n API."""
        
        url = f"{self.base_url}{endpoint}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=json,
                    params=params,
                    timeout=30.0,
                )
                
                # Log request (without sensitive data)
                logger.debug(
                    "n8n_api_request",
                    method=method,
                    endpoint=endpoint,
                    status_code=response.status_code,
                )
                
                if response.status_code >= 400:
                    error_body = response.json() if response.content else {}
                    raise N8NClientError(
                        f"n8n API error: {response.status_code}",
                        status_code=response.status_code,
                        response_body=error_body,
                    )
                
                return response.json() if response.content else {}
                
            except httpx.HTTPError as e:
                logger.error("n8n_api_error", error=str(e))
                raise N8NClientError(f"HTTP error: {str(e)}")
    
    async def create_workflow(self, workflow_json: dict) -> dict:
        """Create a new workflow in n8n.
        
        Args:
            workflow_json: The compiled workflow JSON
            
        Returns:
            The created workflow data including the assigned ID
        """
        logger.info("create_workflow", name=workflow_json.get("name"))
        
        result = await self._request(
            method="POST",
            endpoint="/workflows",
            json=workflow_json,
        )
        
        logger.info(
            "workflow_created",
            workflow_id=result.get("id"),
            name=result.get("name"),
        )
        
        return result
    
    async def update_workflow(self, workflow_id: str, workflow_json: dict) -> dict:
        """Update an existing workflow.
        
        Args:
            workflow_id: The n8n workflow ID
            workflow_json: The updated workflow JSON
            
        Returns:
            The updated workflow data
        """
        logger.info("update_workflow", workflow_id=workflow_id)
        
        result = await self._request(
            method="PUT",
            endpoint=f"/workflows/{workflow_id}",
            json=workflow_json,
        )
        
        logger.info("workflow_updated", workflow_id=workflow_id)
        
        return result
    
    async def get_workflow(self, workflow_id: str) -> dict:
        """Get a workflow by ID.
        
        Args:
            workflow_id: The n8n workflow ID
            
        Returns:
            The workflow data
        """
        logger.debug("get_workflow", workflow_id=workflow_id)
        
        return await self._request(
            method="GET",
            endpoint=f"/workflows/{workflow_id}",
        )
    
    async def list_workflows(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """List all workflows.
        
        Args:
            limit: Maximum number of workflows to return
            cursor: Pagination cursor
            tags: Filter by tags
            
        Returns:
            Paginated list of workflows
        """
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if tags:
            params["tags"] = ",".join(tags)
        
        return await self._request(
            method="GET",
            endpoint="/workflows",
            params=params,
        )
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow.
        
        Args:
            workflow_id: The n8n workflow ID
            
        Returns:
            True if deleted successfully
        """
        logger.info("delete_workflow", workflow_id=workflow_id)
        
        await self._request(
            method="DELETE",
            endpoint=f"/workflows/{workflow_id}",
        )
        
        return True
    
    async def activate_workflow(self, workflow_id: str) -> dict:
        """Activate a workflow (enable triggers).
        
        Args:
            workflow_id: The n8n workflow ID
            
        Returns:
            The updated workflow data
        """
        logger.info("activate_workflow", workflow_id=workflow_id)
        
        return await self._request(
            method="POST",
            endpoint=f"/workflows/{workflow_id}/activate",
        )
    
    async def deactivate_workflow(self, workflow_id: str) -> dict:
        """Deactivate a workflow (disable triggers).
        
        Args:
            workflow_id: The n8n workflow ID
            
        Returns:
            The updated workflow data
        """
        logger.info("deactivate_workflow", workflow_id=workflow_id)
        
        return await self._request(
            method="POST",
            endpoint=f"/workflows/{workflow_id}/deactivate",
        )
    
    async def execute_workflow(
        self,
        workflow_id: str,
        data: Optional[dict] = None,
    ) -> dict:
        """Execute a workflow manually.
        
        Note: This requires the workflow to have a Manual Trigger or
        uses the workflow's test execution endpoint.
        
        Args:
            workflow_id: The n8n workflow ID
            data: Optional input data
            
        Returns:
            Execution result
        """
        logger.info("execute_workflow", workflow_id=workflow_id)
        
        body = {}
        if data:
            body["data"] = data
        
        return await self._request(
            method="POST",
            endpoint=f"/workflows/{workflow_id}/run",
            json=body if body else None,
        )
    
    async def get_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """Get workflow executions.
        
        Args:
            workflow_id: Filter by workflow ID
            status: Filter by status (waiting, running, success, error)
            limit: Maximum number of executions
            
        Returns:
            List of executions
        """
        params = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status
        
        return await self._request(
            method="GET",
            endpoint="/executions",
            params=params,
        )
    
    async def get_execution(self, execution_id: str, include_data: bool = True) -> dict:
        """Get a specific execution by ID.
        
        Args:
            execution_id: The execution ID
            include_data: Whether to include full execution data (node outputs)
            
        Returns:
            Execution details including node outputs if include_data=True
        """
        params = {}
        if include_data:
            params["includeData"] = "true"
        
        logger.info(
            "get_execution_request",
            execution_id=execution_id,
            include_data=include_data,
            params=params,
        )
        
        result = await self._request(
            method="GET",
            endpoint=f"/executions/{execution_id}",
            params=params if params else None,
        )
        
        # Debug logging to diagnose data: null issue
        has_data = result.get("data") is not None
        data_keys = list(result.get("data", {}).keys()) if has_data else []
        
        logger.info(
            "get_execution_response",
            execution_id=execution_id,
            status=result.get("status"),
            has_data=has_data,
            data_keys=data_keys,
            result_keys=list(result.keys()),
        )
        
        if not has_data:
            logger.warning(
                "execution_data_is_null",
                execution_id=execution_id,
                hint="Check n8n settings: Save Data on Success should be 'All', not 'None'",
            )
        
        return result
    
    def get_webhook_url(self, webhook_path: str, test_mode: bool = False) -> str:
        """Get the full webhook URL for a given path.
        
        Args:
            webhook_path: The webhook path configured in the workflow
            test_mode: If True, use test webhook URL (for inactive workflows)
            
        Returns:
            Full webhook URL
        """
        # Remove /api/v1 suffix to get base instance URL
        webhook_base = self.base_url.replace("/api/v1", "")
        
        if test_mode:
            return f"{webhook_base}/webhook-test/{webhook_path}"
        return f"{webhook_base}/webhook/{webhook_path}"
    
    async def trigger_webhook(
        self,
        webhook_path: str,
        data: dict,
        method: str = "POST",
        test_mode: bool = False,
        timeout: float = 60.0,
    ) -> dict:
        """Trigger a workflow via webhook.
        
        Args:
            webhook_path: The webhook path configured in the workflow
            data: The payload to send
            method: HTTP method (usually POST)
            test_mode: If True, use test webhook URL (for inactive workflows)
            timeout: Request timeout in seconds
            
        Returns:
            Webhook response with status_code, body, success, and error (if any)
        """
        webhook_url = self.get_webhook_url(webhook_path, test_mode)
        
        logger.info(
            "triggering_webhook",
            url=webhook_url,
            method=method,
            test_mode=test_mode,
            payload_keys=list(data.keys()),
        )
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=webhook_url,
                    json=data,
                    timeout=timeout,
                )
                
                logger.info(
                    "webhook_triggered",
                    path=webhook_path,
                    status_code=response.status_code,
                    test_mode=test_mode,
                )
                
                # Try to parse JSON response
                body = None
                error = None
                try:
                    body = response.json() if response.content else None
                except:
                    body = response.text if response.content else None
                
                if response.status_code >= 400:
                    error = f"HTTP {response.status_code}: {body}"
                
                return {
                    "status_code": response.status_code,
                    "body": body,
                    "success": response.status_code < 400,
                    "error": error,
                    "webhook_url": webhook_url,
                }
                
            except httpx.TimeoutException:
                logger.error("webhook_timeout", path=webhook_path, timeout=timeout)
                return {
                    "status_code": 408,
                    "body": None,
                    "success": False,
                    "error": f"Webhook timed out after {timeout}s",
                    "webhook_url": webhook_url,
                }
            except Exception as e:
                logger.error("webhook_error", path=webhook_path, error=str(e))
                return {
                    "status_code": 500,
                    "body": None,
                    "success": False,
                    "error": str(e),
                    "webhook_url": webhook_url,
                }
    
    async def test_webhook_connectivity(self, webhook_path: str) -> dict:
        """Test if a webhook is reachable.
        
        Sends a minimal OPTIONS/HEAD request to check connectivity.
        
        Args:
            webhook_path: The webhook path to test
            
        Returns:
            Connectivity test result
        """
        webhook_url = self.get_webhook_url(webhook_path, test_mode=False)
        test_url = self.get_webhook_url(webhook_path, test_mode=True)
        
        results = {
            "production_url": webhook_url,
            "test_url": test_url,
            "production_reachable": False,
            "test_reachable": False,
        }
        
        async with httpx.AsyncClient() as client:
            # Test production webhook
            try:
                resp = await client.options(webhook_url, timeout=10.0)
                results["production_reachable"] = resp.status_code < 500
                results["production_status"] = resp.status_code
            except Exception as e:
                results["production_error"] = str(e)
            
            # Test test-mode webhook
            try:
                resp = await client.options(test_url, timeout=10.0)
                results["test_reachable"] = resp.status_code < 500
                results["test_status"] = resp.status_code
            except Exception as e:
                results["test_error"] = str(e)
        
        return results
    
    async def verify_workflow(self, workflow_id: str) -> dict:
        """Verify a workflow was created correctly.
        
        Fetches the workflow and checks for common issues.
        
        Args:
            workflow_id: The n8n workflow ID
            
        Returns:
            Verification result with any issues found
        """
        workflow = await self.get_workflow(workflow_id)
        
        issues = []
        
        # Check nodes exist
        nodes = workflow.get("nodes", [])
        if not nodes:
            issues.append("No nodes in workflow")
        
        # Check connections exist
        connections = workflow.get("connections", {})
        if not connections and len(nodes) > 1:
            issues.append("No connections between nodes")
        
        # Check all nodes have positions
        for node in nodes:
            if "position" not in node:
                issues.append(f"Node '{node.get('name')}' missing position")
        
        # Check for trigger node
        has_trigger = any(
            "trigger" in node.get("type", "").lower()
            for node in nodes
        )
        if not has_trigger:
            issues.append("No trigger node found")
        
        return {
            "workflow_id": workflow_id,
            "valid": len(issues) == 0,
            "issues": issues,
            "node_count": len(nodes),
            "connection_count": sum(
                len(outputs)
                for node_conns in connections.values()
                for outputs in node_conns.get("main", [])
            ),
        }
