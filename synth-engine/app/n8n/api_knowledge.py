"""API Knowledge Base for HTTP Request configurations.

This module provides pre-configured HTTP Request templates for
integrations that don't have native n8n nodes, including:
- Phantombuster (LinkedIn automation)
- Apollo.io (Lead enrichment)
- Clearbit (Person/company data)
- Clay (Data enrichment)
- Instantly (Cold email)
- Lemlist (Email outreach)
"""
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class APIEndpoint:
    """Definition of an API endpoint."""
    
    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str
    description: str
    required_params: list[str] = field(default_factory=list)
    optional_params: list[str] = field(default_factory=list)
    request_body_schema: Optional[dict] = None
    response_schema: Optional[dict] = None
    
    # For n8n expression templates
    n8n_body_template: Optional[dict] = None


@dataclass
class APIConfig:
    """Complete API configuration for HTTP Request nodes."""
    
    name: str
    base_url: str
    description: str
    
    # Authentication
    auth_type: str  # "header", "query", "bearer", "basic"
    auth_header_name: Optional[str] = None
    auth_query_param: Optional[str] = None
    
    # Endpoints
    endpoints: dict[str, APIEndpoint] = field(default_factory=dict)
    
    # Rate limits
    rate_limit_requests_per_minute: Optional[int] = None
    rate_limit_requests_per_day: Optional[int] = None
    
    # Documentation
    docs_url: Optional[str] = None
    
    # Required environment variable
    env_var_name: Optional[str] = None


# =============================================================================
# PHANTOMBUSTER - LinkedIn Automation
# =============================================================================

PHANTOMBUSTER_CONFIG = APIConfig(
    name="Phantombuster",
    base_url="https://api.phantombuster.com/api/v2",
    description="Browser automation for LinkedIn and other platforms",
    auth_type="header",
    auth_header_name="X-Phantombuster-Key",
    docs_url="https://phantombuster.com/docs/api",
    env_var_name="PHANTOMBUSTER_API_KEY",
    rate_limit_requests_per_minute=100,
    endpoints={
        # Agent Management
        "launch_agent": APIEndpoint(
            method="POST",
            path="/agents/launch",
            description="Launch a Phantombuster agent (phantom)",
            required_params=["id"],
            optional_params=["argument", "saveLaunchType"],
            n8n_body_template={
                "id": "={{ $json.phantomId }}",
                "argument": "={{ JSON.stringify($json.argument) }}"
            }
        ),
        "fetch_output": APIEndpoint(
            method="GET",
            path="/agents/fetch-output",
            description="Fetch the output of an agent",
            required_params=["id"],
            optional_params=["mode", "containerId"]
        ),
        "get_agent": APIEndpoint(
            method="GET",
            path="/agents/fetch",
            description="Get agent details",
            required_params=["id"]
        ),
        "abort_agent": APIEndpoint(
            method="POST",
            path="/agents/abort",
            description="Abort a running agent",
            required_params=["id"]
        ),
        
        # Container/Execution Management
        "get_container_output": APIEndpoint(
            method="GET",
            path="/containers/fetch-output",
            description="Fetch output from a specific container run",
            required_params=["id"]
        ),
        "get_container_result": APIEndpoint(
            method="GET",
            path="/containers/fetch-result-object",
            description="Fetch the result object from a container",
            required_params=["id"]
        ),
    }
)

# Common Phantombuster Phantom IDs for LinkedIn
PHANTOMBUSTER_LINKEDIN_PHANTOMS = {
    "linkedin_profile_scraper": {
        "name": "LinkedIn Profile Scraper",
        "description": "Scrape LinkedIn profile data",
        "argument_schema": {
            "sessionCookie": "string (li_at cookie)",
            "profileUrls": "array of LinkedIn profile URLs",
        }
    },
    "linkedin_search_export": {
        "name": "LinkedIn Search Export",
        "description": "Export results from LinkedIn Sales Navigator search",
        "argument_schema": {
            "sessionCookie": "string",
            "searchUrl": "LinkedIn search URL",
            "numberOfProfiles": "number"
        }
    },
    "linkedin_message_sender": {
        "name": "LinkedIn Message Sender",
        "description": "Send personalized messages to LinkedIn connections",
        "argument_schema": {
            "sessionCookie": "string",
            "spreadsheetUrl": "Google Sheets URL with profiles and messages",
            "columnA": "profileUrl column",
            "columnB": "message column"
        }
    },
    "linkedin_auto_connect": {
        "name": "LinkedIn Auto Connect",
        "description": "Send connection requests on LinkedIn",
        "argument_schema": {
            "sessionCookie": "string",
            "spreadsheetUrl": "Google Sheets URL with profiles",
            "message": "Connection request message (optional)"
        }
    },
    "linkedin_network_booster": {
        "name": "LinkedIn Network Booster",
        "description": "Visit profiles to get views back",
        "argument_schema": {
            "sessionCookie": "string",
            "spreadsheetUrl": "Google Sheets URL with profiles"
        }
    },
    "sales_navigator_search_export": {
        "name": "Sales Navigator Search Export",
        "description": "Export leads from Sales Navigator search",
        "argument_schema": {
            "sessionCookie": "string",
            "searchUrl": "Sales Navigator search URL",
            "numberOfProfiles": "number"
        }
    }
}


# =============================================================================
# APOLLO.IO - Lead Enrichment & People Search
# =============================================================================

APOLLO_CONFIG = APIConfig(
    name="Apollo.io",
    base_url="https://api.apollo.io/v1",
    description="Lead enrichment, people search, and contact data platform",
    auth_type="header",
    auth_header_name="Authorization",  # Pass as "Bearer {api_key}" or use api_key in body
    docs_url="https://apolloio.github.io/apollo-api-docs/",
    env_var_name="APOLLO_API_KEY",
    rate_limit_requests_per_minute=100,
    endpoints={
        # People Search
        "search_people": APIEndpoint(
            method="POST",
            path="/mixed_people/search",
            description="Search for people by various criteria",
            optional_params=[
                "person_titles", "person_seniorities", "q_organization_domains",
                "person_locations", "contact_email_status", "page", "per_page"
            ],
            n8n_body_template={
                "api_key": "={{ $credentials.apolloApiKey }}",
                "q_organization_domains": "={{ $json.domains }}",
                "person_titles": "={{ $json.titles }}",
                "person_seniorities": "={{ $json.seniorities }}",
                "page": "={{ $json.page || 1 }}",
                "per_page": "={{ $json.perPage || 25 }}"
            }
        ),
        
        # Person Enrichment
        "enrich_person": APIEndpoint(
            method="POST",
            path="/people/match",
            description="Enrich person data by email or LinkedIn URL",
            optional_params=["email", "linkedin_url", "first_name", "last_name", "organization_name"],
            n8n_body_template={
                "api_key": "={{ $credentials.apolloApiKey }}",
                "email": "={{ $json.email }}",
                "linkedin_url": "={{ $json.linkedinUrl }}"
            }
        ),
        
        # Organization Search
        "search_organizations": APIEndpoint(
            method="POST",
            path="/mixed_companies/search",
            description="Search for companies/organizations",
            optional_params=[
                "organization_locations", "organization_num_employees_ranges",
                "q_organization_keyword_tags", "page", "per_page"
            ],
            n8n_body_template={
                "api_key": "={{ $credentials.apolloApiKey }}",
                "organization_locations": "={{ $json.locations }}",
                "organization_num_employees_ranges": "={{ $json.employeeRanges }}"
            }
        ),
        
        # Organization Enrichment
        "enrich_organization": APIEndpoint(
            method="GET",
            path="/organizations/enrich",
            description="Enrich company data by domain",
            required_params=["domain"],
        ),
        
        # Email Sequences
        "add_to_sequence": APIEndpoint(
            method="POST",
            path="/emailer_campaigns/{id}/add_contact_ids",
            description="Add contacts to an email sequence",
            required_params=["id", "contact_ids"]
        ),
    }
)


# =============================================================================
# CLEARBIT - Person & Company Data Enrichment
# =============================================================================

CLEARBIT_CONFIG = APIConfig(
    name="Clearbit",
    base_url="https://person.clearbit.com/v2",
    description="Real-time person and company data enrichment",
    auth_type="bearer",
    docs_url="https://clearbit.com/docs",
    env_var_name="CLEARBIT_API_KEY",
    endpoints={
        # Person Enrichment
        "enrich_person_by_email": APIEndpoint(
            method="GET",
            path="/people/find",
            description="Look up person by email address",
            required_params=["email"],
            optional_params=["webhook_url", "given_name", "family_name", "company"]
        ),
        
        # Company Enrichment (different base URL)
        "enrich_company_by_domain": APIEndpoint(
            method="GET",
            path="https://company.clearbit.com/v2/companies/find",  # Full URL
            description="Look up company by domain",
            required_params=["domain"]
        ),
        
        # Combined Person + Company
        "enrich_combined": APIEndpoint(
            method="GET",
            path="https://person-stream.clearbit.com/v2/combined/find",
            description="Look up person and their company together",
            required_params=["email"]
        ),
        
        # Prospector (find people at company)
        "prospector_search": APIEndpoint(
            method="GET",
            path="https://prospector.clearbit.com/v1/people/search",
            description="Find people at a company by role",
            required_params=["domain"],
            optional_params=["role", "seniority", "title", "page", "page_size"]
        ),
        
        # Reveal (IP to company)
        "reveal_company": APIEndpoint(
            method="GET",
            path="https://reveal.clearbit.com/v1/companies/find",
            description="Identify company from IP address",
            required_params=["ip"]
        ),
    }
)


# =============================================================================
# CLAY - Data Enrichment Platform
# =============================================================================

CLAY_CONFIG = APIConfig(
    name="Clay",
    base_url="https://api.clay.com/v3",
    description="AI-powered data enrichment and lead generation",
    auth_type="bearer",
    docs_url="https://docs.clay.com/",
    env_var_name="CLAY_API_KEY",
    endpoints={
        "enrich_person": APIEndpoint(
            method="POST",
            path="/people/enrich",
            description="Enrich person data using Clay's AI",
            optional_params=["email", "linkedin_url", "name", "company"]
        ),
        "enrich_company": APIEndpoint(
            method="POST",
            path="/companies/enrich",
            description="Enrich company data",
            optional_params=["domain", "name", "linkedin_url"]
        ),
        "run_table": APIEndpoint(
            method="POST",
            path="/tables/{table_id}/run",
            description="Run enrichment on a Clay table",
            required_params=["table_id"]
        ),
    }
)


# =============================================================================
# INSTANTLY - Cold Email Platform
# =============================================================================

INSTANTLY_CONFIG = APIConfig(
    name="Instantly",
    base_url="https://api.instantly.ai/api/v1",
    description="Cold email automation and warmup",
    auth_type="query",
    auth_query_param="api_key",
    docs_url="https://developer.instantly.ai/",
    env_var_name="INSTANTLY_API_KEY",
    endpoints={
        # Campaign Management
        "list_campaigns": APIEndpoint(
            method="GET",
            path="/campaign/list",
            description="List all email campaigns"
        ),
        "get_campaign": APIEndpoint(
            method="GET",
            path="/campaign/get",
            description="Get campaign details",
            required_params=["campaign_id"]
        ),
        
        # Lead Management
        "add_leads": APIEndpoint(
            method="POST",
            path="/lead/add",
            description="Add leads to a campaign",
            required_params=["campaign_id", "leads"],
            n8n_body_template={
                "api_key": "={{ $credentials.instantlyApiKey }}",
                "campaign_id": "={{ $json.campaignId }}",
                "leads": "={{ $json.leads }}"
            }
        ),
        "get_lead_status": APIEndpoint(
            method="GET",
            path="/lead/get",
            description="Get lead status",
            required_params=["campaign_id", "email"]
        ),
        
        # Analytics
        "get_campaign_analytics": APIEndpoint(
            method="GET",
            path="/analytics/campaign/summary",
            description="Get campaign performance analytics",
            required_params=["campaign_id"]
        ),
    }
)


# =============================================================================
# LEMLIST - Email Outreach
# =============================================================================

LEMLIST_CONFIG = APIConfig(
    name="Lemlist",
    base_url="https://api.lemlist.com/api",
    description="Personalized email outreach automation",
    auth_type="basic",  # Uses API key as password with empty username
    docs_url="https://developer.lemlist.com/",
    env_var_name="LEMLIST_API_KEY",
    endpoints={
        # Campaign Management
        "list_campaigns": APIEndpoint(
            method="GET",
            path="/campaigns",
            description="List all campaigns"
        ),
        
        # Lead Management
        "add_lead_to_campaign": APIEndpoint(
            method="POST",
            path="/campaigns/{campaign_id}/leads/{email}",
            description="Add a lead to a campaign",
            required_params=["campaign_id", "email"],
            optional_params=["firstName", "lastName", "companyName", "phone", "picture", "linkedinUrl"]
        ),
        "get_lead": APIEndpoint(
            method="GET",
            path="/campaigns/{campaign_id}/leads/{email}",
            description="Get lead details from a campaign",
            required_params=["campaign_id", "email"]
        ),
        "delete_lead": APIEndpoint(
            method="DELETE",
            path="/campaigns/{campaign_id}/leads/{email}",
            description="Remove a lead from a campaign",
            required_params=["campaign_id", "email"]
        ),
        
        # Activities
        "get_activities": APIEndpoint(
            method="GET",
            path="/activities",
            description="Get email activities (sent, opened, clicked, etc.)",
            optional_params=["campaignId", "type", "isFirst"]
        ),
    }
)


# =============================================================================
# PERPLEXITY - AI-powered Research and Web Search
# =============================================================================

PERPLEXITY_CONFIG = APIConfig(
    name="Perplexity",
    base_url="https://api.perplexity.ai",
    description="AI-powered search and research assistant with web access",
    auth_type="bearer",
    docs_url="https://docs.perplexity.ai/",
    env_var_name="PERPLEXITY_API_KEY",
    rate_limit_requests_per_minute=50,
    endpoints={
        # Chat Completions (main endpoint)
        "chat_completions": APIEndpoint(
            method="POST",
            path="/chat/completions",
            description="Generate AI-powered research responses with web search",
            required_params=["model", "messages"],
            optional_params=["max_tokens", "temperature", "top_p", "return_citations", "return_images", "search_domain_filter", "search_recency_filter"],
            n8n_body_template={
                "model": "llama-3.1-sonar-large-128k-online",
                "messages": [
                    {
                        "role": "system",
                        "content": "Be precise and concise."
                    },
                    {
                        "role": "user",
                        "content": "={{ $json.query }}"
                    }
                ],
                "max_tokens": 1024,
                "temperature": 0.2,
                "return_citations": True,
                "return_images": False
            },
            response_schema={
                "id": "string",
                "model": "string",
                "object": "chat.completion",
                "created": "number",
                "choices": [
                    {
                        "index": "number",
                        "finish_reason": "string",
                        "message": {
                            "role": "assistant",
                            "content": "string"
                        },
                        "delta": {"role": "string", "content": "string"}
                    }
                ],
                "citations": ["string"]
            }
        ),
        # Research-focused query
        "research": APIEndpoint(
            method="POST",
            path="/chat/completions",
            description="Deep research on a topic with comprehensive citations",
            required_params=["query"],
            n8n_body_template={
                "model": "llama-3.1-sonar-large-128k-online",
                "messages": [
                    {
                        "role": "system", 
                        "content": "You are a thorough research assistant. Provide comprehensive, well-cited information with sources."
                    },
                    {
                        "role": "user",
                        "content": "={{ $json.query }}"
                    }
                ],
                "max_tokens": 2048,
                "temperature": 0.1,
                "return_citations": True
            }
        ),
        # Company research
        "company_research": APIEndpoint(
            method="POST",
            path="/chat/completions",
            description="Research company information for sales/GTM",
            required_params=["company_name"],
            optional_params=["specific_topics"],
            n8n_body_template={
                "model": "llama-3.1-sonar-large-128k-online",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a B2B sales research assistant. Provide key company insights including: company size, funding, recent news, technology stack, key decision makers, and potential pain points."
                    },
                    {
                        "role": "user",
                        "content": "Research the company: {{ $json.company_name }}. Focus on: {{ $json.specific_topics || 'general company overview, recent news, and key business information' }}"
                    }
                ],
                "max_tokens": 2048,
                "temperature": 0.1,
                "return_citations": True,
                "search_recency_filter": "week"
            }
        ),
        # Lead research
        "lead_research": APIEndpoint(
            method="POST",
            path="/chat/completions",
            description="Research a potential lead/prospect for personalized outreach",
            required_params=["person_name", "company"],
            n8n_body_template={
                "model": "llama-3.1-sonar-large-128k-online",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a sales intelligence researcher. Find recent information about this person that could be used for personalized outreach."
                    },
                    {
                        "role": "user",
                        "content": "Research {{ $json.person_name }} who works at {{ $json.company }}. Find their background, recent posts, speaking engagements, or achievements."
                    }
                ],
                "max_tokens": 1024,
                "temperature": 0.1,
                "return_citations": True,
                "search_recency_filter": "month"
            }
        ),
    }
)


# =============================================================================
# ZOOMINFO - Enterprise Lead Data (for reference)
# =============================================================================

ZOOMINFO_CONFIG = APIConfig(
    name="ZoomInfo",
    base_url="https://api.zoominfo.com",
    description="Enterprise B2B contact and company data",
    auth_type="bearer",  # OAuth2 token
    docs_url="https://developer.zoominfo.com/",
    env_var_name="ZOOMINFO_API_KEY",
    endpoints={
        "search_contacts": APIEndpoint(
            method="POST",
            path="/lookup/contact/search",
            description="Search for contacts by criteria"
        ),
        "search_companies": APIEndpoint(
            method="POST",
            path="/lookup/company/search",
            description="Search for companies by criteria"
        ),
        "enrich_contact": APIEndpoint(
            method="POST",
            path="/enrich/contact",
            description="Enrich contact data"
        ),
    }
)


# =============================================================================
# API REGISTRY
# =============================================================================

API_REGISTRY: dict[str, APIConfig] = {
    "phantombuster": PHANTOMBUSTER_CONFIG,
    "apollo": APOLLO_CONFIG,
    "clearbit": CLEARBIT_CONFIG,
    "clay": CLAY_CONFIG,
    "instantly": INSTANTLY_CONFIG,
    "lemlist": LEMLIST_CONFIG,
    "zoominfo": ZOOMINFO_CONFIG,
    "perplexity": PERPLEXITY_CONFIG,
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_api_config(api_name: str) -> Optional[APIConfig]:
    """Get API configuration by name."""
    return API_REGISTRY.get(api_name.lower())


def get_endpoint_config(api_name: str, endpoint_name: str) -> Optional[APIEndpoint]:
    """Get a specific endpoint configuration."""
    config = get_api_config(api_name)
    if config and endpoint_name in config.endpoints:
        return config.endpoints[endpoint_name]
    return None


def build_http_request_node(
    api_name: str, 
    endpoint_name: str,
    api_key_expression: str = "={{ $credentials.apiKey }}"
) -> dict:
    """Build an n8n HTTP Request node configuration for an API endpoint."""
    config = get_api_config(api_name)
    endpoint = get_endpoint_config(api_name, endpoint_name)
    
    if not config or not endpoint:
        return {}
    
    # Build base URL
    url = f"{config.base_url}{endpoint.path}"
    if endpoint.path.startswith("http"):
        url = endpoint.path  # Full URL provided
    
    # Build node parameters
    params = {
        "method": endpoint.method,
        "url": url,
        "sendBody": endpoint.method in ["POST", "PUT", "PATCH"],
    }
    
    # Add authentication
    if config.auth_type == "header":
        params["sendHeaders"] = True
        params["headerParameters"] = {
            "parameters": [{
                "name": config.auth_header_name,
                "value": api_key_expression
            }]
        }
    elif config.auth_type == "bearer":
        params["authentication"] = "genericCredentialType"
        params["genericAuthType"] = "httpHeaderAuth"
    elif config.auth_type == "query":
        params["sendQuery"] = True
        params["queryParameters"] = {
            "parameters": [{
                "name": config.auth_query_param,
                "value": api_key_expression
            }]
        }
    
    # Add body template if available
    if endpoint.n8n_body_template and endpoint.method in ["POST", "PUT", "PATCH"]:
        params["bodyContentType"] = "json"
        params["body"] = endpoint.n8n_body_template
    
    return params


def get_apis_for_capability(capability: str) -> list[str]:
    """Find APIs that can handle a specific capability."""
    result = []
    
    # Map capabilities to APIs
    capability_map = {
        # LinkedIn automation
        "linkedin_messages": ["phantombuster"],
        "linkedin_connections": ["phantombuster"],
        "linkedin_search": ["phantombuster", "apollo"],
        "linkedin_scraping": ["phantombuster"],
        "linkedin_automation": ["phantombuster"],
        
        # Lead enrichment
        "lead_enrichment": ["apollo", "clearbit", "clay", "zoominfo"],
        "person_enrichment": ["apollo", "clearbit", "clay"],
        "company_enrichment": ["apollo", "clearbit", "clay", "zoominfo"],
        "email_finder": ["apollo", "clearbit", "zoominfo"],
        "people_search": ["apollo", "zoominfo"],
        
        # Cold email
        "cold_email": ["instantly", "lemlist"],
        "email_sequences": ["instantly", "lemlist", "apollo"],
        "email_automation": ["instantly", "lemlist"],
        
        # Data enrichment
        "data_enrichment": ["apollo", "clearbit", "clay", "zoominfo"],
        
        # Research and AI
        "research": ["perplexity"],
        "web_search": ["perplexity"],
        "company_research": ["perplexity", "apollo", "clearbit"],
        "lead_research": ["perplexity", "apollo"],
        "ai_search": ["perplexity"],
        "market_research": ["perplexity"],
    }
    
    # Check direct capability match
    if capability.lower() in capability_map:
        result = capability_map[capability.lower()]
    else:
        # Check if capability is a substring of any API's capabilities
        for api_name, config in API_REGISTRY.items():
            if capability.lower() in config.description.lower():
                result.append(api_name)
    
    return result


def get_phantombuster_phantom_info(phantom_type: str) -> Optional[dict]:
    """Get information about a specific Phantombuster phantom for LinkedIn."""
    return PHANTOMBUSTER_LINKEDIN_PHANTOMS.get(phantom_type)
