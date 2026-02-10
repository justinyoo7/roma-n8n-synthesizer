"""Compiler to transform WorkflowIR to n8n workflow JSON.

The compiler handles:
- Converting StepSpec to n8n node format
- Building the connections graph
- Setting appropriate positions for layout
- Handling branching and merging
"""
from typing import Any, Optional
import copy
from uuid import uuid4

import structlog

from app.models.workflow_ir import (
    WorkflowIR,
    StepSpec,
    EdgeSpec,
    StepType,
    TriggerType,
)
from app.n8n.node_catalog import get_node_definition, N8N_NODE_CATALOG
from app.config import get_settings

logger = structlog.get_logger()


class N8NCompiler:
    """Compiles WorkflowIR to n8n workflow JSON format."""
    
    def __init__(self, route_apis_through_perseus: bool = True):
        """Initialize compiler.
        
        Args:
            route_apis_through_perseus: If True, route Apollo/Phantombuster calls
                through Perseus agent-runner for logging. If False, use direct API calls.
        """
        self.node_id_map: dict[str, str] = {}  # IR step ID -> n8n node ID
        self.route_apis_through_perseus = route_apis_through_perseus
    
    def compile(self, ir: WorkflowIR) -> dict:
        """Compile a WorkflowIR to n8n workflow JSON.
        
        Returns a dict in n8n workflow format:
        {
            "name": str,
            "nodes": [...],
            "connections": {...},
            "settings": {...}
        }
        """
        logger.info("compile_start", workflow_name=ir.name)
        
        # Reset ID mapping
        self.node_id_map = {}
        
        # Compile all nodes
        nodes = []
        
        # Compile trigger first
        trigger_node = self._compile_step(ir.trigger)
        nodes.append(trigger_node)
        
        # Compile other steps
        for step in ir.steps:
            node = self._compile_step(step)
            nodes.append(node)
        
        # Safety net: Convert any direct AI API calls to agent-runner calls
        nodes = [self._convert_direct_ai_calls(node) for node in nodes]
        
        # Configure external API nodes
        if self.route_apis_through_perseus:
            # Route through Perseus for logging
            nodes = [self._route_api_through_perseus(node) for node in nodes]
        else:
            # Direct API calls with auth configured
            nodes = [self._configure_external_api_node(node) for node in nodes]
        
        # Compile connections
        connections = self._compile_connections(ir)
        
        # Build final workflow JSON
        # Note: 'tags' and 'staticData' are read-only in n8n API - don't include them
        workflow = {
            "name": ir.name,
            "nodes": nodes,
            "connections": connections,
            "settings": {
                "executionOrder": "v1",
                "saveManualExecutions": True,
                "callerPolicy": "workflowsFromSameOwner",
            },
        }
        
        logger.info(
            "compile_complete",
            node_count=len(nodes),
            connection_count=sum(len(v) for v in connections.values()),
        )
        
        return workflow
    
    def _compile_step(self, step: StepSpec) -> dict:
        """Compile a single step to n8n node format."""
        
        # Generate n8n node ID
        n8n_id = str(uuid4())
        self.node_id_map[step.id] = n8n_id
        
        # Get node definition for defaults
        node_def = None
        for key, definition in N8N_NODE_CATALOG.items():
            if definition.type == step.n8n_node_type:
                node_def = definition
                break
        
        # Build parameters
        parameters = self._build_parameters(step, node_def)
        self._log_parameter_anomalies(step, node_def, parameters)
        
        # Determine node type (may be overridden for agent steps)
        node_type = step.n8n_node_type
        type_version = step.n8n_type_version
        
        # Force specific versions for certain node types
        if step.n8n_node_type == "n8n-nodes-base.itemLists":
            type_version = 3  # Use v3 for better split functionality
        elif step.n8n_node_type in ("n8n-nodes-base.switch", "n8n-nodes-base.merge") and node_def:
            type_version = node_def.type_version
        
        # Handle agent steps - compile to HTTP Request to agent-runner
        if step.type == StepType.AGENT and step.agent:
            parameters = self._build_agent_parameters(step)
            node_type = "n8n-nodes-base.httpRequest"  # Force HTTP request for agents
            type_version = 4  # Use latest httpRequest version
            logger.info(
                "compiling_agent_step",
                step_name=step.name,
                agent_name=step.agent.name,
            )
        
        # Convert direct API calls (Apollo, Perplexity, etc.) to agent-runner
        # This is more reliable than trying to inject API keys into HTTP nodes
        elif step.n8n_node_type == "n8n-nodes-base.httpRequest":
            url = str(parameters.get("url", ""))
            step_name_lower = step.name.lower()
            
            # Detect Apollo API calls
            if "api.apollo.io" in url or "apollo" in step_name_lower:
                parameters = self._build_api_agent_parameters(step, "apollo_agent", "Search and enrich leads using Apollo.io")
                node_type = "n8n-nodes-base.httpRequest"
                type_version = 4
                logger.info("converting_apollo_to_agent", step_name=step.name)
            
            # Detect Perplexity API calls
            elif "api.perplexity.ai" in url or "perplexity" in step_name_lower or "research" in step_name_lower:
                parameters = self._build_api_agent_parameters(step, "research_agent", "Research using Perplexity AI")
                node_type = "n8n-nodes-base.httpRequest"
                type_version = 4
                logger.info("converting_perplexity_to_agent", step_name=step.name)
            
            # Detect Phantombuster API calls
            elif "api.phantombuster.com" in url or "phantombuster" in step_name_lower or "linkedin" in step_name_lower:
                parameters = self._build_api_agent_parameters(step, "phantombuster_agent", "LinkedIn automation via Phantombuster")
                node_type = "n8n-nodes-base.httpRequest"
                type_version = 4
                logger.info("converting_phantombuster_to_agent", step_name=step.name)
        
        node = {
            "id": n8n_id,
            "name": step.name,
            "type": node_type,
            "typeVersion": type_version,
            "position": [step.position.x, step.position.y],
            "parameters": parameters,
        }
        
        # Add webhookId for webhook triggers (required by n8n Cloud)
        if step.n8n_node_type == "n8n-nodes-base.webhook":
            if "webhookId" not in node:
                node["webhookId"] = str(uuid4())[:8]
        
        return node
    
    def _build_parameters(
        self,
        step: StepSpec,
        node_def: Optional[Any],
    ) -> dict:
        """Build n8n node parameters from step spec."""
        
        # Start with step's parameters
        params = dict(step.parameters)
        
        # Handle specific node types
        if step.n8n_node_type == "n8n-nodes-base.webhook":
            params.setdefault("httpMethod", "POST")
            # Generate unique webhook path based on step ID for reliable triggering
            default_path = f"workflow-{step.id[:8]}"
            params.setdefault("path", step.trigger_config.get("path", default_path) if step.trigger_config else default_path)
            # Use responseNode for compatibility with respondToWebhook
            params.setdefault("responseMode", "responseNode")
            params.setdefault("options", {})
        
        elif step.n8n_node_type == "n8n-nodes-base.switch":
            # Build switch rules from branch conditions
            params["rules"] = self._build_switch_rules(step.branch_conditions or [])
            params.setdefault("mode", "rules")
        
        elif step.n8n_node_type == "n8n-nodes-base.if":
            # Build IF conditions
            if step.branch_conditions and len(step.branch_conditions) > 0:
                params["conditions"] = self._build_if_conditions(step.branch_conditions[0])
        
        elif step.n8n_node_type == "n8n-nodes-base.respondToWebhook":
            params.setdefault("respondWith", "json")
            # Always use a simple, reliable response expression
            # This handles both agent outputs (.output field) and regular data
            # The || $json fallback ensures we always return something
            params["responseBody"] = "={{ $json.output || $json }}"
        
        elif step.n8n_node_type == "n8n-nodes-base.set":
            # Fix Set node parameters to use correct v1 format
            params = self._fix_set_node_params(params)
        
        elif step.n8n_node_type == "n8n-nodes-base.itemLists":
            # Item Lists node v3 - for splitting/aggregating arrays
            # Default to "Split Out Items" operation which loops over array items
            params.setdefault("operation", "splitOutItems")
            # FORCE correct field path - Apollo/ICP agents return contacts at output.contacts
            # (strict format enforced in agent prompts)
            params["fieldToSplitOut"] = "output.contacts"
            # Include any input items in output (required for proper data flow)
            params.setdefault("include", "noOtherFields")
            params.setdefault("options", {})
        
        elif step.n8n_node_type == "n8n-nodes-base.aggregate":
            # Aggregate node - combines items back into array
            params.setdefault("aggregate", "aggregateAllItemData")
            params.setdefault("destinationFieldName", "results")
            params.setdefault("options", {})
        
        elif step.n8n_node_type == "n8n-nodes-base.splitInBatches":
            # Split In Batches - process items in groups
            params.setdefault("batchSize", 10)
            params.setdefault("options", {})
        
        elif step.n8n_node_type == "n8n-nodes-base.merge":
            # Merge node - combine data from multiple branches
            params.setdefault("mode", "combine")
            params.setdefault("combinationMode", "mergeByPosition")
            params.setdefault("options", {})
        
        elif step.n8n_node_type == "n8n-nodes-base.noOp":
            # No Operation - pass through
            params = {}
        
        return self._sanitize_parameters(params, path=[step.name])

    def _log_parameter_anomalies(self, step: StepSpec, node_def: Optional[Any], params: dict) -> None:
        """Log suspicious parameter keys for debugging n8n import issues."""
        # Log any "option" keys (singular) anywhere in parameters
        for path in self._find_key_paths(params, target_key="option"):
            logger.warning(
                "n8n_parameter_option_found",
                node_name=step.name,
                node_type=step.n8n_node_type,
                path=".".join(path),
            )

        # Log unknown top-level keys compared to catalog (best-effort)
        if node_def and getattr(node_def, "parameters", None) is not None:
            allowed = {p.name for p in node_def.parameters}
            extra_keys = sorted(set(params.keys()) - allowed)
            if extra_keys:
                logger.warning(
                    "n8n_parameter_unknown_keys",
                    node_name=step.name,
                    node_type=step.n8n_node_type,
                    extra_keys=extra_keys,
                    allowed=sorted(allowed),
                )

    def _find_key_paths(self, value: Any, target_key: str, path: Optional[list[str]] = None) -> list[list[str]]:
        if path is None:
            path = []
        matches: list[list[str]] = []
        if isinstance(value, dict):
            for key, item in value.items():
                next_path = path + [key]
                if key == target_key:
                    matches.append(next_path)
                matches.extend(self._find_key_paths(item, target_key, next_path))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                matches.extend(self._find_key_paths(item, target_key, path + [f"[{idx}]"]))
        return matches

    def _sanitize_parameters(self, params: Any, path: list[str]) -> Any:
        """Normalize common param mistakes from LLM outputs.

        n8n does not recognize a top-level 'option' key (expects 'options').
        If we see 'option' and no 'options', rename it. Also sanitize nested
        structures to prevent n8n editor load errors.
        """
        if isinstance(params, str):
            normalized = self._normalize_expression(params)
            if normalized != params:
                logger.warning(
                    "n8n_expression_normalized",
                    path=".".join(path),
                    before=params,
                    after=normalized,
                )
            return normalized
        if isinstance(params, list):
            return [self._sanitize_parameters(item, path=path + [f"[{idx}]"]) for idx, item in enumerate(params)]
        if not isinstance(params, dict):
            return params

        has_options = "options" in params
        sanitized: dict = {}
        for key, value in params.items():
            normalized_key = key
            if key == "option" and not has_options:
                logger.warning(
                    "n8n_parameter_key_renamed",
                    from_key="option",
                    to_key="options",
                    path=".".join(path),
                )
                normalized_key = "options"
            if key == "option" and has_options:
                logger.warning(
                    "n8n_parameter_key_dropped",
                    key="option",
                    reason="options already present",
                    path=".".join(path),
                )
                continue
            normalized_value = self._sanitize_parameters(value, path=path + [normalized_key])
            if normalized_key == "leftValue" and isinstance(normalized_value, str):
                fixed_value = self._normalize_expression(normalized_value)
                if fixed_value != normalized_value:
                    logger.warning(
                        "n8n_expression_normalized",
                        path=".".join(path + [normalized_key]),
                        before=normalized_value,
                        after=fixed_value,
                    )
                normalized_value = fixed_value
            sanitized[normalized_key] = normalized_value

        return sanitized

    def _normalize_expression(self, value: str) -> str:
        """Normalize malformed n8n expressions (e.g., '={ ... }')."""
        trimmed = value.strip()
        if trimmed.startswith("={{"):
            return trimmed
        if trimmed.startswith("={"):
            inner = trimmed[2:-1].strip() if trimmed.endswith("}") else trimmed[2:].strip()
            return f"={{ {inner} }}"
        return value
    
    def _fix_set_node_params(self, params: dict) -> dict:
        """Fix Set node parameters to use the correct n8n v1 format.
        
        The correct format is:
        {
            "values": {
                "string": [
                    {"name": "field_name", "value": "field_value"},
                    ...
                ]
            }
        }
        
        LLMs often generate incorrect formats like:
        {
            "values": {
                "field_name": "field_value"
            }
        }
        
        Also fixes node references - LLMs generate $('node_id') but n8n
        expects $('Node Name'). We replace these with $json which always
        refers to the previous node's output.
        """
        values = params.get("values", {})
        
        # If already in correct format, check for bad references
        if isinstance(values, dict) and "string" in values:
            # Fix any $('node_id') references to use $json instead
            for item in values.get("string", []):
                if isinstance(item, dict) and "value" in item:
                    item["value"] = self._fix_node_references(item["value"])
            return params
        
        # Convert from flat format to correct format
        if isinstance(values, dict):
            string_values = []
            for key, value in values.items():
                if key in ("string", "number", "boolean"):
                    # Already in a typed format, skip
                    continue
                # Fix node references in values
                fixed_value = self._fix_node_references(value) if isinstance(value, str) else str(value)
                string_values.append({
                    "name": key,
                    "value": fixed_value,
                })
            
            if string_values:
                params["values"] = {
                    "string": string_values,
                }
                params.setdefault("options", {})
        
        return params
    
    def _fix_node_references(self, value: str) -> str:
        """Replace problematic node references with $json.
        
        LLMs generate references like $('analyze_sentiment') using step IDs,
        but n8n expects node names like $('Analyze Message Sentiment').
        
        The safest fix is to replace any $('...') reference with $json,
        which refers to the previous node's output.
        """
        import re
        
        # Pattern to match $('anything') or $("anything")
        # Replace with equivalent $json reference
        def replace_reference(match):
            # Get the field path after the node reference
            full_match = match.group(0)
            
            # Check if there's a .item.json or similar accessor
            if '.item.json.' in full_match or '.item(0).json.' in full_match:
                # Extract the field name
                if '.item.json.' in full_match:
                    field = full_match.split('.item.json.')[-1]
                else:
                    field = full_match.split('.item(0).json.')[-1]
                return f"$json.{field}"
            elif '.json.' in full_match:
                field = full_match.split('.json.')[-1]
                return f"$json.{field}"
            else:
                # Just the node reference, return the whole json
                return "$json"
        
        # Match $('node_name').item.json.field or $('node_name').json.field patterns
        pattern = r"\$\(['\"][^'\"]+['\"]\)(?:\.item(?:\(\d+\))?)?(?:\.json)?(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?"
        
        result = re.sub(pattern, replace_reference, value)
        return result
    
    def _build_agent_parameters(self, step: StepSpec) -> dict:
        """Build HTTP Request v4 parameters for agent-runner call."""
        
        agent = step.agent
        settings = get_settings()
        
        # Use hardcoded URL from config (n8n Cloud blocks $env access)
        agent_runner_url = settings.agent_runner_url or "https://YOUR_AGENT_RUNNER_URL"
        
        # Build task description from agent role
        task_description = agent.role if agent.role else f"Process data as {agent.name}"
        
        # Escape quotes in task description for JSON embedding
        task_description_escaped = task_description.replace('"', '\\"')
        
        # HTTP Request v4 format - using string body with expression
        # Include n8n_workflow_id for tracking - agent runner will look up internal ID
        json_body = f"""={{{{ JSON.stringify({{
  "agent_name": "{agent.name}",
  "input": Object.assign({{}}, ($json.body || $json), {{ task: "{task_description_escaped}" }}),
  "context": {{}},
  "tools_allowed": [],
  "n8n_workflow_id": $workflow.id,
  "node_id": "{step.id}"
}}) }}}}"""
        
        return {
            "method": "POST",
            "url": f"{agent_runner_url}/api/agent/run",
            "authentication": "none",
            "sendBody": True,
            "specifyBody": "string",
            "body": json_body,
            "contentType": "raw",
            "rawContentType": "application/json",
            "options": {
                "timeout": 120000,  # 2 minutes timeout for agent operations
            },
        }
    
    def _build_api_agent_parameters(self, step: StepSpec, agent_name: str, task_description: str) -> dict:
        """Build HTTP Request parameters to route API calls through agent-runner.
        
        This converts direct API calls (Apollo, Perplexity, etc.) to agent-runner calls.
        The agent-runner has the API keys and proper integration code.
        All calls are logged for analytics.
        """
        settings = get_settings()
        agent_runner_url = settings.agent_runner_url or "https://YOUR_AGENT_RUNNER_URL"
        
        task_description_escaped = task_description.replace('"', '\\"')
        
        # Pass n8n_workflow_id for tracking - agent runner will look up internal ID
        json_body = f"""={{{{ JSON.stringify({{
  "agent_name": "{agent_name}",
  "input": Object.assign({{}}, $json, {{ task: "{task_description_escaped}" }}),
  "context": {{}},
  "tools_allowed": [],
  "n8n_workflow_id": $workflow.id,
  "node_id": "{step.id}"
}}) }}}}"""
        
        return {
            "method": "POST",
            "url": f"{agent_runner_url}/api/agent/run",
            "authentication": "none",
            "sendBody": True,
            "specifyBody": "string",
            "body": json_body,
            "contentType": "raw",
            "rawContentType": "application/json",
            "options": {
                "timeout": 120000,
            },
        }
    
    def _convert_direct_ai_calls(self, node: dict) -> dict:
        """Safety net: Detect direct AI API calls and convert to agent-runner.
        
        This catches cases where the LLM generates direct calls to OpenAI/Anthropic
        instead of using the agent pattern, and converts them to agent-runner calls.
        """
        # Only process httpRequest nodes
        if node.get("type") != "n8n-nodes-base.httpRequest":
            return node
        
        params = node.get("parameters", {})
        url = params.get("url", "")
        
        # Detect direct AI API calls
        ai_api_patterns = [
            "api.openai.com",
            "api.anthropic.com",
            "openai.azure.com",
            "generativelanguage.googleapis.com",  # Google AI
        ]
        
        is_ai_call = any(pattern in url for pattern in ai_api_patterns)
        
        if not is_ai_call:
            return node
        
        logger.info(
            "converting_direct_ai_call",
            node_name=node.get("name"),
            original_url=url,
        )
        
        # Extract agent name from node name or generate one
        agent_name = node.get("name", "ai_agent").lower().replace(" ", "_")
        
        # Build agent-runner parameters
        settings = get_settings()
        agent_runner_url = settings.agent_runner_url or "https://YOUR_AGENT_RUNNER_URL"
        
        # Try to extract system prompt from the original request body
        body = params.get("body", {})
        system_prompt = ""
        if isinstance(body, dict):
            messages = body.get("messages", [])
            for msg in messages:
                if isinstance(msg, dict) and msg.get("role") == "system":
                    system_prompt = msg.get("content", "")
                    break
        
        # Convert to agent-runner call (HTTP Request v4 format)
        context_obj = f'{{"system_prompt": "{system_prompt[:200]}"}}' if system_prompt else '{}'
        json_body = f"""={{{{ JSON.stringify({{
  "agent_name": "{agent_name}",
  "input": $json,
  "context": {context_obj},
  "tools_allowed": []
}}) }}}}"""
        
        converted_params = {
            "method": "POST",
            "url": f"{agent_runner_url}/api/agent/run",
            "authentication": "none",
            "sendBody": True,
            "specifyBody": "string",
            "body": json_body,
            "contentType": "raw",
            "rawContentType": "application/json",
            "options": {
                "timeout": 120000,  # 2 minutes timeout for agent operations
            },
        }
        
        # Return converted node
        return {
            **node,
            "parameters": converted_params,
        }
    
    def _configure_external_api_node(self, node: dict) -> dict:
        """Configure external API nodes with proper authentication.
        
        This handles APIs like Apollo.io, Clearbit, etc. that require
        API keys in specific ways (body, headers, query params).
        """
        # Only process httpRequest nodes
        if node.get("type") != "n8n-nodes-base.httpRequest":
            return node
        
        params = node.get("parameters", {})
        url = params.get("url", "")
        
        settings = get_settings()
        
        # Apollo.io - needs api_key in request body
        if "api.apollo.io" in url:
            api_key = settings.apollo_api_key
            if api_key:
                # Apollo uses api_key in the JSON body
                body = params.get("body", {})
                if isinstance(body, dict):
                    body["api_key"] = api_key
                elif isinstance(body, str) and body.startswith("={{"):
                    # Expression-based body - wrap with api_key injection
                    # Parse the existing expression and add api_key
                    params["body"] = f"={{{{ Object.assign({{ api_key: '{api_key}' }}, {body[3:-2].strip()}) }}}}"
                else:
                    body = {"api_key": api_key}
                params["body"] = body
                
                # Ensure proper content type
                params["sendBody"] = True
                params["bodyContentType"] = "json"
                
                # Remove headerAuth if set (Apollo doesn't use header auth)
                if params.get("authentication") == "headerAuth":
                    params["authentication"] = "none"
                
                logger.info(
                    "configured_apollo_api",
                    node_name=node.get("name"),
                    url=url,
                )
        
        # Phantombuster - needs X-Phantombuster-Key header
        elif "api.phantombuster.com" in url:
            api_key = settings.phantombuster_api_key
            if api_key:
                params["sendHeaders"] = True
                params.setdefault("headerParameters", {})
                params["headerParameters"] = {
                    "parameters": [
                        {"name": "X-Phantombuster-Key", "value": api_key}
                    ]
                }
                params["authentication"] = "none"
                
                logger.info(
                    "configured_phantombuster_api",
                    node_name=node.get("name"),
                )
        
        # Clearbit - uses Bearer token in Authorization header
        elif "clearbit.com" in url:
            api_key = settings.clearbit_api_key
            if api_key:
                params["sendHeaders"] = True
                params.setdefault("headerParameters", {})
                params["headerParameters"] = {
                    "parameters": [
                        {"name": "Authorization", "value": f"Bearer {api_key}"}
                    ]
                }
                params["authentication"] = "none"
                
                logger.info(
                    "configured_clearbit_api",
                    node_name=node.get("name"),
                )
        
        # Instantly - needs api_key in query params
        elif "api.instantly.ai" in url:
            api_key = settings.instantly_api_key
            if api_key:
                params["sendQuery"] = True
                params.setdefault("queryParameters", {})
                params["queryParameters"] = {
                    "parameters": [
                        {"name": "api_key", "value": api_key}
                    ]
                }
                params["authentication"] = "none"
        
        return {
            **node,
            "parameters": params,
        }
    
    def _route_api_through_perseus(self, node: dict) -> dict:
        """Route external API calls through Perseus agent-runner for logging.
        
        This converts direct Apollo/Phantombuster/Perplexity calls to agent-runner calls.
        All executions are logged to the queries table.
        """
        # Only process httpRequest nodes
        if node.get("type") != "n8n-nodes-base.httpRequest":
            return node
        
        params = node.get("parameters", {})
        url = params.get("url", "")
        node_name = node.get("name", "")
        
        settings = get_settings()
        agent_runner_url = settings.agent_runner_url or "https://YOUR_AGENT_RUNNER_URL"
        
        # Determine agent type based on URL
        agent_name = None
        if "api.apollo.io" in url:
            if "/people/search" in url or "/mixed_people" in url:
                agent_name = "apollo_search_people"
            elif "/people/match" in url or "/people/enrich" in url:
                agent_name = "apollo_enrich_person"
            elif "/organizations/enrich" in url:
                agent_name = "apollo_enrich_company"
        elif "api.phantombuster.com" in url:
            if "/launch" in url:
                agent_name = "phantombuster_launch"
            elif "/fetch-output" in url:
                agent_name = "phantombuster_fetch_output"
        elif "api.perplexity.ai" in url:
            agent_name = "perplexity_search"
        
        # If we identified an agent, route through Perseus
        if agent_name:
            logger.info(
                "routing_api_through_perseus",
                node_name=node_name,
                agent_name=agent_name,
                original_url=url,
            )
            
            # Get node_id from node properties
            node_id = node.get("id", node_name.replace(" ", "_").lower())
            
            # Build Perseus agent call with n8n workflow ID
            json_body = f"""={{{{ JSON.stringify({{
  "agent_name": "{agent_name}",
  "input": $json,
  "n8n_workflow_id": $workflow.id,
  "node_id": "{node_id}"
}}) }}}}"""
            
            params = {
                "method": "POST",
                "url": f"{agent_runner_url}/api/agent/run",
                "authentication": "none",
                "sendBody": True,
                "specifyBody": "string",
                "body": json_body,
                "contentType": "raw",
                "rawContentType": "application/json",
                "options": {
                    "timeout": 120000,
                },
            }
            
            return {
                **node,
                "parameters": params,
            }
        
        # Not a recognized API, return as-is
        return node
    
    def _build_switch_rules(self, conditions: list[dict]) -> dict:
        """Build n8n switch rules from branch conditions."""
        
        rules = {"rules": []}

        if not conditions:
            # Provide a minimal valid rule to avoid invalid node params
            conditions = [
                {
                    "field": "branch_key",
                    "value": "default",
                    "operation": "equals",
                    "output": "output0",
                }
            ]

        for i, condition in enumerate(conditions):
            field = condition.get("field", "category")
            left_value = self._build_left_value(field)
            rule = {
                "outputKey": condition.get("output", f"output{i}"),
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "loose",
                    },
                    "conditions": [
                        {
                            "leftValue": left_value,
                            "rightValue": condition.get("value", ""),
                            "operator": {
                                "type": "string",
                                "operation": condition.get("operation", "equals"),
                            },
                        },
                    ],
                    "combinator": "and",
                },
            }
            rules["rules"].append(rule)
        
        # Add fallback/default output
        rules["fallbackOutput"] = "extra"
        
        return rules

    def _build_left_value(self, field: str) -> str:
        """Ensure switch rules reference $json correctly."""
        if not field:
            return "={{ $json.category }}"
        if isinstance(field, str) and field.strip().startswith("={{"):
            return field
        if isinstance(field, str) and field.strip().startswith("={"):
            # Normalize malformed expression syntax
            cleaned = field.strip()
            inner = cleaned[2:-1].strip() if cleaned.endswith("}") else cleaned[2:].strip()
            return f"={{ {inner} }}"
        safe_field = field.strip()
        if safe_field.isidentifier():
            return f"={{{{ $json.{safe_field} }}}}"
        return f"={{{{ $json[\"{safe_field}\"] }}}}"
    
    def _build_if_conditions(self, condition: dict) -> dict:
        """Build n8n IF conditions from a single condition."""
        
        return {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "loose",
            },
            "conditions": [
                {
                    "id": str(uuid4())[:8],
                    "leftValue": condition.get("field", ""),
                    "rightValue": condition.get("value", ""),
                    "operator": {
                        "type": "string",
                        "operation": condition.get("operation", "equals"),
                    },
                },
            ],
            "combinator": "and",
        }
    
    def _compile_connections(self, ir: WorkflowIR) -> dict:
        """Compile edges to n8n connections format.
        
        n8n connections format:
        {
            "Node Name": {
                "main": [
                    [{"node": "Target Node", "type": "main", "index": 0}],  # output 0
                    [{"node": "Target Node 2", "type": "main", "index": 0}],  # output 1
                ]
            }
        }
        """
        connections: dict[str, dict[str, list]] = {}
        
        # Group edges by source
        edges_by_source: dict[str, list[EdgeSpec]] = {}
        for edge in ir.edges:
            if edge.source_id not in edges_by_source:
                edges_by_source[edge.source_id] = []
            edges_by_source[edge.source_id].append(edge)
        
        # Build connections for each source node
        for source_id, edges in edges_by_source.items():
            source_step = ir.get_step_by_id(source_id)
            if not source_step:
                continue
            
            source_name = source_step.name
            
            # Group edges by output index
            outputs_by_index: dict[int, list[dict]] = {}
            
            for edge in edges:
                target_step = ir.get_step_by_id(edge.target_id)
                if not target_step:
                    continue
                if edge.source_id == edge.target_id:
                    logger.warning(
                        "dropping_self_loop_edge",
                        step_id=edge.source_id,
                        edge_id=edge.id,
                    )
                    continue
                
                # Determine output index from condition or source_output
                output_index = 0
                if edge.condition:
                    # Map condition to output index for switch nodes
                    if source_step.type == StepType.BRANCH:
                        output_index = self._get_branch_output_index(
                            source_step,
                            edge.condition,
                        )
                elif edge.source_output != "main":
                    # Parse output index from source_output name
                    try:
                        output_index = int(edge.source_output.replace("output", ""))
                    except ValueError:
                        output_index = 0
                
                if output_index not in outputs_by_index:
                    outputs_by_index[output_index] = []
                
                outputs_by_index[output_index].append({
                    "node": target_step.name,
                    "type": edge.target_input,
                    "index": 0,  # Input index on target node
                })
            
            # Build main outputs array
            max_output = max(outputs_by_index.keys()) if outputs_by_index else 0
            main_outputs = []
            for i in range(max_output + 1):
                main_outputs.append(outputs_by_index.get(i, []))
            
            connections[source_name] = {"main": main_outputs}
        
        return connections
    
    def _get_branch_output_index(
        self,
        step: StepSpec,
        condition: str,
    ) -> int:
        """Map a branch condition name to output index."""
        
        if not step.branch_conditions:
            return 0
        
        for i, branch_cond in enumerate(step.branch_conditions):
            if branch_cond.get("output") == condition:
                return i
            if branch_cond.get("name") == condition:
                return i
            if branch_cond.get("value") == condition:
                return i
        
        return 0
    
    def validate_compiled(self, compiled: dict) -> list[str]:
        """Validate compiled workflow JSON.
        
        Returns list of validation errors (empty if valid).
        """
        detailed = self.validate_compiled_detailed(compiled)
        return [e["message"] for e in detailed if e.get("severity") == "error"]

    def validate_compiled_detailed(self, compiled: dict) -> list[dict]:
        """Validate compiled workflow JSON and return structured errors."""
        errors: list[dict] = []

        def add_error(
            message: str,
            node_name: Optional[str] = None,
            node_type: Optional[str] = None,
            path: Optional[str] = None,
            severity: str = "error",
            code: Optional[str] = None,
        ) -> None:
            errors.append(
                {
                    "message": message,
                    "node_name": node_name,
                    "node_type": node_type,
                    "path": path,
                    "severity": severity,
                    "code": code,
                }
            )
        
        # Check required fields
        if "name" not in compiled:
            add_error("Missing workflow name", code="missing_name")
        
        if "nodes" not in compiled:
            add_error("Missing nodes array", code="missing_nodes")
        elif not compiled["nodes"]:
            add_error("Workflow has no nodes", code="empty_nodes")
        
        if "connections" not in compiled:
            add_error("Missing connections object", code="missing_connections")
        
        # Validate each node
        node_names = set()
        for node in compiled.get("nodes", []):
            if "id" not in node:
                add_error(
                    "Node missing id",
                    node_name=node.get("name"),
                    node_type=node.get("type"),
                    code="node_missing_id",
                )
            if "name" not in node:
                add_error(
                    "Node missing name",
                    node_name=node.get("id"),
                    node_type=node.get("type"),
                    code="node_missing_name",
                )
            elif node["name"] in node_names:
                add_error(
                    f"Duplicate node name: {node['name']}",
                    node_name=node["name"],
                    node_type=node.get("type"),
                    code="duplicate_node_name",
                )
            else:
                node_names.add(node["name"])
            if "type" not in node:
                add_error(
                    "Node missing type",
                    node_name=node.get("name"),
                    code="node_missing_type",
                )
            if "position" not in node:
                add_error(
                    "Node missing position",
                    node_name=node.get("name"),
                    node_type=node.get("type"),
                    code="node_missing_position",
                )

            node_type = node.get("type")
            node_name = node.get("name")
            params = node.get("parameters", {})
            node_def = get_node_definition(node_type) if node_type else None

            # Required params check
            if node_def:
                for param in node_def.parameters:
                    if param.required and param.name not in params:
                        add_error(
                            f"Missing required parameter '{param.name}'",
                            node_name=node_name,
                            node_type=node_type,
                            path=f"parameters.{param.name}",
                            code="missing_required_param",
                        )

            # Switch rules must exist
            if node_type == "n8n-nodes-base.switch":
                rules = params.get("rules")
                if not rules or not isinstance(rules, dict) or not rules.get("rules"):
                    add_error(
                        "Switch node has no rules",
                        node_name=node_name,
                        node_type=node_type,
                        path="parameters.rules",
                        code="switch_missing_rules",
                    )
                if node_def and node.get("typeVersion", 0) < node_def.type_version:
                    add_error(
                        "Switch node typeVersion is outdated",
                        node_name=node_name,
                        node_type=node_type,
                        path="typeVersion",
                        code="switch_version_mismatch",
                    )

            # Merge params vs version
            if node_type == "n8n-nodes-base.merge":
                if "combinationMode" in params and node.get("typeVersion", 0) < 3:
                    add_error(
                        "Merge node uses combinationMode but typeVersion < 3",
                        node_name=node_name,
                        node_type=node_type,
                        path="parameters.combinationMode",
                        code="merge_version_mismatch",
                    )

            # Malformed expressions
            for path in self._find_invalid_expression_paths(params):
                add_error(
                    "Malformed expression syntax",
                    node_name=node_name,
                    node_type=node_type,
                    path=".".join(["parameters"] + path),
                    code="bad_expression",
                )
        
        # Validate connections reference existing nodes
        for source_name, outputs in compiled.get("connections", {}).items():
            if source_name not in node_names:
                add_error(
                    f"Connection source not found: {source_name}",
                    node_name=source_name,
                    code="connection_source_missing",
                )
            
            for output_connections in outputs.get("main", []):
                for conn in output_connections:
                    if conn.get("node") not in node_names:
                        add_error(
                            f"Connection target not found: {conn.get('node')}",
                            node_name=source_name,
                            code="connection_target_missing",
                        )
                    if conn.get("node") == source_name:
                        add_error(
                            "Self-loop connection detected",
                            node_name=source_name,
                            code="self_loop_connection",
                        )
        
        return errors

    def validate_and_fix_compiled(
        self,
        compiled: dict,
        max_attempts: int = 3,
    ) -> tuple[dict, list[dict], bool]:
        current = compiled
        auto_fixed = False

        for _ in range(max_attempts):
            errors = self.validate_compiled_detailed(current)
            if not [e for e in errors if e.get("severity") == "error"]:
                return current, [], auto_fixed
            fixed = self.auto_fix_compiled_json(current)
            if fixed == current:
                return current, errors, auto_fixed
            current = fixed
            auto_fixed = True

        return current, errors, auto_fixed

    def auto_fix_compiled_json(self, compiled: dict) -> dict:
        fixed = copy.deepcopy(compiled)

        for node in fixed.get("nodes", []):
            node_name = node.get("name", "unknown_node")
            params = node.get("parameters", {})
            node["parameters"] = self._sanitize_parameters(params, path=[node_name])

            node_type = node.get("type")
            node_def = get_node_definition(node_type) if node_type else None

            if node_type == "n8n-nodes-base.switch":
                if node_def:
                    node["typeVersion"] = node_def.type_version
                rules = node["parameters"].get("rules")
                if not rules or not isinstance(rules, dict) or not rules.get("rules"):
                    node["parameters"]["rules"] = self._build_switch_rules([])

            if node_type == "n8n-nodes-base.merge":
                if "combinationMode" in node["parameters"] and node_def:
                    node["typeVersion"] = node_def.type_version

        connections = fixed.get("connections", {})
        for source_name, outputs in connections.items():
            main_outputs = outputs.get("main", [])
            new_outputs = []
            for output in main_outputs:
                filtered = [conn for conn in output if conn.get("node") != source_name]
                if len(filtered) != len(output):
                    logger.warning(
                        "dropping_self_loop_connection",
                        node_name=source_name,
                    )
                new_outputs.append(filtered)
            outputs["main"] = new_outputs

        return fixed

    def _find_invalid_expression_paths(self, params: Any, path: Optional[list[str]] = None) -> list[list[str]]:
        if path is None:
            path = []
        matches: list[list[str]] = []
        if isinstance(params, dict):
            for key, value in params.items():
                next_path = path + [key]
                if isinstance(value, str) and value.strip().startswith("={") and not value.strip().startswith("={{"):
                    matches.append(next_path)
                matches.extend(self._find_invalid_expression_paths(value, next_path))
        elif isinstance(params, list):
            for idx, item in enumerate(params):
                matches.extend(self._find_invalid_expression_paths(item, path + [f"[{idx}]"]))
        return matches
    
    @staticmethod
    def extract_webhook_path(compiled_workflow: dict) -> Optional[str]:
        """Extract the webhook path from a compiled workflow.
        
        Returns the webhook path if the workflow has a webhook trigger,
        otherwise returns None.
        """
        for node in compiled_workflow.get("nodes", []):
            if node.get("type") == "n8n-nodes-base.webhook":
                params = node.get("parameters", {})
                return params.get("path")
        return None
    
    @staticmethod
    def extract_webhook_method(compiled_workflow: dict) -> str:
        """Extract the HTTP method for the webhook trigger.
        
        Returns "POST" by default.
        """
        for node in compiled_workflow.get("nodes", []):
            if node.get("type") == "n8n-nodes-base.webhook":
                params = node.get("parameters", {})
                return params.get("httpMethod", "POST")
        return "POST"