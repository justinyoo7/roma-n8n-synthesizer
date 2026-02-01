"""Comprehensive catalog of n8n nodes and their configurations.

This catalog provides the synthesis engine with knowledge about:
- Available n8n nodes and their capabilities
- Native integrations vs. custom HTTP implementations needed
- Parameter requirements and authentication types
- Known limitations for each integration
"""
from typing import Optional
from dataclasses import dataclass, field

from pydantic import BaseModel


class NodeParameter(BaseModel):
    """Definition of a node parameter."""
    
    name: str
    type: str  # string, number, boolean, options, json
    required: bool = False
    default: Optional[str] = None
    description: str = ""
    options: Optional[list[str]] = None  # For options type


class NodeDefinition(BaseModel):
    """Definition of an n8n node type."""
    
    type: str  # Full n8n type string
    type_version: int
    name: str  # Human-readable name
    description: str
    capabilities: list[str]
    parameters: list[NodeParameter] = []  # Default to empty list
    
    # Input/output configuration
    inputs: list[str] = ["main"]
    outputs: list[str] = ["main"]
    
    # Categorization
    category: str = "general"
    subcategory: Optional[str] = None
    
    # Authentication
    requires_auth: bool = False
    auth_type: Optional[str] = None  # "oauth2", "apiKey", "basic", etc.
    credential_type: Optional[str] = None  # n8n credential type name
    
    # Limitations
    limitations: list[str] = []
    
    # Operations available (resource -> operations)
    operations: dict[str, list[str]] = {}


@dataclass
class IntegrationInfo:
    """Complete information about an integration (native or custom)."""
    
    name: str
    description: str
    capabilities: list[str]
    has_native_node: bool
    native_node_type: Optional[str] = None
    
    # For native nodes
    operations: dict[str, list[str]] = field(default_factory=dict)
    requires_auth: bool = False
    auth_type: str = "none"
    
    # For custom HTTP implementations
    api_base_url: Optional[str] = None
    api_docs_url: Optional[str] = None
    
    # Limitations and warnings
    limitations: list[str] = field(default_factory=list)
    
    # Category for organization
    category: str = "general"


# =============================================================================
# COMPREHENSIVE NODE CATALOG - Native n8n Integrations
# =============================================================================

N8N_NODE_CATALOG: dict[str, NodeDefinition] = {
    # =========================================================================
    # TRIGGERS
    # =========================================================================
    "webhook": NodeDefinition(
        type="n8n-nodes-base.webhook",
        type_version=2,
        name="Webhook",
        description="Receive HTTP requests and start workflow",
        capabilities=["trigger", "http_input", "webhook"],
        category="trigger",
        parameters=[
            NodeParameter(name="httpMethod", type="options", required=True, 
                         options=["GET", "POST", "PUT", "DELETE", "PATCH"], default="POST"),
            NodeParameter(name="path", type="string", required=True, default="webhook"),
            NodeParameter(name="responseMode", type="options", 
                         options=["onReceived", "lastNode", "responseNode"], default="responseNode"),
        ],
    ),
    
    "manual_trigger": NodeDefinition(
        type="n8n-nodes-base.manualTrigger",
        type_version=1,
        name="Manual Trigger",
        description="Manually start the workflow",
        capabilities=["trigger", "manual"],
        category="trigger",
        parameters=[],
    ),
    
    "schedule_trigger": NodeDefinition(
        type="n8n-nodes-base.scheduleTrigger",
        type_version=1,
        name="Schedule Trigger",
        description="Trigger workflow on a schedule (cron or interval)",
        capabilities=["trigger", "schedule", "cron", "interval", "recurring"],
        category="trigger",
        parameters=[
            NodeParameter(name="rule", type="json", required=True, 
                         description="Cron expression or interval configuration"),
        ],
    ),
    
    "email_trigger_imap": NodeDefinition(
        type="n8n-nodes-base.emailReadImap",
        type_version=2,
        name="Email Trigger (IMAP)",
        description="Trigger when new email arrives",
        capabilities=["trigger", "email", "imap"],
        category="trigger",
        requires_auth=True,
        auth_type="imap",
        parameters=[],
    ),

    # =========================================================================
    # HTTP & API
    # =========================================================================
    "http_request": NodeDefinition(
        type="n8n-nodes-base.httpRequest",
        type_version=4,
        name="HTTP Request",
        description="Make HTTP requests to any API",
        capabilities=["api_call", "http", "rest", "custom_api", "universal"],
        category="http",
        parameters=[
            NodeParameter(name="method", type="options", required=True,
                         options=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                         default="GET"),
            NodeParameter(name="url", type="string", required=True),
            NodeParameter(name="authentication", type="options",
                         options=["none", "genericCredentialType", "predefinedCredentialType"],
                         default="none"),
            NodeParameter(name="sendBody", type="boolean", default="false"),
            NodeParameter(name="bodyContentType", type="options",
                         options=["json", "form-urlencoded", "multipart-form-data", "raw"],
                         default="json"),
        ],
    ),
    
    "respond_to_webhook": NodeDefinition(
        type="n8n-nodes-base.respondToWebhook",
        type_version=1,
        name="Respond to Webhook",
        description="Send response back to webhook caller",
        capabilities=["http_response", "webhook_response"],
        category="http",
        parameters=[
            NodeParameter(name="respondWith", type="options",
                         options=["allIncomingItems", "firstIncomingItem", "json", "noData", "text"],
                         default="json"),
            NodeParameter(name="responseBody", type="json"),
        ],
    ),

    # =========================================================================
    # CRM - Native Integrations
    # =========================================================================
    "hubspot": NodeDefinition(
        type="n8n-nodes-base.hubspot",
        type_version=2,
        name="HubSpot",
        description="HubSpot CRM - contacts, companies, deals, tickets",
        capabilities=["crm", "contacts", "companies", "deals", "tickets", "hubspot", 
                     "lead_management", "sales", "marketing"],
        category="crm",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="hubspotOAuth2Api",
        operations={
            "contact": ["create", "get", "getAll", "update", "delete", "search"],
            "company": ["create", "get", "getAll", "update", "delete", "search"],
            "deal": ["create", "get", "getAll", "update", "delete", "search"],
            "ticket": ["create", "get", "getAll", "update", "delete"],
            "engagement": ["create", "get", "getAll", "delete"],
        },
        parameters=[
            NodeParameter(name="resource", type="options", required=True,
                         options=["contact", "company", "deal", "ticket", "engagement"]),
            NodeParameter(name="operation", type="options", required=True),
        ],
    ),
    
    "salesforce": NodeDefinition(
        type="n8n-nodes-base.salesforce",
        type_version=1,
        name="Salesforce",
        description="Salesforce CRM - full CRUD operations",
        capabilities=["crm", "contacts", "accounts", "leads", "opportunities", "salesforce",
                     "sales", "enterprise_crm"],
        category="crm",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="salesforceOAuth2Api",
        operations={
            "account": ["create", "get", "getAll", "update", "delete"],
            "contact": ["create", "get", "getAll", "update", "delete"],
            "lead": ["create", "get", "getAll", "update", "delete", "convert"],
            "opportunity": ["create", "get", "getAll", "update", "delete"],
            "task": ["create", "get", "getAll", "update", "delete"],
            "case": ["create", "get", "getAll", "update", "delete"],
        },
        parameters=[
            NodeParameter(name="resource", type="options", required=True,
                         options=["account", "contact", "lead", "opportunity", "task", "case"]),
            NodeParameter(name="operation", type="options", required=True),
        ],
    ),
    
    "pipedrive": NodeDefinition(
        type="n8n-nodes-base.pipedrive",
        type_version=1,
        name="Pipedrive",
        description="Pipedrive CRM - deals, contacts, organizations",
        capabilities=["crm", "deals", "contacts", "organizations", "pipedrive", "sales"],
        category="crm",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="pipedriveApi",
        operations={
            "deal": ["create", "get", "getAll", "update", "delete"],
            "person": ["create", "get", "getAll", "update", "delete"],
            "organization": ["create", "get", "getAll", "update", "delete"],
            "activity": ["create", "get", "getAll", "update", "delete"],
            "note": ["create", "get", "getAll", "update", "delete"],
        },
    ),
    
    "zoho_crm": NodeDefinition(
        type="n8n-nodes-base.zohoCrm",
        type_version=1,
        name="Zoho CRM",
        description="Zoho CRM - leads, contacts, accounts, deals",
        capabilities=["crm", "leads", "contacts", "accounts", "deals", "zoho"],
        category="crm",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="zohoCrmOAuth2Api",
        operations={
            "lead": ["create", "get", "getAll", "update", "delete", "upsert"],
            "contact": ["create", "get", "getAll", "update", "delete", "upsert"],
            "account": ["create", "get", "getAll", "update", "delete", "upsert"],
            "deal": ["create", "get", "getAll", "update", "delete", "upsert"],
        },
    ),

    # =========================================================================
    # EMAIL - Native Integrations
    # =========================================================================
    "gmail": NodeDefinition(
        type="n8n-nodes-base.gmail",
        type_version=2,
        name="Gmail",
        description="Send and receive emails via Gmail",
        capabilities=["email", "gmail", "send_email", "receive_email", "drafts", "labels"],
        category="email",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="gmailOAuth2",
        operations={
            "message": ["send", "get", "getAll", "delete", "reply"],
            "draft": ["create", "get", "getAll", "delete"],
            "label": ["create", "get", "getAll", "delete"],
            "thread": ["get", "getAll", "delete", "reply", "addLabels", "removeLabels"],
        },
        parameters=[
            NodeParameter(name="resource", type="options", required=True,
                         options=["message", "draft", "label", "thread"]),
            NodeParameter(name="operation", type="options", required=True),
        ],
    ),
    
    "outlook": NodeDefinition(
        type="n8n-nodes-base.microsoftOutlook",
        type_version=2,
        name="Microsoft Outlook",
        description="Send and receive emails via Outlook",
        capabilities=["email", "outlook", "microsoft", "send_email", "receive_email", "calendar"],
        category="email",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="microsoftOutlookOAuth2Api",
        operations={
            "message": ["send", "get", "getAll", "delete", "update", "move", "reply"],
            "draft": ["create", "get", "delete", "send", "update"],
            "folder": ["create", "get", "getAll", "delete"],
            "calendar": ["create", "get", "getAll", "delete", "update"],
        },
    ),
    
    "sendgrid": NodeDefinition(
        type="n8n-nodes-base.sendGrid",
        type_version=1,
        name="SendGrid",
        description="Send transactional emails via SendGrid",
        capabilities=["email", "sendgrid", "send_email", "transactional", "marketing_email"],
        category="email",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="sendGridApi",
        operations={
            "mail": ["send"],
            "contact": ["create", "get", "getAll", "delete", "upsert"],
            "list": ["create", "get", "getAll", "delete", "update"],
        },
    ),
    
    "mailchimp": NodeDefinition(
        type="n8n-nodes-base.mailchimp",
        type_version=1,
        name="Mailchimp",
        description="Email marketing automation with Mailchimp",
        capabilities=["email", "mailchimp", "marketing", "newsletter", "campaigns", "subscribers"],
        category="email",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="mailchimpOAuth2Api",
        operations={
            "member": ["create", "get", "getAll", "update", "delete"],
            "campaign": ["create", "get", "getAll", "delete", "send", "replicate"],
            "listGroup": ["getAll"],
        },
    ),

    # =========================================================================
    # LINKEDIN - Native Integration (Limited)
    # =========================================================================
    "linkedin": NodeDefinition(
        type="n8n-nodes-base.linkedIn",
        type_version=1,
        name="LinkedIn",
        description="LinkedIn Company Page operations ONLY",
        capabilities=["linkedin", "social_media", "company_page", "posts"],
        category="social",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="linkedInOAuth2Api",
        operations={
            "post": ["create", "delete"],
        },
        limitations=[
            "ONLY supports Company Page operations",
            "Cannot access personal profiles",
            "Cannot send messages or InMails",
            "Cannot send connection requests",
            "Cannot search for people or connections",
            "Cannot view 1st/2nd degree connections",
            "For personal LinkedIn automation, use Phantombuster via HTTP Request",
        ],
        parameters=[
            NodeParameter(name="resource", type="options", required=True,
                         options=["post"]),
            NodeParameter(name="operation", type="options", required=True,
                         options=["create", "delete"]),
        ],
    ),

    # =========================================================================
    # COMMUNICATION - Native Integrations
    # =========================================================================
    "slack": NodeDefinition(
        type="n8n-nodes-base.slack",
        type_version=2,
        name="Slack",
        description="Send messages, manage channels in Slack",
        capabilities=["communication", "slack", "messaging", "channels", "notifications"],
        category="communication",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="slackOAuth2Api",
        operations={
            "message": ["post", "update", "delete", "getPermalink"],
            "channel": ["create", "get", "getAll", "archive", "close", "history", 
                       "invite", "join", "kick", "leave", "member", "open", "rename", 
                       "replies", "setPurpose", "setTopic", "unarchive"],
            "file": ["get", "getAll", "upload"],
            "reaction": ["add", "get", "remove"],
            "star": ["add", "delete", "getAll"],
            "user": ["get", "getAll", "getPresence", "updateProfile"],
            "userGroup": ["create", "disable", "enable", "getAll", "update"],
        },
        parameters=[
            NodeParameter(name="resource", type="options", required=True,
                         options=["message", "channel", "file", "reaction", "star", "user", "userGroup"]),
            NodeParameter(name="operation", type="options", required=True),
        ],
    ),
    
    "discord": NodeDefinition(
        type="n8n-nodes-base.discord",
        type_version=2,
        name="Discord",
        description="Send messages to Discord channels",
        capabilities=["communication", "discord", "messaging", "webhooks"],
        category="communication",
        requires_auth=True,
        auth_type="webhook",
        operations={
            "message": ["send"],
            "webhook": ["send"],
        },
        parameters=[],
    ),
    
    "telegram": NodeDefinition(
        type="n8n-nodes-base.telegram",
        type_version=1,
        name="Telegram",
        description="Send messages via Telegram Bot",
        capabilities=["communication", "telegram", "messaging", "bot", "notifications"],
        category="communication",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="telegramApi",
        operations={
            "message": ["send", "editMessageText", "deleteMessage", "pinChatMessage", "unpinChatMessage"],
            "chat": ["get", "getAdministrators", "getMember", "setDescription", "setTitle", "leaveChat"],
            "callback": ["answer"],
            "file": ["get", "sendAnimation", "sendAudio", "sendDocument", "sendPhoto", 
                    "sendSticker", "sendVideo", "sendMediaGroup"],
        },
    ),
    
    "twilio": NodeDefinition(
        type="n8n-nodes-base.twilio",
        type_version=1,
        name="Twilio",
        description="Send SMS messages and make calls via Twilio",
        capabilities=["communication", "twilio", "sms", "voice", "phone"],
        category="communication",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="twilioApi",
        operations={
            "sms": ["send"],
            "call": ["make"],
        },
    ),
    
    "teams": NodeDefinition(
        type="n8n-nodes-base.microsoftTeams",
        type_version=2,
        name="Microsoft Teams",
        description="Send messages and manage channels in Teams",
        capabilities=["communication", "teams", "microsoft", "messaging", "channels"],
        category="communication",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="microsoftTeamsOAuth2Api",
        operations={
            "channel": ["create", "get", "getAll", "delete", "update"],
            "channelMessage": ["create", "getAll"],
            "chatMessage": ["create", "get", "getAll"],
            "task": ["create", "get", "getAll", "delete", "update"],
        },
    ),

    # =========================================================================
    # DATABASES - Native Integrations
    # =========================================================================
    "postgres": NodeDefinition(
        type="n8n-nodes-base.postgres",
        type_version=2,
        name="PostgreSQL",
        description="Query PostgreSQL database",
        capabilities=["database", "sql", "postgres", "storage", "query"],
        category="database",
        requires_auth=True,
        auth_type="credentials",
        credential_type="postgres",
        operations={
            "database": ["executeQuery", "insert", "update", "upsert", "delete", "select"],
        },
        parameters=[
            NodeParameter(name="operation", type="options", required=True,
                         options=["executeQuery", "insert", "update", "upsert", "delete", "select"]),
        ],
    ),
    
    "mysql": NodeDefinition(
        type="n8n-nodes-base.mySql",
        type_version=2,
        name="MySQL",
        description="Query MySQL database",
        capabilities=["database", "sql", "mysql", "storage", "query"],
        category="database",
        requires_auth=True,
        auth_type="credentials",
        credential_type="mySql",
        operations={
            "database": ["executeQuery", "insert", "update", "delete", "select"],
        },
    ),
    
    "mongodb": NodeDefinition(
        type="n8n-nodes-base.mongoDb",
        type_version=1,
        name="MongoDB",
        description="Query MongoDB database",
        capabilities=["database", "nosql", "mongodb", "storage", "documents"],
        category="database",
        requires_auth=True,
        auth_type="credentials",
        credential_type="mongoDb",
        operations={
            "collection": ["aggregate", "deleteOne", "deleteMany", "find", "findAndReplace",
                          "findAndUpdate", "findOne", "insertOne", "insertMany", "updateOne", "updateMany"],
        },
    ),
    
    "airtable": NodeDefinition(
        type="n8n-nodes-base.airtable",
        type_version=2,
        name="Airtable",
        description="Manage Airtable bases and records",
        capabilities=["database", "airtable", "spreadsheet", "storage", "no_code"],
        category="database",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="airtableApi",
        operations={
            "record": ["create", "delete", "get", "getAll", "update", "upsert"],
        },
        parameters=[
            NodeParameter(name="operation", type="options", required=True,
                         options=["create", "delete", "get", "getAll", "update", "upsert"]),
            NodeParameter(name="base", type="string", required=True),
            NodeParameter(name="table", type="string", required=True),
        ],
    ),
    
    "google_sheets": NodeDefinition(
        type="n8n-nodes-base.googleSheets",
        type_version=4,
        name="Google Sheets",
        description="Read and write Google Sheets data",
        capabilities=["spreadsheet", "google_sheets", "storage", "data"],
        category="database",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="googleSheetsOAuth2Api",
        operations={
            "sheet": ["append", "clear", "create", "delete", "read", "update", "appendOrUpdate"],
        },
        parameters=[
            NodeParameter(name="operation", type="options", required=True,
                         options=["append", "clear", "create", "delete", "read", "update", "appendOrUpdate"]),
            NodeParameter(name="documentId", type="string", required=True),
            NodeParameter(name="sheetName", type="string", required=True),
        ],
    ),
    
    "supabase": NodeDefinition(
        type="n8n-nodes-base.supabase",
        type_version=1,
        name="Supabase",
        description="Supabase database operations",
        capabilities=["database", "supabase", "postgres", "storage", "realtime"],
        category="database",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="supabaseApi",
        operations={
            "row": ["create", "delete", "get", "getAll", "update", "upsert"],
        },
    ),

    # =========================================================================
    # ENRICHMENT - Native Integrations
    # =========================================================================
    "clearbit": NodeDefinition(
        type="n8n-nodes-base.clearbit",
        type_version=1,
        name="Clearbit",
        description="Person and company data enrichment",
        capabilities=["enrichment", "clearbit", "person_lookup", "company_lookup", "data_enrichment"],
        category="enrichment",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="clearbitApi",
        operations={
            "person": ["enrich"],
            "company": ["enrich", "autocomplete"],
        },
        parameters=[
            NodeParameter(name="resource", type="options", required=True,
                         options=["person", "company"]),
            NodeParameter(name="operation", type="options", required=True),
        ],
    ),
    
    "hunter": NodeDefinition(
        type="n8n-nodes-base.hunter",
        type_version=1,
        name="Hunter",
        description="Find and verify email addresses",
        capabilities=["enrichment", "hunter", "email_finder", "email_verification"],
        category="enrichment",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="hunterApi",
        operations={
            "email": ["find", "verify"],
            "domain": ["search"],
        },
    ),

    # =========================================================================
    # SCHEDULING - Native Integrations
    # =========================================================================
    "calendly": NodeDefinition(
        type="n8n-nodes-base.calendly",
        type_version=1,
        name="Calendly",
        description="Scheduling with Calendly",
        capabilities=["scheduling", "calendly", "appointments", "meetings"],
        category="scheduling",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="calendlyApi",
        operations={
            "event": ["get", "getAll"],
            "invitee": ["get", "getAll"],
        },
    ),
    
    "cal_com": NodeDefinition(
        type="n8n-nodes-base.cal",
        type_version=1,
        name="Cal.com",
        description="Open source scheduling with Cal.com",
        capabilities=["scheduling", "cal_com", "appointments", "meetings", "open_source"],
        category="scheduling",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="calApi",
        operations={
            "availability": ["get", "delete", "set"],
            "booking": ["create", "delete", "get", "getAll", "update"],
            "eventType": ["get", "getAll"],
        },
    ),
    
    "google_calendar": NodeDefinition(
        type="n8n-nodes-base.googleCalendar",
        type_version=1,
        name="Google Calendar",
        description="Manage Google Calendar events",
        capabilities=["scheduling", "google_calendar", "calendar", "events", "meetings"],
        category="scheduling",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="googleCalendarOAuth2Api",
        operations={
            "event": ["create", "delete", "get", "getAll", "update"],
            "calendar": ["get", "getAll"],
        },
    ),

    # =========================================================================
    # FLOW CONTROL
    # =========================================================================
    "switch": NodeDefinition(
        type="n8n-nodes-base.switch",
        type_version=3,
        name="Switch",
        description="Route items based on conditions",
        capabilities=["branching", "routing", "conditional", "flow_control"],
        category="flow",
        outputs=["output0", "output1", "output2", "output3"],
        parameters=[
            NodeParameter(name="mode", type="options", 
                         options=["rules", "expression"], default="rules"),
            NodeParameter(name="rules", type="json", required=True),
        ],
    ),
    
    "if": NodeDefinition(
        type="n8n-nodes-base.if",
        type_version=2,
        name="IF",
        description="Route based on true/false condition",
        capabilities=["branching", "conditional", "flow_control"],
        category="flow",
        outputs=["true", "false"],
        parameters=[
            NodeParameter(name="conditions", type="json", required=True),
        ],
    ),
    
    "merge": NodeDefinition(
        type="n8n-nodes-base.merge",
        type_version=3,
        name="Merge",
        description="Merge multiple inputs into one",
        capabilities=["merge", "combine", "join", "flow_control"],
        category="flow",
        inputs=["main", "main"],
        parameters=[
            NodeParameter(name="mode", type="options",
                         options=["append", "combine", "chooseBranch", "mergeByFields",
                                  "mergeByPosition", "multiplex"],
                         default="append"),
        ],
    ),
    
    "no_op": NodeDefinition(
        type="n8n-nodes-base.noOp",
        type_version=1,
        name="No Operation",
        description="Pass through data unchanged",
        capabilities=["passthrough", "noop", "flow_control"],
        category="flow",
        parameters=[],
    ),
    
    "filter": NodeDefinition(
        type="n8n-nodes-base.filter",
        type_version=2,
        name="Filter",
        description="Filter items based on conditions",
        capabilities=["filter", "conditional", "flow_control"],
        category="flow",
        parameters=[
            NodeParameter(name="conditions", type="json", required=True),
        ],
    ),
    
    "loop_over_items": NodeDefinition(
        type="n8n-nodes-base.splitInBatches",
        type_version=3,
        name="Loop Over Items",
        description="Process items one at a time or in batches",
        capabilities=["loop", "batch", "iterate", "flow_control"],
        category="flow",
        outputs=["main", "done"],
        parameters=[
            NodeParameter(name="batchSize", type="number", default="1"),
        ],
    ),

    # =========================================================================
    # DATA TRANSFORMATION
    # =========================================================================
    "set": NodeDefinition(
        type="n8n-nodes-base.set",
        type_version=3,
        name="Set",
        description="Set or modify field values",
        capabilities=["transform", "set_values", "modify", "data_manipulation"],
        category="transform",
        parameters=[
            NodeParameter(name="mode", type="options",
                         options=["manual", "raw"], default="manual"),
            NodeParameter(name="assignments", type="json"),
        ],
    ),
    
    "code": NodeDefinition(
        type="n8n-nodes-base.code",
        type_version=2,
        name="Code",
        description="Run custom JavaScript/Python code",
        capabilities=["transform", "code", "custom_logic", "javascript", "python"],
        category="transform",
        parameters=[
            NodeParameter(name="language", type="options",
                         options=["javaScript", "python"], default="javaScript"),
            NodeParameter(name="jsCode", type="string"),
        ],
    ),
    
    "item_lists": NodeDefinition(
        type="n8n-nodes-base.itemLists",
        type_version=3,
        name="Item Lists",
        description="Manipulate item lists (sort, limit, split, etc.)",
        capabilities=["transform", "list_operations", "sort", "limit", "split"],
        category="transform",
        parameters=[
            NodeParameter(name="operation", type="options", required=True,
                         options=["concatenate", "limit", "removeDuplicates", "sort", "split", "summarize"]),
        ],
    ),
    
    "aggregate": NodeDefinition(
        type="n8n-nodes-base.aggregate",
        type_version=1,
        name="Aggregate",
        description="Aggregate items into a single item",
        capabilities=["transform", "aggregate", "combine", "data_manipulation"],
        category="transform",
        parameters=[
            NodeParameter(name="aggregate", type="options",
                         options=["aggregateIndividualFields", "aggregateAllItemData"]),
        ],
    ),

    # =========================================================================
    # UTILITIES
    # =========================================================================
    "wait": NodeDefinition(
        type="n8n-nodes-base.wait",
        type_version=1,
        name="Wait",
        description="Wait for a specified time",
        capabilities=["wait", "delay", "timer", "rate_limit"],
        category="utility",
        parameters=[
            NodeParameter(name="resume", type="options",
                         options=["timeInterval", "specificTime", "webhook"], default="timeInterval"),
            NodeParameter(name="amount", type="number", default="1"),
            NodeParameter(name="unit", type="options",
                         options=["seconds", "minutes", "hours", "days"], default="seconds"),
        ],
    ),
    
    "date_time": NodeDefinition(
        type="n8n-nodes-base.dateTime",
        type_version=2,
        name="Date & Time",
        description="Work with dates and times",
        capabilities=["date", "time", "format", "parse", "calculate"],
        category="utility",
        parameters=[
            NodeParameter(name="action", type="options", required=True,
                         options=["calculate", "format", "parse"]),
        ],
    ),
    
    "crypto": NodeDefinition(
        type="n8n-nodes-base.crypto",
        type_version=1,
        name="Crypto",
        description="Hash, encrypt, and sign data",
        capabilities=["crypto", "hash", "encrypt", "sign", "security"],
        category="utility",
        parameters=[
            NodeParameter(name="action", type="options", required=True,
                         options=["hash", "hmac", "sign"]),
        ],
    ),
    
    "html_extract": NodeDefinition(
        type="n8n-nodes-base.html",
        type_version=1,
        name="HTML",
        description="Extract data from HTML",
        capabilities=["html", "scrape", "extract", "parse"],
        category="utility",
        parameters=[
            NodeParameter(name="operation", type="options", required=True,
                         options=["extractHtmlContent", "generateHtmlTemplate"]),
        ],
    ),
    
    "xml": NodeDefinition(
        type="n8n-nodes-base.xml",
        type_version=1,
        name="XML",
        description="Parse and create XML",
        capabilities=["xml", "parse", "convert"],
        category="utility",
        parameters=[
            NodeParameter(name="mode", type="options", required=True,
                         options=["jsonToXml", "xmlToJson"]),
        ],
    ),

    # =========================================================================
    # ERROR HANDLING
    # =========================================================================
    "error_trigger": NodeDefinition(
        type="n8n-nodes-base.errorTrigger",
        type_version=1,
        name="Error Trigger",
        description="Trigger when workflow errors occur",
        capabilities=["trigger", "error_handling", "monitoring"],
        category="error",
        parameters=[],
    ),
    
    "stop_and_error": NodeDefinition(
        type="n8n-nodes-base.stopAndError",
        type_version=1,
        name="Stop And Error",
        description="Stop workflow with an error",
        capabilities=["error", "stop", "abort"],
        category="error",
        parameters=[
            NodeParameter(name="errorType", type="options",
                         options=["errorMessage", "errorObject"], default="errorMessage"),
            NodeParameter(name="errorMessage", type="string", required=True),
        ],
    ),

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    "google_drive": NodeDefinition(
        type="n8n-nodes-base.googleDrive",
        type_version=3,
        name="Google Drive",
        description="Manage files in Google Drive",
        capabilities=["file_storage", "google_drive", "upload", "download", "share"],
        category="file",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="googleDriveOAuth2Api",
        operations={
            "file": ["copy", "create", "delete", "download", "list", "move", "share", "update", "upload"],
            "folder": ["create", "delete", "share"],
            "drive": ["list"],
        },
    ),
    
    "dropbox": NodeDefinition(
        type="n8n-nodes-base.dropbox",
        type_version=1,
        name="Dropbox",
        description="Manage files in Dropbox",
        capabilities=["file_storage", "dropbox", "upload", "download"],
        category="file",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="dropboxOAuth2Api",
        operations={
            "file": ["copy", "delete", "download", "move", "upload"],
            "folder": ["create", "delete", "list"],
            "search": ["query"],
        },
    ),
    
    "aws_s3": NodeDefinition(
        type="n8n-nodes-base.s3",
        type_version=1,
        name="AWS S3",
        description="Manage files in Amazon S3",
        capabilities=["file_storage", "s3", "aws", "upload", "download", "bucket"],
        category="file",
        requires_auth=True,
        auth_type="apiKey",
        credential_type="s3",
        operations={
            "bucket": ["create", "delete", "getAll", "search"],
            "file": ["copy", "delete", "download", "getAll", "upload"],
            "folder": ["create", "delete", "getAll"],
        },
    ),

    # =========================================================================
    # FORMS & SURVEYS
    # =========================================================================
    "typeform": NodeDefinition(
        type="n8n-nodes-base.typeform",
        type_version=1,
        name="Typeform",
        description="Get form submissions from Typeform",
        capabilities=["forms", "typeform", "surveys", "responses"],
        category="forms",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "form": ["get", "getAll"],
            "response": ["get", "getAll", "delete"],
        },
    ),
    
    "google_forms": NodeDefinition(
        type="n8n-nodes-base.googleForms",
        type_version=1,
        name="Google Forms",
        description="Get form responses from Google Forms",
        capabilities=["forms", "google_forms", "surveys", "responses"],
        category="forms",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "response": ["getAll"],
            "form": ["get"],
        },
    ),

    # =========================================================================
    # ANALYTICS
    # =========================================================================
    "google_analytics": NodeDefinition(
        type="n8n-nodes-base.googleAnalytics",
        type_version=2,
        name="Google Analytics",
        description="Get data from Google Analytics",
        capabilities=["analytics", "google_analytics", "reporting", "metrics"],
        category="analytics",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "report": ["get"],
            "userActivity": ["search"],
        },
    ),

    # =========================================================================
    # PROJECT MANAGEMENT
    # =========================================================================
    "notion": NodeDefinition(
        type="n8n-nodes-base.notion",
        type_version=2,
        name="Notion",
        description="Manage Notion databases and pages",
        capabilities=["project_management", "notion", "database", "pages", "notes"],
        category="productivity",
        requires_auth=True,
        auth_type="oauth2",
        credential_type="notionOAuth2Api",
        operations={
            "page": ["create", "get", "search", "archive"],
            "database": ["get", "getAll", "query", "search"],
            "databasePage": ["create", "get", "getAll", "update"],
            "block": ["append", "getAll"],
            "user": ["get", "getAll"],
        },
    ),
    
    "asana": NodeDefinition(
        type="n8n-nodes-base.asana",
        type_version=1,
        name="Asana",
        description="Manage tasks and projects in Asana",
        capabilities=["project_management", "asana", "tasks", "projects"],
        category="productivity",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "task": ["create", "delete", "get", "getAll", "update", "move", "search"],
            "project": ["create", "delete", "get", "getAll", "update"],
            "subtask": ["create", "getAll"],
            "taskComment": ["create", "getAll"],
        },
    ),
    
    "trello": NodeDefinition(
        type="n8n-nodes-base.trello",
        type_version=1,
        name="Trello",
        description="Manage Trello boards, lists, and cards",
        capabilities=["project_management", "trello", "boards", "cards", "kanban"],
        category="productivity",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "board": ["create", "delete", "get", "update"],
            "card": ["create", "delete", "get", "update"],
            "cardComment": ["create", "delete", "getAll", "update"],
            "checklist": ["create", "delete", "deleteCheckItem", "get", "getAll", 
                         "getCheckItem", "createCheckItem", "updateCheckItem"],
            "label": ["create", "delete", "get", "getAll", "update"],
            "list": ["archive", "create", "get", "getAll", "update"],
        },
    ),
    
    "jira": NodeDefinition(
        type="n8n-nodes-base.jira",
        type_version=1,
        name="Jira",
        description="Manage Jira issues and projects",
        capabilities=["project_management", "jira", "issues", "agile", "tickets"],
        category="productivity",
        requires_auth=True,
        auth_type="apiKey",
        operations={
            "issue": ["create", "delete", "get", "getAll", "update", "changelog", "notify", "transitions"],
            "issueAttachment": ["add", "get", "getAll", "remove"],
            "issueComment": ["add", "get", "getAll", "remove", "update"],
            "user": ["create", "delete", "get"],
        },
    ),

    # =========================================================================
    # SOCIAL MEDIA (Other than LinkedIn)
    # =========================================================================
    "twitter": NodeDefinition(
        type="n8n-nodes-base.twitter",
        type_version=2,
        name="Twitter/X",
        description="Post tweets and manage Twitter",
        capabilities=["social_media", "twitter", "tweets", "x"],
        category="social",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "tweet": ["create", "delete", "search", "retweet", "like"],
            "user": ["get", "getFollowers", "getFollowing"],
            "directMessage": ["create"],
        },
    ),
    
    "facebook": NodeDefinition(
        type="n8n-nodes-base.facebookGraphApi",
        type_version=1,
        name="Facebook",
        description="Facebook Graph API for pages and posts",
        capabilities=["social_media", "facebook", "posts", "pages"],
        category="social",
        requires_auth=True,
        auth_type="oauth2",
        operations={
            "page": ["post"],
            "video": ["upload"],
            "graphApi": ["get", "post", "delete"],
        },
    ),
}


# =============================================================================
# INTEGRATION REGISTRY - Native vs Custom
# =============================================================================

INTEGRATION_REGISTRY: dict[str, IntegrationInfo] = {
    # Native integrations that fully support their use cases
    "hubspot": IntegrationInfo(
        name="HubSpot",
        description="Full CRM operations",
        capabilities=["crm", "contacts", "deals", "companies", "marketing"],
        has_native_node=True,
        native_node_type="n8n-nodes-base.hubspot",
        category="crm",
    ),
    "salesforce": IntegrationInfo(
        name="Salesforce",
        description="Enterprise CRM operations",
        capabilities=["crm", "contacts", "leads", "opportunities", "accounts"],
        has_native_node=True,
        native_node_type="n8n-nodes-base.salesforce",
        category="crm",
    ),
    "slack": IntegrationInfo(
        name="Slack",
        description="Team messaging and notifications",
        capabilities=["messaging", "notifications", "channels"],
        has_native_node=True,
        native_node_type="n8n-nodes-base.slack",
        category="communication",
    ),
    "gmail": IntegrationInfo(
        name="Gmail",
        description="Send and receive emails",
        capabilities=["email", "send_email", "receive_email"],
        has_native_node=True,
        native_node_type="n8n-nodes-base.gmail",
        category="email",
    ),
    
    # Integrations with limitations
    "linkedin": IntegrationInfo(
        name="LinkedIn",
        description="LinkedIn Company Page operations only",
        capabilities=["company_page_posts"],
        has_native_node=True,
        native_node_type="n8n-nodes-base.linkedIn",
        limitations=[
            "Only supports Company Page operations",
            "Cannot send personal messages",
            "Cannot manage connections",
            "Cannot search for people",
            "For personal LinkedIn automation, use Phantombuster",
        ],
        category="social",
    ),
    
    # Custom HTTP required (no native node)
    "phantombuster": IntegrationInfo(
        name="Phantombuster",
        description="Browser automation for LinkedIn and other platforms",
        capabilities=["linkedin_automation", "browser_automation", "scraping",
                     "linkedin_messages", "linkedin_connections", "linkedin_search"],
        has_native_node=False,
        api_base_url="https://api.phantombuster.com/api/v2",
        api_docs_url="https://phantombuster.com/docs/api",
        category="automation",
    ),
    "apollo": IntegrationInfo(
        name="Apollo.io",
        description="Lead enrichment and people search",
        capabilities=["lead_enrichment", "people_search", "company_search", 
                     "email_finder", "contact_data"],
        has_native_node=False,
        api_base_url="https://api.apollo.io/v1",
        api_docs_url="https://apolloio.github.io/apollo-api-docs/",
        category="enrichment",
    ),
    "clay": IntegrationInfo(
        name="Clay",
        description="Data enrichment and lead generation platform",
        capabilities=["enrichment", "lead_generation", "data_enrichment", "prospecting"],
        has_native_node=False,
        api_base_url="https://api.clay.com/v1",
        category="enrichment",
    ),
    "instantly": IntegrationInfo(
        name="Instantly",
        description="Cold email automation platform",
        capabilities=["cold_email", "email_sequences", "email_warmup"],
        has_native_node=False,
        api_base_url="https://api.instantly.ai/api/v1",
        category="email",
    ),
    "lemlist": IntegrationInfo(
        name="Lemlist",
        description="Email outreach and automation",
        capabilities=["cold_email", "email_sequences", "personalization"],
        has_native_node=False,
        api_base_url="https://api.lemlist.com/api",
        category="email",
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_node_definition(node_key: str) -> Optional[NodeDefinition]:
    """Get a node definition by its key."""
    return N8N_NODE_CATALOG.get(node_key)


def find_nodes_by_capability(capability: str) -> list[NodeDefinition]:
    """Find all nodes with a specific capability."""
    return [
        node for node in N8N_NODE_CATALOG.values()
        if capability in node.capabilities
    ]


def find_nodes_by_category(category: str) -> list[NodeDefinition]:
    """Find all nodes in a category."""
    return [
        node for node in N8N_NODE_CATALOG.values()
        if node.category == category
    ]


def find_trigger_nodes() -> list[NodeDefinition]:
    """Get all trigger nodes."""
    return find_nodes_by_capability("trigger")


def find_branching_nodes() -> list[NodeDefinition]:
    """Get all branching/routing nodes."""
    return [
        node for node in N8N_NODE_CATALOG.values()
        if "branching" in node.capabilities or "routing" in node.capabilities
    ]


def get_integration_info(integration_name: str) -> Optional[IntegrationInfo]:
    """Get integration info by name."""
    return INTEGRATION_REGISTRY.get(integration_name.lower())


def has_native_node(integration_name: str) -> bool:
    """Check if an integration has a native n8n node."""
    info = get_integration_info(integration_name)
    return info.has_native_node if info else False


def get_integration_limitations(integration_name: str) -> list[str]:
    """Get limitations for an integration."""
    info = get_integration_info(integration_name)
    return info.limitations if info else []


def find_integrations_by_capability(capability: str) -> list[IntegrationInfo]:
    """Find integrations that support a specific capability."""
    return [
        info for info in INTEGRATION_REGISTRY.values()
        if capability in info.capabilities
    ]
