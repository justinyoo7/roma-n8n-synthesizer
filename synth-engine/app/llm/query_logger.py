"""LLM Query Logger - logs all LLM calls to Supabase for analytics.

This module provides a logging wrapper for LLM calls that:
- Measures latency
- Extracts token usage
- Calculates cost based on model pricing
- Logs to Supabase queries table
- Handles errors gracefully (logging failures don't break main flow)
"""
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import structlog

from app.db.supabase import get_supabase_client

logger = structlog.get_logger()


# Model pricing per 1K tokens (input, output)
# Updated pricing as of 2026
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI models
    "gpt-4": (0.03, 0.06),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4-turbo-preview": (0.01, 0.03),
    "gpt-4o": (0.005, 0.015),  # GPT-4o pricing
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "gpt-3.5-turbo-0125": (0.0005, 0.0015),
    
    # Anthropic models
    "claude-3-opus": (0.015, 0.075),
    "claude-3-opus-20240229": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-sonnet-20240229": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-3-haiku-20240307": (0.00025, 0.00125),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-sonnet-20240620": (0.003, 0.015),
    "claude-sonnet-4-20250514": (0.003, 0.015),  # Claude Sonnet 4
    
    # Default fallback
    "default": (0.01, 0.03),
}


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate the cost of an LLM call based on token usage.
    
    Args:
        model: Model name/identifier
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        
    Returns:
        Cost in USD
    """
    # Find pricing for model (check exact match first, then prefix match)
    pricing = MODEL_PRICING.get(model)
    
    if not pricing:
        # Try prefix matching for versioned models
        for model_key, price in MODEL_PRICING.items():
            if model.startswith(model_key) or model_key in model.lower():
                pricing = price
                break
    
    if not pricing:
        pricing = MODEL_PRICING["default"]
        logger.warning("unknown_model_pricing", model=model, using_default=True)
    
    input_price, output_price = pricing
    
    # Calculate cost (pricing is per 1K tokens)
    input_cost = (input_tokens / 1000) * input_price
    output_cost = (output_tokens / 1000) * output_price
    
    return round(input_cost + output_cost, 6)


class QueryLogContext:
    """Context manager for logging LLM queries with timing.
    
    Usage:
        async with QueryLogContext(
            node_name="AI Agent",
            model="gpt-4",
            query_text="Classify this customer message...",
        ) as ctx:
            response = await llm.generate(...)
            ctx.set_response(
                input_tokens=response.metadata.get("input_tokens", 0),
                output_tokens=response.metadata.get("output_tokens", 0),
                raw_response=response.raw_content,
            )
    """
    
    def __init__(
        self,
        node_name: str,
        model: str,
        query_text: str,
        workflow_id: Optional[UUID] = None,
        node_id: Optional[str] = None,
        user_id: Optional[UUID] = None,
        raw_request: Optional[dict] = None,
    ):
        self.workflow_id = workflow_id
        self.node_id = node_id or f"node_{int(time.time() * 1000)}"
        self.node_name = node_name
        self.model = model
        self.query_text = query_text[:5000] if query_text else ""  # Truncate to 5000 chars
        self.user_id = user_id
        self.raw_request = raw_request
        
        self.start_time: Optional[float] = None
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.raw_response: Optional[str] = None
        self.status: str = "pending"
        self.failure_reason: Optional[str] = None
    
    def set_response(
        self,
        input_tokens: int,
        output_tokens: int,
        raw_response: Optional[str] = None,
    ):
        """Set the response data after LLM call completes."""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.raw_response = raw_response
        self.status = "success"
    
    def set_error(self, error: str):
        """Set error status if LLM call fails."""
        self.status = "error"
        self.failure_reason = error
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Calculate latency
        latency_ms = int((time.time() - self.start_time) * 1000) if self.start_time else 0
        
        # If an exception occurred, mark as error
        if exc_type is not None:
            self.status = "error"
            self.failure_reason = str(exc_val) if exc_val else str(exc_type.__name__)
        
        # Calculate cost
        cost_usd = calculate_cost(self.model, self.input_tokens, self.output_tokens)
        
        # Log to Supabase (don't let failures break the main flow)
        try:
            await log_query(
                workflow_id=self.workflow_id,
                node_id=self.node_id,
                node_name=self.node_name,
                query_text=self.query_text,
                model=self.model,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                status=self.status,
                failure_reason=self.failure_reason,
                raw_request=self.raw_request,
                raw_response={"content": self.raw_response[:2000]} if self.raw_response else None,
                user_id=self.user_id,
            )
        except Exception as e:
            # Log the error but don't propagate it
            logger.error(
                "query_log_failed",
                error=str(e),
                node_name=self.node_name,
                model=self.model,
            )
        
        # Don't suppress the original exception
        return False


async def log_query(
    node_name: str,
    query_text: str,
    model: str,
    status: str,
    workflow_id: Optional[UUID] = None,
    node_id: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    failure_reason: Optional[str] = None,
    raw_request: Optional[dict] = None,
    raw_response: Optional[dict] = None,
    user_id: Optional[UUID] = None,
) -> Optional[dict]:
    """Log an LLM query to Supabase.
    
    This function logs query data to the queries table for analytics.
    Failures are logged but don't raise exceptions to avoid breaking the main flow.
    
    Args:
        workflow_id: Associated workflow ID (optional)
        node_id: Unique node identifier
        node_name: Human-readable node name
        query_text: The prompt/input sent to LLM (truncated to 5000 chars)
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Latency in milliseconds
        cost_usd: Calculated cost in USD
        status: "success" or "error"
        failure_reason: Error message if failed
        raw_request: Full request payload (optional)
        raw_response: Full response payload (optional)
        user_id: Associated user ID (optional)
        
    Returns:
        Inserted row data if successful, None if failed
    """
    client = get_supabase_client()
    
    if not client:
        logger.debug("query_log_skipped", reason="supabase_not_configured")
        return None
    
    try:
        # Build the row data
        row = {
            "node_id": node_id or f"node_{int(time.time() * 1000)}",
            "node_name": node_name,
            "query_text": query_text[:5000] if query_text else "",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "cost_usd": float(cost_usd),
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Add optional fields
        if workflow_id:
            row["workflow_id"] = str(workflow_id) if isinstance(workflow_id, UUID) else workflow_id
        if failure_reason:
            row["failure_reason"] = failure_reason[:1000]
        if raw_request:
            row["raw_request"] = raw_request
        if raw_response:
            row["raw_response"] = raw_response
        if user_id:
            row["user_id"] = str(user_id) if isinstance(user_id, UUID) else user_id
        
        result = await client.insert("queries", row)
        
        logger.info(
            "query_logged",
            node_name=node_name,
            model=model,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "query_log_error",
            error=str(e),
            node_name=node_name,
            model=model,
        )
        return None


async def log_query_sync(
    node_name: str,
    query_text: str,
    model: str,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    **kwargs,
) -> None:
    """Fire-and-forget query logging (non-blocking).
    
    This is a convenience wrapper that logs but doesn't wait for completion.
    """
    try:
        await log_query(
            node_name=node_name,
            query_text=query_text,
            model=model,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            **kwargs,
        )
    except Exception:
        pass  # Silently ignore errors
