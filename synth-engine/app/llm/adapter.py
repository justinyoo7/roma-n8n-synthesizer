"""Unified LLM adapter supporting both Anthropic and OpenAI."""
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Literal, Optional
from uuid import UUID

import structlog
from pydantic import BaseModel

from app.config import get_settings

logger = structlog.get_logger()


class LLMResponse(BaseModel):
    """Standardized LLM response."""
    
    content: Any  # Parsed content (dict for JSON, str for text)
    raw_content: str  # Raw text response
    metadata: dict = {}
    
    # Logging metadata (optional, populated when logging is enabled)
    logged: bool = False
    log_id: Optional[str] = None


class LLMAdapter(ABC):
    """Abstract base class for LLM adapters."""
    
    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        pass
    
    @abstractmethod
    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response with tool use capabilities."""
        pass


class AnthropicAdapter(LLMAdapter):
    """Adapter for Anthropic Claude models."""
    
    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
    
    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse:
        """Generate a response using Claude."""
        
        # Add JSON instruction if needed
        if response_format == "json":
            system_prompt = f"{system_prompt}\n\nIMPORTANT: Respond with valid JSON only. No markdown, no explanation."
        
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        
        raw_content = response.content[0].text
        
        # Parse JSON if requested
        if response_format == "json":
            try:
                # Handle potential markdown code blocks
                content_text = raw_content.strip()
                if content_text.startswith("```"):
                    # Extract content between first ``` and last ```
                    parts = content_text.split("```")
                    if len(parts) >= 2:
                        content_text = parts[1]
                        # Remove "json" language tag if present
                        if content_text.startswith("json"):
                            content_text = content_text[4:]
                        elif content_text.startswith("\n"):
                            content_text = content_text[1:]
                    content_text = content_text.strip()
                
                # Try direct JSON parse first
                try:
                    content = json.loads(content_text)
                except json.JSONDecodeError:
                    # Try to find JSON object in the text
                    start_idx = content_text.find('{')
                    end_idx = content_text.rfind('}')
                    
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_str = content_text[start_idx:end_idx + 1]
                        content = json.loads(json_str)
                    else:
                        raise
                        
            except json.JSONDecodeError:
                content = {"error": "Failed to parse JSON", "raw": raw_content[:500]}
        else:
            content = raw_content
        
        return LLMResponse(
            content=content,
            raw_content=raw_content,
            metadata={
                "model": self.model,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
    
    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response with tool use."""
        
        # Convert tools to Anthropic format
        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
            })
        
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            tools=anthropic_tools,
        )
        
        # Extract content and tool calls
        content = {}
        tool_calls = []
        
        for block in response.content:
            if block.type == "text":
                content["text"] = block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })
        
        content["tool_calls"] = tool_calls
        
        return LLMResponse(
            content=content,
            raw_content=str(response.content),
            metadata={
                "model": self.model,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
                "stop_reason": response.stop_reason,
            },
        )


class OpenAIAdapter(LLMAdapter):
    """Adapter for OpenAI GPT models."""
    
    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
    
    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse:
        """Generate a response using GPT."""
        
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        
        # Use JSON mode if available
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        
        response = await self.client.chat.completions.create(**kwargs)
        
        raw_content = response.choices[0].message.content or ""
        
        # Parse JSON if requested
        if response_format == "json":
            try:
                content = json.loads(raw_content)
            except json.JSONDecodeError:
                content = {"error": "Failed to parse JSON", "raw": raw_content}
        else:
            content = raw_content
        
        return LLMResponse(
            content=content,
            raw_content=raw_content,
            metadata={
                "model": self.model,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )
    
    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response with tool use."""
        
        # Convert tools to OpenAI format
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            })
        
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            tools=openai_tools,
            tool_choice="auto",
        )
        
        message = response.choices[0].message
        content = {"text": message.content or ""}
        
        # Extract tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments) if tc.function.arguments else {},
                })
        
        content["tool_calls"] = tool_calls
        
        return LLMResponse(
            content=content,
            raw_content=str(message),
            metadata={
                "model": self.model,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
                "finish_reason": response.choices[0].finish_reason,
            },
        )


# Singleton adapter instance
_adapter: Optional[LLMAdapter] = None


def get_llm_adapter() -> LLMAdapter:
    """Get the configured LLM adapter instance."""
    global _adapter
    
    if _adapter is None:
        settings = get_settings()
        
        if settings.llm_provider == "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            _adapter = AnthropicAdapter(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
        elif settings.llm_provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            _adapter = OpenAIAdapter(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
            )
        else:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
    
    return _adapter


def reset_adapter():
    """Reset the adapter (for testing)."""
    global _adapter
    _adapter = None


async def generate_with_logging(
    system_prompt: str,
    user_message: str,
    node_name: str = "LLM Call",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    response_format: Literal["text", "json"] = "text",
    workflow_id: Optional[UUID] = None,
    node_id: Optional[str] = None,
    user_id: Optional[UUID] = None,
    adapter: Optional[LLMAdapter] = None,
) -> LLMResponse:
    """Generate LLM response with automatic query logging.
    
    This is a convenience wrapper that logs all LLM calls to Supabase.
    Logging failures don't break the main flow.
    
    Args:
        system_prompt: System prompt for the LLM
        user_message: User message for the LLM
        node_name: Human-readable name for logging (e.g., "AI Classifier")
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        response_format: "text" or "json"
        workflow_id: Associated workflow ID for tracking
        node_id: Unique node identifier
        user_id: Associated user ID
        adapter: Optional LLM adapter (uses default if not provided)
        
    Returns:
        LLMResponse with content, raw_content, and metadata
    """
    # Import here to avoid circular imports
    from app.llm.query_logger import log_query, calculate_cost
    
    llm = adapter or get_llm_adapter()
    start_time = time.time()
    status = "success"
    failure_reason = None
    response = None
    
    try:
        response = await llm.generate(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        return response
        
    except Exception as e:
        status = "error"
        failure_reason = str(e)
        raise
        
    finally:
        # Calculate metrics
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Extract token usage from response metadata
        input_tokens = 0
        output_tokens = 0
        model = "unknown"
        
        if response and response.metadata:
            input_tokens = response.metadata.get("input_tokens", 0)
            output_tokens = response.metadata.get("output_tokens", 0)
            model = response.metadata.get("model", "unknown")
        elif hasattr(llm, "model"):
            model = llm.model
        
        # Calculate cost
        cost_usd = calculate_cost(model, input_tokens, output_tokens)
        
        # Log to Supabase (fire and forget - errors won't break main flow)
        try:
            # Build query text (combine system prompt and user message, truncate)
            query_text = f"[System]: {system_prompt[:1000]}...\n\n[User]: {user_message[:3500]}..."
            if len(system_prompt) <= 1000:
                query_text = f"[System]: {system_prompt}\n\n[User]: {user_message[:4000]}..."
            
            log_result = await log_query(
                workflow_id=workflow_id,
                node_id=node_id or f"node_{int(time.time() * 1000)}",
                node_name=node_name,
                query_text=query_text,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                status=status,
                failure_reason=failure_reason,
                raw_request={"system": system_prompt[:500], "user": user_message[:500]},
                raw_response={"content": response.raw_content[:1000]} if response else None,
                user_id=user_id,
            )
            
            # Mark response as logged
            if response:
                response.logged = True
                if log_result:
                    response.log_id = str(log_result.get("id"))
            
            # Log success/failure
            if log_result:
                logger.debug("llm_query_logged", node_name=node_name, log_id=log_result.get("id"))
            else:
                logger.warning("llm_query_log_returned_none", node_name=node_name)
                
        except Exception as log_error:
            # Don't let logging errors break the main flow, but log them clearly
            logger.error(
                "llm_query_log_failed",
                error=str(log_error),
                error_type=type(log_error).__name__,
                node_name=node_name,
            )


async def generate_with_tools_and_logging(
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    node_name: str = "LLM Tool Call",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    workflow_id: Optional[UUID] = None,
    node_id: Optional[str] = None,
    user_id: Optional[UUID] = None,
    adapter: Optional[LLMAdapter] = None,
) -> LLMResponse:
    """Generate LLM response with tools and automatic query logging.
    
    Similar to generate_with_logging but for tool-enabled calls.
    """
    from app.llm.query_logger import log_query, calculate_cost
    
    llm = adapter or get_llm_adapter()
    start_time = time.time()
    status = "success"
    failure_reason = None
    response = None
    
    try:
        response = await llm.generate_with_tools(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response
        
    except Exception as e:
        status = "error"
        failure_reason = str(e)
        raise
        
    finally:
        latency_ms = int((time.time() - start_time) * 1000)
        
        input_tokens = 0
        output_tokens = 0
        model = "unknown"
        
        if response and response.metadata:
            input_tokens = response.metadata.get("input_tokens", 0)
            output_tokens = response.metadata.get("output_tokens", 0)
            model = response.metadata.get("model", "unknown")
        elif hasattr(llm, "model"):
            model = llm.model
        
        cost_usd = calculate_cost(model, input_tokens, output_tokens)
        
        try:
            tool_names = [t.get("name", "unknown") for t in tools[:5]]
            query_text = f"[System]: {system_prompt[:1000]}...\n\n[User]: {user_message[:3000]}...\n\n[Tools]: {tool_names}"
            
            log_result = await log_query(
                workflow_id=workflow_id,
                node_id=node_id or f"node_{int(time.time() * 1000)}",
                node_name=node_name,
                query_text=query_text,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                status=status,
                failure_reason=failure_reason,
                raw_request={"system": system_prompt[:500], "user": user_message[:500], "tools": tool_names},
                raw_response={"content": response.raw_content[:1000]} if response else None,
                user_id=user_id,
            )
            
            if response:
                response.logged = True
                if log_result:
                    response.log_id = str(log_result.get("id"))
            
            if log_result:
                logger.debug("llm_query_logged", node_name=node_name, log_id=log_result.get("id"))
            else:
                logger.warning("llm_query_log_returned_none", node_name=node_name)
                
        except Exception as log_error:
            logger.error(
                "llm_query_log_failed",
                error=str(log_error),
                error_type=type(log_error).__name__,
                node_name=node_name,
            )
