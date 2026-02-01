"""Atomizer - First stage of ROMA pipeline.

The Atomizer analyzes the user's prompt and determines:
1. Whether the request is "atomic" (simple enough for direct synthesis)
2. Or requires recursive decomposition into a task tree

For atomic requests, it produces a draft WorkflowIR directly.
For complex requests, it creates the root of a TaskTree for the Planner.
"""
from typing import Optional

import structlog

from app.llm.adapter import get_llm_adapter
from app.models.workflow_ir import (
    WorkflowIR,
    StepSpec,
    StepType,
    TriggerType,
    EdgeSpec,
    AgentSpec,
    DataContract,
    FieldSchema,
    DataType,
    ErrorStrategy,
    TestInvariant,
    Position,
)
from app.models.task_tree import (
    TaskTree,
    TaskNode,
    SubtaskType,
    Artifact,
)

logger = structlog.get_logger()


# System prompt for complexity assessment
COMPLEXITY_PROMPT = """You are a workflow complexity analyzer. Analyze the user's workflow description and determine if it's:

1. ATOMIC: A simple workflow that can be directly mapped to n8n nodes without complex decomposition.
   Examples:
   - "Send an email when webhook is triggered"
   - "Fetch data from API and save to database"
   - "Transform incoming data and forward to another service"
   - "Classify messages using AI" (simple AI workflows are still atomic)
   - "Analyze sentiment of text" (single AI task = atomic)

2. COMPOSITE: A complex workflow requiring decomposition into subtasks.
   Examples:
   - "Customer support triage with branching based on intent"
   - "Multi-agent process with different handlers for different scenarios"
   - "Workflow with error handling, retries, and fallback paths"
   - "Complex multi-step AI pipeline with multiple agents"
   - "LinkedIn automation with search, filtering, and messaging"

IMPORTANT FLAGS:
- Set has_agents to TRUE if the workflow requires ANY AI/ML capability such as:
  * Text classification or categorization
  * Sentiment analysis
  * Content generation or summarization
  * Entity extraction, Natural language understanding
  * Personalized message generation

- Set requires_custom_api to TRUE if the workflow needs:
  * LinkedIn personal automation (messages, connections, profile scraping) - requires Phantombuster
  * Apollo.io lead enrichment
  * Clay data enrichment
  * Instantly or Lemlist cold email
  * Any tool without a native n8n node

- Set uses_native_integrations to TRUE for:
  * CRM: HubSpot, Salesforce, Pipedrive
  * Email: Gmail, Outlook, SendGrid, Mailchimp
  * Communication: Slack, Discord, Telegram, Teams
  * Database: Postgres, MySQL, Airtable, Google Sheets

Respond with JSON:
{
    "complexity": "atomic" | "composite",
    "reasoning": "Brief explanation of your assessment",
    "key_components": ["list", "of", "identified", "components"],
    "estimated_nodes": <number>,
    "has_branching": true | false,
    "has_agents": true | false,
    "has_error_handling": true | false,
    "requires_custom_api": true | false,
    "uses_native_integrations": true | false,
    "integrations_needed": ["list", "of", "tools/platforms"]
}"""


# System prompt for atomic workflow generation
ATOMIC_GENERATION_PROMPT = """You are an n8n workflow generator with comprehensive knowledge of integrations.

=== NATIVE N8N INTEGRATIONS (use directly) ===
CRM:
- HubSpot (n8n-nodes-base.hubspot) - contacts, companies, deals, tickets
- Salesforce (n8n-nodes-base.salesforce) - full CRM operations
- Pipedrive (n8n-nodes-base.pipedrive) - deals, contacts, organizations

EMAIL:
- Gmail (n8n-nodes-base.gmail) - send/receive emails, drafts, labels
- Outlook (n8n-nodes-base.microsoftOutlook) - send/receive, calendar
- SendGrid (n8n-nodes-base.sendGrid) - transactional emails
- Mailchimp (n8n-nodes-base.mailchimp) - email marketing, campaigns

COMMUNICATION:
- Slack (n8n-nodes-base.slack) - messages, channels
- Discord (n8n-nodes-base.discord) - webhooks, messages
- Telegram (n8n-nodes-base.telegram) - bot messages
- Microsoft Teams (n8n-nodes-base.microsoftTeams) - channels, messages
- Twilio (n8n-nodes-base.twilio) - SMS, voice

DATABASE:
- PostgreSQL (n8n-nodes-base.postgres) - SQL queries
- MySQL (n8n-nodes-base.mySql) - SQL queries
- MongoDB (n8n-nodes-base.mongoDb) - document operations
- Airtable (n8n-nodes-base.airtable) - records
- Google Sheets (n8n-nodes-base.googleSheets) - spreadsheet operations
- Supabase (n8n-nodes-base.supabase) - database operations

ENRICHMENT:
- Clearbit (n8n-nodes-base.clearbit) - person/company enrichment
- Hunter (n8n-nodes-base.hunter) - email finder/verification

LINKEDIN (VERY LIMITED - Company Pages ONLY):
- n8n-nodes-base.linkedIn - ONLY for Company Page posts
- CANNOT send personal messages, connection requests, or view profiles

=== CUSTOM HTTP REQUIRED (no native node) ===
LINKEDIN PERSONAL AUTOMATION (requires Phantombuster):
- Sending LinkedIn messages to connections
- Sending connection requests
- Scraping LinkedIn profiles
- Searching for people on LinkedIn
- Sales Navigator exports

LEAD ENRICHMENT:
- Apollo.io - comprehensive lead data, people search
- Clay - AI-powered data enrichment
- ZoomInfo - enterprise contact data

COLD EMAIL:
- Instantly - cold email sequences
- Lemlist - email outreach automation

=== STEP TYPES ===
- "trigger": Workflow start (webhook, manual, schedule)
- "action": Regular API calls using native nodes or HTTP Request
- "transform": Data transformation using Set node
- "agent": AI-powered steps (classification, sentiment, generation, personalization)

=== CRITICAL RULES ===
1. For ANY AI/ML task, use type: "agent". NEVER call OpenAI/Anthropic APIs directly.

2. For LinkedIn personal automation, use type: "action" with:
   - n8n_type: "n8n-nodes-base.httpRequest"
   - api_integration: "phantombuster"
   - The system will configure the HTTP request to Phantombuster's API

3. For Apollo.io/Clay enrichment, use type: "action" with:
   - n8n_type: "n8n-nodes-base.httpRequest"  
   - api_integration: "apollo" or "clay"

4. KEEP WORKFLOWS SIMPLE - For agent workflows:
   - Trigger → Agent Step → Respond is usually sufficient
   - Agent output returns as JSON with an "output" field
   - DO NOT add unnecessary intermediate steps

5. In Set node parameters, use $json not $('node_id').

Respond with JSON:
{
    "name": "Workflow name",
    "description": "What it does",
    "trigger": {
        "type": "webhook" | "manual" | "schedule",
        "config": {
            "httpMethod": "POST",
            "path": "my-webhook",
            "schedule": {"mode": "everyX", "value": 10, "unit": "minutes"}
        }
    },
    "steps": [
        {
            "id": "unique_id",
            "name": "Step Name",
            "type": "action" | "transform" | "agent",
            "n8n_type": "n8n-nodes-base.xxx",
            "parameters": {},
            "description": "What this step does",
            "api_integration": "phantombuster|apollo|clearbit|etc",
            "agent": {
                "name": "agent_name",
                "role": "What the agent does",
                "system_prompt": "System prompt for AI behavior"
            }
        }
    ],
    "edges": [
        {"from": "trigger", "to": "step_id"}
    ],
    "test_cases": [
        {
            "name": "Happy path",
            "input": {},
            "expected_output_contains": ["key"]
        }
    ]
}

Notes:
- "agent" field is REQUIRED when type is "agent"
- "api_integration" should be set when using HTTP Request for non-native APIs
"""


class Atomizer:
    """Atomizer stage of the ROMA pipeline.
    
    Responsibilities:
    - Assess complexity of user request
    - For atomic requests: generate direct WorkflowIR
    - For composite requests: create initial TaskTree structure
    """
    
    def __init__(self):
        self.llm = get_llm_adapter()
    
    async def analyze(self, prompt: str) -> tuple[bool, dict]:
        """Analyze the prompt and determine complexity.
        
        Returns:
            Tuple of (is_atomic, analysis_result)
        """
        logger.info("atomizer_analyze", prompt_length=len(prompt))
        
        response = await self.llm.generate(
            system_prompt=COMPLEXITY_PROMPT,
            user_message=f"Analyze this workflow description:\n\n{prompt}",
            response_format="json",
            temperature=0.3,  # Lower temperature for more consistent analysis
        )
        
        analysis = response.content
        is_atomic = analysis.get("complexity") == "atomic"
        
        logger.info(
            "atomizer_analysis_complete",
            is_atomic=is_atomic,
            estimated_nodes=analysis.get("estimated_nodes"),
            has_branching=analysis.get("has_branching"),
            has_agents=analysis.get("has_agents"),
            requires_custom_api=analysis.get("requires_custom_api"),
            integrations_needed=analysis.get("integrations_needed"),
        )
        
        return is_atomic, analysis
    
    async def generate_atomic_workflow(self, prompt: str) -> WorkflowIR:
        """Generate a WorkflowIR directly for simple requests."""
        
        logger.info("atomizer_generate_atomic")
        
        response = await self.llm.generate(
            system_prompt=ATOMIC_GENERATION_PROMPT,
            user_message=f"Create a simple n8n workflow for:\n\n{prompt}",
            response_format="json",
            temperature=0.5,
        )
        
        workflow_data = response.content
        
        # Convert LLM output to WorkflowIR
        return self._build_workflow_ir(workflow_data, prompt)
    
    async def create_task_tree(self, prompt: str, analysis: dict) -> TaskTree:
        """Create a TaskTree for complex requests.
        
        The task tree will be further processed by the Planner.
        """
        logger.info("atomizer_create_task_tree")
        
        tree = TaskTree(root_prompt=prompt, is_atomic=False)
        
        # Create initial subtasks based on analysis
        subtasks = []
        
        # Always need to choose a trigger
        trigger_task = TaskNode(
            type=SubtaskType.CHOOSE_TRIGGER,
            name="Choose Trigger",
            description="Determine the workflow trigger type",
            input_data={
                "components": analysis.get("key_components", []),
                "integrations_needed": analysis.get("integrations_needed", []),
            },
        )
        subtasks.append(trigger_task)
        
        # Check if workflow needs agents (explicit flag or inferred from components)
        components = analysis.get("key_components", [])
        needs_agents = analysis.get("has_agents", False)
        
        # Infer agents needed if components mention classifiers, drafters, analyzers, etc.
        agent_keywords = ["classifier", "drafter", "analyzer", "generator", "agent", "ai", "llm",
                        "sentiment", "classify", "personalize", "summarize", "generate"]
        if not needs_agents and components:
            for comp in components:
                if any(kw in comp.lower() for kw in agent_keywords):
                    needs_agents = True
                    break
        
        # If workflow has agents, need to define them
        if needs_agents:
            subtasks.append(TaskNode(
                type=SubtaskType.DEFINE_AGENTS,
                name="Define Agents",
                description="Identify and configure required agents",
                depends_on=[trigger_task.id],
                input_data={"components": components},
            ))
        
        # Need to define data contracts
        subtasks.append(TaskNode(
            type=SubtaskType.DEFINE_DATA_CONTRACTS,
            name="Define Data Contracts",
            description="Define input/output schemas for each step",
            depends_on=[t.id for t in subtasks],
        ))
        
        # Select n8n nodes
        subtasks.append(TaskNode(
            type=SubtaskType.SELECT_N8N_NODES,
            name="Select n8n Nodes",
            description="Map workflow steps to specific n8n nodes",
            depends_on=[subtasks[-1].id],
            input_data={
                "requires_custom_api": analysis.get("requires_custom_api", False),
                "integrations_needed": analysis.get("integrations_needed", []),
            },
        ))
        
        # If workflow has error handling needs
        if analysis.get("has_error_handling"):
            subtasks.append(TaskNode(
                type=SubtaskType.DEFINE_ERROR_HANDLING,
                name="Define Error Handling",
                description="Configure retry and fallback strategies",
                depends_on=[subtasks[-1].id],
            ))
        
        # Always generate tests
        subtasks.append(TaskNode(
            type=SubtaskType.GENERATE_TESTS,
            name="Generate Tests",
            description="Create test cases for the workflow",
            depends_on=[subtasks[-1].id],
        ))
        
        # Define layout
        subtasks.append(TaskNode(
            type=SubtaskType.DEFINE_LAYOUT,
            name="Define Layout",
            description="Determine node positions for visualization",
            depends_on=[subtasks[-1].id],
        ))
        
        tree.tasks = subtasks
        
        logger.info(
            "task_tree_created",
            task_count=len(subtasks),
            task_types=[t.type.value for t in subtasks],
        )
        
        return tree
    
    def _build_workflow_ir(self, data: dict, original_prompt: str) -> WorkflowIR:
        """Build a WorkflowIR from LLM-generated data."""
        
        # Build trigger step
        trigger_data = data.get("trigger", {"type": "webhook"})
        trigger = self._build_trigger(trigger_data)
        
        # Build other steps
        steps = []
        for i, step_data in enumerate(data.get("steps", [])):
            step = self._build_step(step_data, i)
            steps.append(step)
        
        # Ensure webhook workflows have a Respond to Webhook step
        if trigger.trigger_type == TriggerType.WEBHOOK:
            has_respond = any(
                s.n8n_node_type == "n8n-nodes-base.respondToWebhook" 
                for s in steps
            )
            if not has_respond and steps:
                # Add respond step after the last step
                last_step = steps[-1]
                respond_step = StepSpec(
                    id="respond_to_webhook",
                    name="Respond to Webhook",
                    type=StepType.ACTION,
                    description="Send response back to the webhook caller",
                    n8n_node_type="n8n-nodes-base.respondToWebhook",
                    parameters={
                        "respondWith": "json",
                        "responseBody": "={{ $json.output || $json }}",
                    },
                    position=Position(
                        x=last_step.position.x + 250, 
                        y=last_step.position.y
                    ),
                )
                steps.append(respond_step)
                
                # Add edge from last step to respond
                data.setdefault("edges", [])
                data["edges"].append({
                    "from": last_step.id,
                    "to": "respond_to_webhook",
                })
        
        # Build edges
        edges = []
        for edge_data in data.get("edges", []):
            edge = self._build_edge(edge_data, trigger.id, steps)
            if edge:
                edges.append(edge)
        
        # Build test invariants
        success_criteria = []
        for test in data.get("test_cases", []):
            invariant = TestInvariant(
                name=test.get("name", "Test"),
                description=f"Test: {test.get('name', 'unnamed')}",
                type="output_contains" if test.get("expected_output_contains") else "execution_success",
                config=test,
            )
            success_criteria.append(invariant)
        
        return WorkflowIR(
            name=data.get("name", "Generated Workflow"),
            description=data.get("description", original_prompt[:200]),
            trigger=trigger,
            steps=steps,
            edges=edges,
            error_strategy=ErrorStrategy(),
            success_criteria=success_criteria,
            metadata={
                "original_prompt": original_prompt,
                "integrations_used": self._extract_integrations(data),
            },
        )
    
    def _extract_integrations(self, data: dict) -> list[str]:
        """Extract list of integrations used in the workflow."""
        integrations = set()
        for step in data.get("steps", []):
            if step.get("api_integration"):
                integrations.add(step["api_integration"])
            n8n_type = step.get("n8n_type", "")
            if "hubspot" in n8n_type.lower():
                integrations.add("hubspot")
            elif "salesforce" in n8n_type.lower():
                integrations.add("salesforce")
            elif "gmail" in n8n_type.lower():
                integrations.add("gmail")
            elif "slack" in n8n_type.lower():
                integrations.add("slack")
            elif "linkedIn" in n8n_type:
                integrations.add("linkedin")
        return list(integrations)
    
    def _build_trigger(self, trigger_data: dict) -> StepSpec:
        """Build a trigger StepSpec."""
        
        trigger_type_str = trigger_data.get("type", "webhook")
        trigger_type = TriggerType.WEBHOOK
        n8n_type = "n8n-nodes-base.webhook"
        
        if trigger_type_str == "manual":
            trigger_type = TriggerType.MANUAL
            n8n_type = "n8n-nodes-base.manualTrigger"
        elif trigger_type_str == "schedule":
            trigger_type = TriggerType.SCHEDULE
            n8n_type = "n8n-nodes-base.scheduleTrigger"
        
        return StepSpec(
            id="trigger",
            name="Trigger",
            type=StepType.TRIGGER,
            n8n_node_type=n8n_type,
            trigger_type=trigger_type,
            trigger_config=trigger_data.get("config", {}),
            parameters=trigger_data.get("config", {}),
            position=Position(x=0, y=200),
        )
    
    def _build_step(self, step_data: dict, index: int) -> StepSpec:
        """Build a StepSpec from step data."""
        
        step_type = StepType.ACTION
        type_str = step_data.get("type", "action")
        if type_str == "transform":
            step_type = StepType.TRANSFORM
        elif type_str == "agent":
            step_type = StepType.AGENT
        elif type_str == "branch":
            step_type = StepType.BRANCH
        
        # Build agent spec if needed
        agent = None
        if step_type == StepType.AGENT and step_data.get("agent"):
            agent_data = step_data["agent"]
            agent = AgentSpec(
                name=agent_data.get("name", f"agent_{index}"),
                role=agent_data.get("role", "Process data"),
                tools_allowed=agent_data.get("tools", []),
                input_schema=DataContract(
                    name=f"agent_{index}_input",
                    fields=[FieldSchema(name="input", type=DataType.OBJECT)],
                ),
                output_schema=DataContract(
                    name=f"agent_{index}_output",
                    fields=[FieldSchema(name="output", type=DataType.OBJECT)],
                ),
            )
        
        # Store api_integration metadata if present
        metadata = {}
        if step_data.get("api_integration"):
            metadata["api_integration"] = step_data["api_integration"]
        
        return StepSpec(
            id=step_data.get("id", f"step_{index}"),
            name=step_data.get("name", f"Step {index + 1}"),
            type=step_type,
            description=step_data.get("description"),
            n8n_node_type=step_data.get("n8n_type", "n8n-nodes-base.set"),
            parameters=step_data.get("parameters", {}),
            agent=agent,
            position=Position(x=300 + (index * 250), y=200),
            metadata=metadata,
        )
    
    def _build_edge(
        self,
        edge_data: dict,
        trigger_id: str,
        steps: list[StepSpec],
    ) -> Optional[EdgeSpec]:
        """Build an EdgeSpec from edge data."""
        
        from_id = edge_data.get("from", "")
        to_id = edge_data.get("to", "")
        
        # Resolve 'trigger' reference
        if from_id == "trigger":
            from_id = trigger_id
        
        # Find target step
        target_step = None
        for step in steps:
            if step.id == to_id:
                target_step = step
                break
        
        if not target_step:
            return None
        
        return EdgeSpec(
            source_id=from_id,
            target_id=to_id,
            condition=edge_data.get("condition"),
            label=edge_data.get("label"),
        )
