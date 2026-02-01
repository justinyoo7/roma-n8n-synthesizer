"""Executor - Third stage of ROMA pipeline.

The Executor pool processes individual subtasks and produces artifacts.
Each subtask type has a specialized executor that:
1. Understands the subtask requirements
2. Uses LLM and tools to generate artifacts
3. Returns typed, validated outputs
4. Uses the CapabilityResolver for intelligent node selection
"""
import asyncio
import json
from typing import Callable, Optional

import structlog

from app.llm.adapter import get_llm_adapter
from app.models.task_tree import (
    TaskNode,
    TaskStatus,
    SubtaskType,
    Artifact,
)
from app.n8n.node_catalog import (
    N8N_NODE_CATALOG,
    INTEGRATION_REGISTRY,
    find_trigger_nodes,
    find_branching_nodes,
    find_nodes_by_capability,
)
from app.n8n.capability_resolver import (
    CapabilityResolver,
    ResolvedCapability,
    get_resolver,
    resolve_intent,
)
from app.n8n.api_knowledge import (
    API_REGISTRY,
    get_api_config,
    build_http_request_node,
    PHANTOMBUSTER_LINKEDIN_PHANTOMS,
)

logger = structlog.get_logger()


class ExecutorPool:
    """Pool of specialized executors for different subtask types.
    
    Supports parallel execution of independent subtasks.
    Uses CapabilityResolver for intelligent node selection.
    """
    
    def __init__(self):
        self.llm = get_llm_adapter()
        self.resolver = get_resolver()
        self.executors: dict[SubtaskType, Callable] = {
            SubtaskType.CHOOSE_TRIGGER: self._execute_choose_trigger,
            SubtaskType.DEFINE_AGENTS: self._execute_define_agents,
            SubtaskType.DEFINE_DATA_CONTRACTS: self._execute_define_data_contracts,
            SubtaskType.SELECT_N8N_NODES: self._execute_select_n8n_nodes,
            SubtaskType.DEFINE_ERROR_HANDLING: self._execute_define_error_handling,
            SubtaskType.GENERATE_TESTS: self._execute_generate_tests,
            SubtaskType.DEFINE_LAYOUT: self._execute_define_layout,
        }
    
    async def execute(self, task: TaskNode, context: dict) -> list[Artifact]:
        """Execute a single task and return its artifacts."""
        
        logger.info(
            "executor_start",
            task_id=str(task.id),
            task_type=task.type.value,
        )
        
        executor = self.executors.get(task.type)
        if not executor:
            logger.warning("no_executor", task_type=task.type.value)
            return []
        
        try:
            artifacts = await executor(task, context)
            logger.info(
                "executor_complete",
                task_id=str(task.id),
                artifact_count=len(artifacts),
            )
            return artifacts
        except Exception as e:
            logger.error(
                "executor_error",
                task_id=str(task.id),
                error=str(e),
            )
            raise
    
    async def execute_parallel(
        self,
        tasks: list[TaskNode],
        context: dict,
    ) -> dict[str, list[Artifact]]:
        """Execute multiple tasks in parallel.
        
        Returns a dict mapping task ID to artifacts.
        """
        logger.info("executor_parallel_start", task_count=len(tasks))
        
        async def execute_single(task: TaskNode):
            return str(task.id), await self.execute(task, context)
        
        results = await asyncio.gather(
            *[execute_single(task) for task in tasks],
            return_exceptions=True,
        )
        
        artifacts_by_task = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error("parallel_execution_error", error=str(result))
            else:
                task_id, artifacts = result
                artifacts_by_task[task_id] = artifacts
        
        return artifacts_by_task
    
    def _resolve_step_capability(self, step_description: str) -> ResolvedCapability:
        """Use the capability resolver to determine the best node for a step."""
        return self.resolver.resolve(step_description)
    
    def _build_node_catalog_prompt(self) -> str:
        """Build a comprehensive prompt section describing available nodes."""
        
        # Native nodes by category
        categories = {}
        for key, node_def in N8N_NODE_CATALOG.items():
            cat = node_def.category
            if cat not in categories:
                categories[cat] = []
            limitations = f" (Limitations: {', '.join(node_def.limitations)})" if node_def.limitations else ""
            categories[cat].append(f"  - {key}: {node_def.description}{limitations}")
        
        native_nodes = []
        for cat, nodes in sorted(categories.items()):
            native_nodes.append(f"\n{cat.upper()}:")
            native_nodes.extend(nodes)
        
        # Custom APIs (no native node)
        custom_apis = ["\n\nCUSTOM API INTEGRATIONS (use HTTP Request node):"]
        for name, info in INTEGRATION_REGISTRY.items():
            if not info.has_native_node:
                custom_apis.append(f"  - {name}: {info.description}")
                if info.limitations:
                    custom_apis.append(f"    Limitations: {', '.join(info.limitations)}")
        
        return "\n".join(native_nodes) + "\n".join(custom_apis)
    
    def _build_capability_guidance(self) -> str:
        """Build guidance for the LLM on which nodes/APIs to use."""
        return """
NODE SELECTION GUIDANCE:

1. LINKEDIN AUTOMATION:
   - Company Page posts: Use native "linkedin" node (n8n-nodes-base.linkedIn)
   - Personal messaging: REQUIRES Phantombuster via HTTP Request
   - Connection requests: REQUIRES Phantombuster via HTTP Request
   - Profile scraping: REQUIRES Phantombuster via HTTP Request
   - People search: Use Phantombuster OR Apollo.io via HTTP Request

2. LEAD ENRICHMENT:
   - Person enrichment: Use "clearbit" (native) OR Apollo/Clay via HTTP
   - Company enrichment: Use "clearbit" (native) OR Apollo via HTTP
   - Email finding: Use Apollo.io or Hunter via HTTP

3. COLD EMAIL:
   - Use Instantly or Lemlist via HTTP Request (no native nodes)

4. CRM:
   - HubSpot, Salesforce, Pipedrive: Use native nodes (full support)

5. EMAIL:
   - Gmail, Outlook, SendGrid: Use native nodes
   - Mailchimp: Use native node for marketing campaigns

6. COMMUNICATION:
   - Slack, Discord, Telegram, Teams: Use native nodes

7. AI/ML TASKS:
   - Classification, sentiment, generation: Set step_type: "agent"
   - NEVER configure direct OpenAI/Anthropic API calls

8. DATABASE:
   - Postgres, MySQL, MongoDB, Airtable, Google Sheets: Native nodes
   - Supabase: Native node available
"""
    
    # === Individual Executors ===
    
    async def _execute_choose_trigger(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Choose and configure the workflow trigger."""
        
        prompt = context.get("prompt", "")
        
        response = await self.llm.generate(
            system_prompt="""You are selecting a trigger for an n8n workflow.
Available triggers:
- webhook: Receive HTTP requests (POST, GET, etc.) - best for real-time integrations
- manual: Start manually from n8n UI - best for one-off tasks
- schedule: Run on a schedule (cron/interval) - best for periodic jobs like "every 10 minutes"

Choose the most appropriate trigger based on the workflow description.

Respond with JSON:
{
    "trigger_type": "webhook|manual|schedule",
    "reasoning": "Why this trigger was chosen",
    "config": {
        "httpMethod": "POST",  // for webhook
        "path": "my-webhook",  // for webhook
        "schedule": {          // for schedule triggers
            "mode": "everyX",  // or "cron"
            "value": 10,       // for everyX: amount
            "unit": "minutes"  // for everyX: seconds|minutes|hours
        }
    }
}""",
            user_message=f"Choose a trigger for: {prompt}",
            response_format="json",
        )
        
        return [Artifact(
            type=SubtaskType.CHOOSE_TRIGGER,
            content=response.content,
        )]
    
    async def _execute_define_agents(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Define AI agents needed in the workflow."""
        
        prompt = context.get("prompt", "")
        
        response = await self.llm.generate(
            system_prompt="""You are defining AI agents for a workflow.
Each agent should have:
- A clear role/purpose
- Defined input/output schemas
- List of tools it can use (if any)

Common agent patterns:
- Classifier: Categorize input into predefined categories
- Drafter: Generate text responses
- Analyzer: Extract information from data
- Router: Decide next steps based on context
- Personalizer: Create personalized content based on context

Respond with JSON:
{
    "agents": [
        {
            "name": "agent_name",
            "role": "What this agent does",
            "system_prompt": "System prompt for the agent",
            "input_schema": {
                "type": "object",
                "properties": {...}
            },
            "output_schema": {
                "type": "object", 
                "properties": {...}
            },
            "tools": ["list", "of", "tools"]
        }
    ]
}""",
            user_message=f"Define agents for: {prompt}",
            response_format="json",
        )
        
        return [Artifact(
            type=SubtaskType.DEFINE_AGENTS,
            content=response.content,
        )]
    
    async def _execute_define_data_contracts(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Define data contracts between workflow steps."""
        
        prompt = context.get("prompt", "")
        agents = context.get("agents", [])
        
        response = await self.llm.generate(
            system_prompt="""You are defining data contracts for workflow edges.
Each contract specifies the shape of data flowing between steps.

Consider:
- What data the trigger provides
- What each agent/step needs as input
- What each agent/step produces as output
- How data transforms between steps

Respond with JSON:
{
    "contracts": [
        {
            "name": "contract_name",
            "from_step": "source_step_id",
            "to_step": "target_step_id",
            "schema": {
                "type": "object",
                "properties": {...},
                "required": [...]
            },
            "transform": "Optional transform expression"
        }
    ]
}""",
            user_message=f"""Define data contracts for: {prompt}

Agents defined: {agents}""",
            response_format="json",
        )
        
        return [Artifact(
            type=SubtaskType.DEFINE_DATA_CONTRACTS,
            content=response.content,
        )]
    
    async def _execute_select_n8n_nodes(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Select appropriate n8n nodes for each workflow step.
        
        Uses the CapabilityResolver to provide intelligent recommendations.
        """
        
        prompt = context.get("prompt", "")
        agents = context.get("agents", [])
        
        # Pre-resolve some common intents from the prompt to provide guidance
        pre_resolved = {}
        keywords_to_check = [
            "linkedin message", "linkedin connection", "linkedin search",
            "enrich", "apollo", "clearbit", "phantombuster",
            "cold email", "hubspot", "salesforce", "slack",
            "sentiment", "classify", "analyze", "generate"
        ]
        
        for kw in keywords_to_check:
            if kw.lower() in prompt.lower():
                resolution = self._resolve_step_capability(kw)
                pre_resolved[kw] = {
                    "use_native": resolution.use_native_node,
                    "node_type": resolution.node_type,
                    "api_name": resolution.api_name,
                    "requires_agent": resolution.requires_agent,
                    "warnings": resolution.warnings,
                }
        
        # Build catalog and guidance
        node_catalog = self._build_node_catalog_prompt()
        capability_guidance = self._build_capability_guidance()
        
        pre_resolved_info = ""
        if pre_resolved:
            pre_resolved_info = f"\n\nPRE-RESOLVED CAPABILITIES (use these recommendations):\n{json.dumps(pre_resolved, indent=2)}"
        
        response = await self.llm.generate(
            system_prompt=f"""You are mapping workflow steps to n8n nodes.

{node_catalog}

{capability_guidance}
{pre_resolved_info}

CRITICAL RULES:
1. For AI/ML steps (classification, sentiment, generation, personalization): 
   - Set step_type to "agent"
   - Set n8n_node_type to "n8n-nodes-base.httpRequest" 
   - The system will automatically configure the agent-runner URL
   - DO NOT set parameters for agent steps - leave them empty {{}}

2. For LinkedIn personal automation (messages, connections, profile scraping):
   - Set step_type to "action"
   - Set n8n_node_type to "n8n-nodes-base.httpRequest"
   - Set api_integration to "phantombuster"
   - The system will configure the HTTP request automatically

3. For lead enrichment without native node (Apollo, Clay):
   - Set step_type to "action"
   - Set n8n_node_type to "n8n-nodes-base.httpRequest"
   - Set api_integration to "apollo" or "clay"

4. For native integrations (HubSpot, Slack, Gmail, Clearbit, etc.):
   - Use the native node type directly

5. For branching: use n8n-nodes-base.switch
6. For merging: use n8n-nodes-base.merge
7. For data transformation: use n8n-nodes-base.set
8. For webhooks: use n8n-nodes-base.webhook (trigger) and n8n-nodes-base.respondToWebhook

NEVER configure direct calls to api.openai.com or api.anthropic.com.
All AI functionality must use step_type: "agent".

Respond with JSON:
{{
    "node_selections": [
        {{
            "step_id": "unique_id",
            "step_name": "Human readable name",
            "step_type": "trigger|action|agent|branch|merge|transform",
            "n8n_node_type": "n8n-nodes-base.xxx",
            "n8n_type_version": 1,
            "parameters": {{}},
            "agent_name": "name_for_agent_steps",
            "api_integration": "phantombuster|apollo|clearbit|etc (for HTTP-based integrations)",
            "rationale": "Why this node was chosen",
            "warnings": ["Any limitations or warnings"]
        }}
    ]
}}""",
            user_message=f"""Select n8n nodes for: {prompt}

Agents defined: {agents}

Remember: 
- LinkedIn personal actions (messages, connections, scraping) REQUIRE Phantombuster via HTTP
- AI tasks (sentiment, classification, generation) MUST use step_type: "agent"
- Use native nodes when available (HubSpot, Slack, Gmail, Clearbit, etc.)""",
            response_format="json",
        )
        
        return [Artifact(
            type=SubtaskType.SELECT_N8N_NODES,
            content=response.content,
        )]
    
    async def _execute_define_error_handling(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Define error handling strategy."""
        
        prompt = context.get("prompt", "")
        
        response = await self.llm.generate(
            system_prompt="""You are defining error handling for a workflow.

Consider:
- Which steps might fail and how
- Whether to retry failed steps
- Fallback behavior when retries exhausted
- Whether to continue or abort on error
- Error notification/logging needs

For API integrations (Phantombuster, Apollo, etc.), consider:
- Rate limiting errors
- Authentication failures
- Timeouts for long-running operations

Respond with JSON:
{
    "error_strategy": {
        "default_action": "retry|fallback|abort|continue",
        "retry_config": {
            "max_retries": 3,
            "backoff_ms": 1000,
            "backoff_multiplier": 2.0
        },
        "step_overrides": [
            {
                "step_id": "step to override",
                "action": "specific action for this step",
                "fallback_step_id": "optional fallback"
            }
        ],
        "error_notifications": {
            "enabled": true,
            "channel": "log|webhook|email"
        }
    }
}""",
            user_message=f"Define error handling for: {prompt}",
            response_format="json",
        )
        
        return [Artifact(
            type=SubtaskType.DEFINE_ERROR_HANDLING,
            content=response.content,
        )]
    
    async def _execute_generate_tests(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Generate test cases for the workflow."""
        
        prompt = context.get("prompt", "")
        agents = context.get("agents", [])
        contracts = context.get("contracts", [])
        
        response = await self.llm.generate(
            system_prompt="""You are generating test cases for an n8n workflow.

Create at least 3 tests:
1. Happy path - valid input produces expected output
2. Malformed input - invalid data is handled gracefully
3. Agent/service failure - downstream failures are handled

Each test should have:
- Name and description
- Input payload
- Expected behavior (output contains, branch taken, etc.)
- Invariants to check

Respond with JSON:
{
    "tests": [
        {
            "name": "Test name",
            "description": "What this tests",
            "type": "happy_path|error_handling|edge_case",
            "input": {
                // Input payload for webhook/trigger
            },
            "invariants": [
                {
                    "type": "output_contains|output_matches_schema|branch_taken|no_error",
                    "config": {
                        // Type-specific config
                    }
                }
            ],
            "expected_output": {
                // Expected output structure (partial match OK)
            }
        }
    ]
}""",
            user_message=f"""Generate tests for: {prompt}

Agents: {agents}
Data contracts: {contracts}""",
            response_format="json",
        )
        
        return [Artifact(
            type=SubtaskType.GENERATE_TESTS,
            content=response.content,
        )]
    
    async def _execute_define_layout(
        self,
        task: TaskNode,
        context: dict,
    ) -> list[Artifact]:
        """Define node positions for workflow visualization."""
        
        nodes = context.get("nodes", [])
        edges = context.get("edges", [])
        
        # Use a simple layout algorithm
        # - Trigger at left
        # - Steps flow left to right
        # - Branches spread vertically
        
        positions = {}
        x_offset = 0
        y_center = 300
        
        # Simple left-to-right layout
        # In production, use a proper graph layout algorithm
        for i, node in enumerate(nodes):
            step_id = node.get("step_id", f"node_{i}")
            positions[step_id] = {
                "x": x_offset,
                "y": y_center,
            }
            x_offset += 300
        
        return [Artifact(
            type=SubtaskType.DEFINE_LAYOUT,
            content={"positions": positions},
        )]
