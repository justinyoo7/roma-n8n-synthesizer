"""Compiler to transform WorkflowIR to n8n workflow JSON.

The compiler handles:
- Converting StepSpec to n8n node format
- Building the connections graph
- Setting appropriate positions for layout
- Handling branching and merging
"""
from typing import Any, Optional
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
from app.n8n.capability_resolver import resolve_tool_id
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

        # Resolve tool_id if capability metadata is present
        if not step.tool_id and step.capability:
            resolved = resolve_tool_id(step.capability, step.integration_hint)
            if resolved:
                step.tool_id = resolved.get("tool_id")
                if not step.integration_hint:
                    step.integration_hint = resolved.get("api_name")
        
        # Determine node type (may be overridden for agent steps)
        node_type = step.n8n_node_type
        type_version = step.n8n_type_version
        
        # Force specific versions for certain node types
        if step.n8n_node_type == "n8n-nodes-base.itemLists":
            type_version = 3  # Use v3 for better split functionality
        
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
        
        # Route HTTP Request steps through agent-runner when tool_id is available
        elif step.n8n_node_type == "n8n-nodes-base.httpRequest" and step.tool_id:
            parameters = self._build_registry_parameters(step)
            node_type = "n8n-nodes-base.httpRequest"
            type_version = 4
            logger.info("routing_http_to_registry", step_name=step.name, tool_id=step.tool_id)
        
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
            if step.branch_conditions:
                params["rules"] = self._build_switch_rules(step.branch_conditions)
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
        
        return params
    
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

        tool_id_value = f"\"{step.tool_id}\"" if step.tool_id else "null"
        capability_value = f"\"{step.capability}\"" if step.capability else "null"
        integration_hint_value = f"\"{step.integration_hint}\"" if step.integration_hint else "null"
        
        # HTTP Request v4 format - using string body with expression
        # Include n8n_workflow_id for tracking - agent runner will look up internal ID
        json_body = f"""={{{{ JSON.stringify({{
  "agent_name": "{agent.name}",
  "tool_id": {tool_id_value},
  "capability": {capability_value},
  "integration_hint": {integration_hint_value},
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

    def _build_registry_parameters(self, step: StepSpec) -> dict:
        """Build HTTP Request parameters for registry-based tool execution."""
        settings = get_settings()
        agent_runner_url = settings.agent_runner_url or "https://YOUR_AGENT_RUNNER_URL"

        tool_id_value = f"\"{step.tool_id}\"" if step.tool_id else "null"
        capability_value = f"\"{step.capability}\"" if step.capability else "null"
        integration_hint_value = f"\"{step.integration_hint}\"" if step.integration_hint else "null"

        task_description = step.description or step.name
        task_description_escaped = task_description.replace('"', '\\"')

        json_body = f"""={{{{ JSON.stringify({{
  "agent_name": "{step.name}",
  "tool_id": {tool_id_value},
  "capability": {capability_value},
  "integration_hint": {integration_hint_value},
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
                "timeout": 120000,
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
        
        for i, condition in enumerate(conditions):
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
                            "leftValue": condition.get("field", "={{ $json.category }}"),
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
        errors = []
        
        # Check required fields
        if "name" not in compiled:
            errors.append("Missing workflow name")
        
        if "nodes" not in compiled:
            errors.append("Missing nodes array")
        elif not compiled["nodes"]:
            errors.append("Workflow has no nodes")
        
        if "connections" not in compiled:
            errors.append("Missing connections object")
        
        # Validate each node
        node_names = set()
        for node in compiled.get("nodes", []):
            if "id" not in node:
                errors.append(f"Node missing id: {node.get('name', 'unknown')}")
            if "name" not in node:
                errors.append(f"Node missing name: {node.get('id', 'unknown')}")
            elif node["name"] in node_names:
                errors.append(f"Duplicate node name: {node['name']}")
            else:
                node_names.add(node["name"])
            if "type" not in node:
                errors.append(f"Node missing type: {node.get('name', 'unknown')}")
            if "position" not in node:
                errors.append(f"Node missing position: {node.get('name', 'unknown')}")
        
        # Validate connections reference existing nodes
        for source_name, outputs in compiled.get("connections", {}).items():
            if source_name not in node_names:
                errors.append(f"Connection source not found: {source_name}")
            
            for output_connections in outputs.get("main", []):
                for conn in output_connections:
                    if conn.get("node") not in node_names:
                        errors.append(
                            f"Connection target not found: {conn.get('node')}"
                        )
        
        return errors
    
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