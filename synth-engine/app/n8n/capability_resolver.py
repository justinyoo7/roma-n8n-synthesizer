"""Capability Resolver - Maps user intents to n8n nodes or HTTP configurations.

This module is the intelligence layer that decides:
1. Whether to use a native n8n node or HTTP Request
2. Which specific node/API to use
3. What parameters and credentials are needed
4. Any limitations or warnings to surface
"""
from typing import Optional
from dataclasses import dataclass, field
import re

from .node_catalog import (
    N8N_NODE_CATALOG,
    INTEGRATION_REGISTRY,
    NodeDefinition,
    IntegrationInfo,
    find_nodes_by_capability,
    get_integration_info,
    get_integration_limitations,
)
from .api_knowledge import (
    API_REGISTRY,
    APIConfig,
    get_api_config,
    get_apis_for_capability,
    build_http_request_node,
    PHANTOMBUSTER_LINKEDIN_PHANTOMS,
)


@dataclass
class ResolvedCapability:
    """Result of capability resolution."""
    
    # What the user wants to do
    intent: str
    
    # Resolution result
    use_native_node: bool
    
    # For native nodes
    node_type: Optional[str] = None
    node_key: Optional[str] = None
    resource: Optional[str] = None
    operation: Optional[str] = None
    
    # For HTTP Request nodes (custom APIs)
    api_name: Optional[str] = None
    api_endpoint: Optional[str] = None
    http_config: Optional[dict] = None
    
    # For agent steps (AI tasks)
    requires_agent: bool = False
    agent_prompt: Optional[str] = None
    
    # Credentials needed
    credential_type: Optional[str] = None
    env_var_needed: Optional[str] = None
    
    # Confidence and alternatives
    confidence: float = 1.0
    alternatives: list["ResolvedCapability"] = field(default_factory=list)
    
    # Warnings and limitations
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


class CapabilityResolver:
    """Resolves user intents to specific n8n node configurations."""
    
    # Intent patterns -> (capability_category, specific_intent)
    # IMPORTANT: These patterns are evaluated in order, so more specific patterns should come first
    INTENT_PATTERNS = {
        # LinkedIn patterns - Order matters! Company page posts first (native support)
        r"(company page|company post).*linkedin|linkedin.*(company page|company post)": ("linkedin", "company_post"),
        r"(post|share).*(company|page).*linkedin|linkedin.*(post|share).*(company|page)": ("linkedin", "company_post"),
        
        # LinkedIn patterns - Personal actions (require Phantombuster)
        r"(message|dm|inmail).*linkedin|linkedin.*(message|dm|inmail)": ("linkedin", "send_message"),
        r"(connect|connection).*linkedin|linkedin.*(connect|connection)": ("linkedin", "send_connection"),
        r"(search|find).*(linkedin|people.*linkedin|linkedin.*people)": ("linkedin", "search_people"),
        r"(scrape|extract).*linkedin|linkedin.*(scrape|extract)": ("linkedin", "scrape_profile"),
        r"(view|visit).*profile.*linkedin|linkedin.*(view|visit).*profile": ("linkedin", "view_profile"),
        
        # CRM patterns
        r"(hubspot|salesforce|pipedrive).*(contact|lead|deal)": ("crm", "manage_record"),
        r"(create|add|update|get).*(contact|lead|deal)": ("crm", "manage_record"),
        r"crm.*(sync|update|create)": ("crm", "manage_record"),
        
        # Communication patterns - SMS/Twilio MUST come before email patterns
        r"(sms|text message|twilio)": ("communication", "send_sms"),
        r"(slack|teams|discord).*(message|notify|send)": ("communication", "send_notification"),
        r"(telegram|bot).*(message|send)": ("communication", "send_telegram"),
        
        # Email patterns - after communication so SMS doesn't match
        r"(cold|outreach|sequence).*(email)": ("email", "cold_email"),
        r"(send|compose|write).*(email)": ("email", "send_email"),  # Only match "email", not "message"
        r"(gmail|outlook).*(send|read|email)": ("email", "email_operation"),
        
        # Enrichment patterns - Specific tools first
        r"(apollo|clearbit|clay|zoominfo)": ("enrichment", "enrichment_api"),
        r"enrich.*(lead|person|company|contact|data)": ("enrichment", "person_enrichment"),
        r"(lookup|find).*(person|people|contact)": ("enrichment", "person_enrichment"),
        r"(lookup|find).*(company|organization|domain)": ("enrichment", "company_enrichment"),
        r"(find|get).*(email|contact info)": ("enrichment", "email_finder"),
        
        # Scheduling patterns
        r"(schedule|calendar|meeting|appointment)": ("scheduling", "manage_calendar"),
        r"(calendly|cal\.com)": ("scheduling", "scheduling_tool"),
        
        # Database patterns
        r"(postgres|mysql|mongodb|database).*(query|insert|update)": ("database", "database_operation"),
        r"(airtable|google sheets|spreadsheet)": ("database", "spreadsheet_operation"),
        
        # AI/Analysis patterns - These should be checked for AI/ML tasks
        r"(analyze|sentiment|classify|summarize|generate|personalize|tailor|write|draft|create).*(message|content|text|email|outreach)": ("ai", "ai_task"),
        r"(analyze|sentiment|classify|summarize)": ("ai", "ai_task"),
        r"(gpt|claude|openai|anthropic|llm|ai)": ("ai", "ai_task"),
        
        # Research patterns - Use Perplexity
        r"(perplexity)": ("research", "perplexity_search"),
        r"(research|investigate).*(company|person|lead|prospect|market)": ("research", "company_research"),
        r"(web search|search the web|look up|find information about)": ("research", "web_search"),
        r"(current|latest|recent).*(news|info|information)": ("research", "web_search"),
    }
    
    # Capability to native node mapping
    CAPABILITY_TO_NODE = {
        # CRM
        ("crm", "hubspot"): "hubspot",
        ("crm", "salesforce"): "salesforce",
        ("crm", "pipedrive"): "pipedrive",
        
        # Email
        ("email", "gmail"): "gmail",
        ("email", "outlook"): "outlook",
        ("email", "sendgrid"): "sendgrid",
        ("email", "mailchimp"): "mailchimp",
        
        # Communication
        ("communication", "slack"): "slack",
        ("communication", "discord"): "discord",
        ("communication", "telegram"): "telegram",
        ("communication", "twilio"): "twilio",
        ("communication", "teams"): "teams",
        
        # Database
        ("database", "postgres"): "postgres",
        ("database", "mysql"): "mysql",
        ("database", "mongodb"): "mongodb",
        ("database", "airtable"): "airtable",
        ("database", "google_sheets"): "google_sheets",
        ("database", "supabase"): "supabase",
        
        # Enrichment
        ("enrichment", "clearbit"): "clearbit",
        ("enrichment", "hunter"): "hunter",
        
        # Scheduling
        ("scheduling", "calendly"): "calendly",
        ("scheduling", "cal_com"): "cal_com",
        ("scheduling", "google_calendar"): "google_calendar",
        
        # Social
        ("social", "linkedin_company"): "linkedin",
        ("social", "twitter"): "twitter",
        ("social", "facebook"): "facebook",
    }
    
    # Capabilities that REQUIRE HTTP Request (no native node)
    REQUIRES_HTTP = {
        "linkedin_messages",
        "linkedin_connections", 
        "linkedin_search_people",
        "linkedin_scrape",
        "phantombuster",
        "apollo",
        "clay",
        "instantly",
        "lemlist",
        "zoominfo",
        "perplexity",
    }
    
    # Capabilities that require AI agent
    REQUIRES_AGENT = {
        "analyze",
        "sentiment",
        "classify",
        "summarize", 
        "generate_text",
        "ai_reasoning",
        "personalize_message",
        "write_content",
    }
    
    def __init__(self):
        self._build_capability_index()
    
    def _build_capability_index(self):
        """Build index of capabilities to nodes."""
        self.capability_index = {}
        
        for key, node in N8N_NODE_CATALOG.items():
            for cap in node.capabilities:
                if cap not in self.capability_index:
                    self.capability_index[cap] = []
                self.capability_index[cap].append(key)
    
    def resolve(self, intent: str, context: Optional[dict] = None) -> ResolvedCapability:
        """
        Resolve a user intent to a specific capability.
        
        Args:
            intent: Natural language description of what user wants to do
            context: Optional context (e.g., mentioned tools, credentials)
            
        Returns:
            ResolvedCapability with node/API configuration
        """
        intent_lower = intent.lower()
        context = context or {}
        
        # Step 1: Parse the intent
        category, specific_intent = self._parse_intent(intent_lower)
        
        # Step 2: Check for explicit tool mentions
        explicit_tool = self._detect_explicit_tool(intent_lower)
        
        # Step 3: Resolve based on category
        if explicit_tool:
            return self._resolve_explicit_tool(intent, explicit_tool, context)
        
        if category == "linkedin":
            return self._resolve_linkedin(intent, specific_intent, context)
        
        if category == "enrichment":
            return self._resolve_enrichment(intent, specific_intent, context)
        
        if category == "email":
            return self._resolve_email(intent, specific_intent, context)
        
        if category == "ai":
            return self._resolve_ai_task(intent, specific_intent, context)
        
        if category == "crm":
            return self._resolve_crm(intent, specific_intent, context)
        
        if category == "communication":
            return self._resolve_communication(intent, specific_intent, context)
        
        if category == "scheduling":
            return self._resolve_scheduling(intent, specific_intent, context)
        
        if category == "database":
            return self._resolve_database(intent, specific_intent, context)
        
        if category == "research":
            return self._resolve_research(intent, specific_intent, context)
        
        # Default: Try to find any matching node
        return self._resolve_general(intent, context)
    
    def _parse_intent(self, intent: str) -> tuple[str, str]:
        """Parse intent into category and specific action."""
        for pattern, (category, specific) in self.INTENT_PATTERNS.items():
            if re.search(pattern, intent, re.IGNORECASE):
                return (category, specific)
        
        return ("general", "unknown")
    
    def _detect_explicit_tool(self, intent: str) -> Optional[str]:
        """Detect if user explicitly mentioned a tool."""
        tool_keywords = {
            "phantombuster": "phantombuster",
            "apollo": "apollo",
            "clearbit": "clearbit",
            "clay": "clay",
            "instantly": "instantly",
            "lemlist": "lemlist",
            "hubspot": "hubspot",
            "salesforce": "salesforce",
            "pipedrive": "pipedrive",
            "gmail": "gmail",
            "outlook": "outlook",
            "slack": "slack",
            "discord": "discord",
            "telegram": "telegram",
            "airtable": "airtable",
            "notion": "notion",
            "perplexity": "perplexity",
        }
        
        for keyword, tool in tool_keywords.items():
            if keyword in intent:
                return tool
        
        return None
    
    def _resolve_explicit_tool(self, intent: str, tool: str, context: dict) -> ResolvedCapability:
        """Resolve when user explicitly mentions a tool."""
        
        # Check if native node exists
        if tool in N8N_NODE_CATALOG:
            node = N8N_NODE_CATALOG[tool]
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type=node.type,
                node_key=tool,
                credential_type=node.credential_type,
                confidence=0.95,
                limitations=node.limitations,
            )
        
        # Check if in integration registry
        if tool in INTEGRATION_REGISTRY:
            info = INTEGRATION_REGISTRY[tool]
            if info.has_native_node:
                node_key = info.native_node_type.split(".")[-1].lower() if info.native_node_type else tool
                if node_key in N8N_NODE_CATALOG:
                    node = N8N_NODE_CATALOG[node_key]
                    return ResolvedCapability(
                        intent=intent,
                        use_native_node=True,
                        node_type=info.native_node_type,
                        node_key=node_key,
                        credential_type=node.credential_type,
                        confidence=0.95,
                        limitations=info.limitations,
                    )
        
        # Check API registry (custom HTTP)
        if tool in API_REGISTRY:
            api = API_REGISTRY[tool]
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name=tool,
                http_config={"base_url": api.base_url},
                env_var_needed=api.env_var_name,
                confidence=0.9,
            )
        
        # Fallback
        return self._resolve_general(intent, context)
    
    def _resolve_linkedin(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve LinkedIn-related intents."""
        
        # Company page posts - use native node
        if specific == "company_post" or "company page" in intent.lower():
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.linkedIn",
                node_key="linkedin",
                resource="post",
                operation="create",
                credential_type="linkedInOAuth2Api",
                confidence=0.95,
                warnings=["This only works for Company Pages, not personal profiles"],
            )
        
        # Personal LinkedIn actions - MUST use Phantombuster
        phantombuster_config = API_REGISTRY.get("phantombuster")
        
        if specific == "send_message":
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="phantombuster",
                api_endpoint="launch_agent",
                http_config=build_http_request_node("phantombuster", "launch_agent"),
                env_var_needed="PHANTOMBUSTER_API_KEY",
                confidence=0.9,
                warnings=[
                    "LinkedIn personal messaging requires Phantombuster",
                    "You need a 'LinkedIn Message Sender' phantom configured",
                    "Requires LinkedIn session cookie (li_at)",
                ],
                limitations=[
                    "n8n's native LinkedIn node cannot send personal messages",
                    "Rate limited by LinkedIn",
                ],
            )
        
        if specific == "send_connection":
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="phantombuster",
                api_endpoint="launch_agent",
                http_config=build_http_request_node("phantombuster", "launch_agent"),
                env_var_needed="PHANTOMBUSTER_API_KEY",
                confidence=0.9,
                warnings=[
                    "LinkedIn connection requests require Phantombuster",
                    "You need a 'LinkedIn Auto Connect' phantom configured",
                ],
            )
        
        if specific == "search_people":
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="phantombuster",
                api_endpoint="launch_agent",
                http_config=build_http_request_node("phantombuster", "launch_agent"),
                env_var_needed="PHANTOMBUSTER_API_KEY",
                confidence=0.85,
                warnings=["Consider Apollo.io for more comprehensive people search"],
                alternatives=[
                    ResolvedCapability(
                        intent=intent,
                        use_native_node=False,
                        api_name="apollo",
                        api_endpoint="search_people",
                        confidence=0.8,
                    )
                ],
            )
        
        if specific == "scrape_profile":
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="phantombuster",
                api_endpoint="launch_agent",
                http_config=build_http_request_node("phantombuster", "launch_agent"),
                env_var_needed="PHANTOMBUSTER_API_KEY",
                confidence=0.9,
            )
        
        # Default LinkedIn -> Phantombuster
        return ResolvedCapability(
            intent=intent,
            use_native_node=False,
            api_name="phantombuster",
            env_var_needed="PHANTOMBUSTER_API_KEY",
            confidence=0.7,
            warnings=["Most personal LinkedIn automation requires Phantombuster"],
        )
    
    def _resolve_enrichment(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve enrichment-related intents."""
        intent_lower = intent.lower()
        
        # Clearbit has native node for basic enrichment
        if "clearbit" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.clearbit",
                node_key="clearbit",
                resource="person" if "person" in intent_lower else "company",
                operation="enrich",
                credential_type="clearbitApi",
                confidence=0.95,
            )
        
        # Apollo for comprehensive lead data
        if "apollo" in intent_lower or specific in ["person_enrichment", "email_finder"]:
            endpoint = "enrich_person" if "person" in intent_lower or "email" in intent_lower else "search_people"
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="apollo",
                api_endpoint=endpoint,
                http_config=build_http_request_node("apollo", endpoint),
                env_var_needed="APOLLO_API_KEY",
                confidence=0.9,
            )
        
        # Clay for AI-powered enrichment
        if "clay" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="clay",
                api_endpoint="enrich_person",
                env_var_needed="CLAY_API_KEY",
                confidence=0.85,
            )
        
        # Default: Use Clearbit native node if available, otherwise Apollo
        if specific == "company_enrichment":
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.clearbit",
                node_key="clearbit",
                resource="company",
                operation="enrich",
                credential_type="clearbitApi",
                confidence=0.85,
                alternatives=[
                    ResolvedCapability(
                        intent=intent,
                        use_native_node=False,
                        api_name="apollo",
                        api_endpoint="enrich_organization",
                        confidence=0.8,
                    )
                ],
            )
        
        # Person enrichment default
        return ResolvedCapability(
            intent=intent,
            use_native_node=False,
            api_name="apollo",
            api_endpoint="enrich_person",
            http_config=build_http_request_node("apollo", "enrich_person"),
            env_var_needed="APOLLO_API_KEY",
            confidence=0.8,
            alternatives=[
                ResolvedCapability(
                    intent=intent,
                    use_native_node=True,
                    node_type="n8n-nodes-base.clearbit",
                    node_key="clearbit",
                    confidence=0.75,
                )
            ],
        )
    
    def _resolve_email(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve email-related intents."""
        intent_lower = intent.lower()
        
        # Cold email platforms
        if specific == "cold_email" or "cold" in intent_lower or "sequence" in intent_lower:
            if "instantly" in intent_lower:
                return ResolvedCapability(
                    intent=intent,
                    use_native_node=False,
                    api_name="instantly",
                    api_endpoint="add_leads",
                    env_var_needed="INSTANTLY_API_KEY",
                    confidence=0.9,
                )
            if "lemlist" in intent_lower:
                return ResolvedCapability(
                    intent=intent,
                    use_native_node=False,
                    api_name="lemlist",
                    api_endpoint="add_lead_to_campaign",
                    env_var_needed="LEMLIST_API_KEY",
                    confidence=0.9,
                )
            # Default cold email to Instantly
            return ResolvedCapability(
                intent=intent,
                use_native_node=False,
                api_name="instantly",
                api_endpoint="add_leads",
                env_var_needed="INSTANTLY_API_KEY",
                confidence=0.75,
                alternatives=[
                    ResolvedCapability(
                        intent=intent,
                        use_native_node=False,
                        api_name="lemlist",
                        confidence=0.7,
                    )
                ],
            )
        
        # Standard email - use native nodes
        if "gmail" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.gmail",
                node_key="gmail",
                resource="message",
                operation="send",
                credential_type="gmailOAuth2",
                confidence=0.95,
            )
        
        if "outlook" in intent_lower or "microsoft" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.microsoftOutlook",
                node_key="outlook",
                resource="message",
                operation="send",
                credential_type="microsoftOutlookOAuth2Api",
                confidence=0.95,
            )
        
        if "sendgrid" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.sendGrid",
                node_key="sendgrid",
                resource="mail",
                operation="send",
                credential_type="sendGridApi",
                confidence=0.95,
            )
        
        # Default to Gmail
        return ResolvedCapability(
            intent=intent,
            use_native_node=True,
            node_type="n8n-nodes-base.gmail",
            node_key="gmail",
            resource="message",
            operation="send",
            credential_type="gmailOAuth2",
            confidence=0.7,
        )
    
    def _resolve_ai_task(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve AI/analysis tasks - always use agent."""
        return ResolvedCapability(
            intent=intent,
            use_native_node=False,
            requires_agent=True,
            agent_prompt=intent,
            confidence=0.9,
            warnings=["AI tasks will be routed through the agent-runner service"],
        )
    
    def _resolve_crm(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve CRM-related intents."""
        intent_lower = intent.lower()
        
        if "hubspot" in intent_lower:
            resource = "contact"
            if "company" in intent_lower or "companies" in intent_lower:
                resource = "company"
            elif "deal" in intent_lower:
                resource = "deal"
            elif "ticket" in intent_lower:
                resource = "ticket"
            
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.hubspot",
                node_key="hubspot",
                resource=resource,
                credential_type="hubspotOAuth2Api",
                confidence=0.95,
            )
        
        if "salesforce" in intent_lower:
            resource = "contact"
            if "account" in intent_lower:
                resource = "account"
            elif "lead" in intent_lower:
                resource = "lead"
            elif "opportunity" in intent_lower:
                resource = "opportunity"
            
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.salesforce",
                node_key="salesforce",
                resource=resource,
                credential_type="salesforceOAuth2Api",
                confidence=0.95,
            )
        
        if "pipedrive" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.pipedrive",
                node_key="pipedrive",
                credential_type="pipedriveApi",
                confidence=0.95,
            )
        
        # Default to HubSpot
        return ResolvedCapability(
            intent=intent,
            use_native_node=True,
            node_type="n8n-nodes-base.hubspot",
            node_key="hubspot",
            credential_type="hubspotOAuth2Api",
            confidence=0.6,
            warnings=["Defaulting to HubSpot - specify CRM if different"],
        )
    
    def _resolve_communication(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve communication intents."""
        intent_lower = intent.lower()
        
        if "slack" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.slack",
                node_key="slack",
                resource="message",
                operation="post",
                credential_type="slackOAuth2Api",
                confidence=0.95,
            )
        
        if "discord" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.discord",
                node_key="discord",
                resource="message",
                operation="send",
                confidence=0.95,
            )
        
        if "telegram" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.telegram",
                node_key="telegram",
                resource="message",
                operation="send",
                credential_type="telegramApi",
                confidence=0.95,
            )
        
        if "twilio" in intent_lower or "sms" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.twilio",
                node_key="twilio",
                resource="sms",
                operation="send",
                credential_type="twilioApi",
                confidence=0.95,
            )
        
        if "teams" in intent_lower or "microsoft teams" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.microsoftTeams",
                node_key="teams",
                credential_type="microsoftTeamsOAuth2Api",
                confidence=0.95,
            )
        
        # Default to Slack
        return ResolvedCapability(
            intent=intent,
            use_native_node=True,
            node_type="n8n-nodes-base.slack",
            node_key="slack",
            credential_type="slackOAuth2Api",
            confidence=0.5,
            warnings=["Defaulting to Slack - specify platform if different"],
        )
    
    def _resolve_scheduling(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve scheduling intents."""
        intent_lower = intent.lower()
        
        if "calendly" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.calendly",
                node_key="calendly",
                credential_type="calendlyApi",
                confidence=0.95,
            )
        
        if "cal.com" in intent_lower or "cal com" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.cal",
                node_key="cal_com",
                credential_type="calApi",
                confidence=0.95,
            )
        
        if "google calendar" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.googleCalendar",
                node_key="google_calendar",
                credential_type="googleCalendarOAuth2Api",
                confidence=0.95,
            )
        
        # Default to Google Calendar
        return ResolvedCapability(
            intent=intent,
            use_native_node=True,
            node_type="n8n-nodes-base.googleCalendar",
            node_key="google_calendar",
            credential_type="googleCalendarOAuth2Api",
            confidence=0.6,
        )
    
    def _resolve_database(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve database intents."""
        intent_lower = intent.lower()
        
        if "postgres" in intent_lower or "postgresql" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.postgres",
                node_key="postgres",
                credential_type="postgres",
                confidence=0.95,
            )
        
        if "mysql" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.mySql",
                node_key="mysql",
                credential_type="mySql",
                confidence=0.95,
            )
        
        if "mongodb" in intent_lower or "mongo" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.mongoDb",
                node_key="mongodb",
                credential_type="mongoDb",
                confidence=0.95,
            )
        
        if "airtable" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.airtable",
                node_key="airtable",
                credential_type="airtableApi",
                confidence=0.95,
            )
        
        if "google sheets" in intent_lower or "spreadsheet" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.googleSheets",
                node_key="google_sheets",
                credential_type="googleSheetsOAuth2Api",
                confidence=0.95,
            )
        
        if "supabase" in intent_lower:
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type="n8n-nodes-base.supabase",
                node_key="supabase",
                credential_type="supabaseApi",
                confidence=0.95,
            )
        
        # Default to Postgres
        return ResolvedCapability(
            intent=intent,
            use_native_node=True,
            node_type="n8n-nodes-base.postgres",
            node_key="postgres",
            credential_type="postgres",
            confidence=0.5,
        )
    
    def _resolve_research(self, intent: str, specific: str, context: dict) -> ResolvedCapability:
        """Resolve research intents - uses Perplexity API."""
        intent_lower = intent.lower()
        
        # Determine the best endpoint based on intent
        endpoint = "chat_completions"  # Default
        if "company" in intent_lower or "business" in intent_lower:
            endpoint = "company_research"
        elif "lead" in intent_lower or "person" in intent_lower or "prospect" in intent_lower:
            endpoint = "lead_research"
        elif "research" in intent_lower:
            endpoint = "research"
        
        # Build HTTP Request configuration for Perplexity
        api_config = get_api_config("perplexity")
        http_config = None
        
        if api_config:
            http_config = build_http_request_node("perplexity", endpoint)
        
        return ResolvedCapability(
            intent=intent,
            use_native_node=False,
            api_name="perplexity",
            api_endpoint=endpoint,
            http_config=http_config,
            env_var_needed="PERPLEXITY_API_KEY",
            confidence=0.9,
            warnings=[
                "Perplexity API requires an API key from https://www.perplexity.ai/settings/api",
                "Results include citations from web sources",
            ],
            limitations=[
                "Rate limited to 50 requests per minute",
                "Best for factual research, not creative generation",
            ],
        )
    
    def _resolve_general(self, intent: str, context: dict) -> ResolvedCapability:
        """General fallback resolution."""
        intent_lower = intent.lower()
        
        # Try to match capabilities
        best_match = None
        best_score = 0
        
        for key, node in N8N_NODE_CATALOG.items():
            score = 0
            for cap in node.capabilities:
                if cap in intent_lower:
                    score += 1
            
            if score > best_score:
                best_score = score
                best_match = key
        
        if best_match and best_score > 0:
            node = N8N_NODE_CATALOG[best_match]
            return ResolvedCapability(
                intent=intent,
                use_native_node=True,
                node_type=node.type,
                node_key=best_match,
                credential_type=node.credential_type,
                confidence=min(0.3 + (best_score * 0.1), 0.7),
            )
        
        # Ultimate fallback - HTTP Request
        return ResolvedCapability(
            intent=intent,
            use_native_node=True,
            node_type="n8n-nodes-base.httpRequest",
            node_key="http_request",
            confidence=0.3,
            warnings=["Could not determine specific integration - using generic HTTP Request"],
        )
    
    def get_resolution_summary(self, resolution: ResolvedCapability) -> str:
        """Generate a human-readable summary of the resolution."""
        lines = [f"Intent: {resolution.intent}"]
        
        if resolution.use_native_node:
            lines.append(f"→ Using native n8n node: {resolution.node_type}")
            if resolution.resource:
                lines.append(f"  Resource: {resolution.resource}")
            if resolution.operation:
                lines.append(f"  Operation: {resolution.operation}")
        elif resolution.requires_agent:
            lines.append("→ Routing to AI agent for processing")
        else:
            lines.append(f"→ Using HTTP Request to {resolution.api_name}")
            if resolution.api_endpoint:
                lines.append(f"  Endpoint: {resolution.api_endpoint}")
        
        if resolution.credential_type:
            lines.append(f"  Credentials: {resolution.credential_type}")
        if resolution.env_var_needed:
            lines.append(f"  Env var needed: {resolution.env_var_needed}")
        
        lines.append(f"  Confidence: {resolution.confidence:.0%}")
        
        if resolution.warnings:
            lines.append("  Warnings:")
            for w in resolution.warnings:
                lines.append(f"    ⚠ {w}")
        
        if resolution.limitations:
            lines.append("  Limitations:")
            for l in resolution.limitations:
                lines.append(f"    • {l}")
        
        return "\n".join(lines)


# Singleton instance
_resolver = None

def get_resolver() -> CapabilityResolver:
    """Get the singleton capability resolver."""
    global _resolver
    if _resolver is None:
        _resolver = CapabilityResolver()
    return _resolver


def resolve_intent(intent: str, context: Optional[dict] = None) -> ResolvedCapability:
    """Convenience function to resolve an intent."""
    return get_resolver().resolve(intent, context)
