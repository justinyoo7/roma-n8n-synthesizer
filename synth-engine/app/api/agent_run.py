"""Agent Runner API endpoint - executes agent steps within n8n workflows.

This module provides the agent execution endpoint that n8n workflows call.
It includes real API integrations for:
- Apollo.io (lead enrichment, people search)
- Phantombuster (LinkedIn automation)
- Perplexity (AI-powered research)
"""
import re
import asyncio
import json
from typing import Optional, Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm.adapter import get_llm_adapter

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter()


# =============================================================================
# TOOL DEFINITIONS WITH API DOCUMENTATION
# =============================================================================

APOLLO_TOOLS = {
    "apollo_search_people": {
        "description": "Search for people/contacts using Apollo.io. Returns contact information including emails.",
        "endpoint": "https://api.apollo.io/v1/mixed_people/search",
        "method": "POST",
        "parameters": {
            "q_organization_domains": "List of company domains to search (e.g., ['stripe.com'])",
            "person_titles": "List of job titles to filter (e.g., ['CEO', 'CTO', 'VP'])",
            "person_seniorities": "List of seniority levels (e.g., ['owner', 'c_suite', 'vp', 'director'])",
            "per_page": "Results per page (default 25, max 100)",
            "page": "Page number (default 1)",
        },
        "example_response": {
            "people": [
                {
                    "id": "abc123",
                    "first_name": "John",
                    "last_name": "Doe",
                    "title": "CEO",
                    "email": "john@company.com",
                    "linkedin_url": "linkedin.com/in/johndoe",
                    "organization": {"name": "Company Inc", "website": "company.com"}
                }
            ],
            "pagination": {"page": 1, "per_page": 25, "total_entries": 100}
        }
    },
    "apollo_enrich_person": {
        "description": "Enrich a person's data using Apollo.io. Get full profile from email or LinkedIn URL.",
        "endpoint": "https://api.apollo.io/v1/people/match",
        "method": "POST",
        "parameters": {
            "email": "Person's email address",
            "linkedin_url": "Person's LinkedIn profile URL",
            "first_name": "First name (helps with matching)",
            "last_name": "Last name (helps with matching)",
            "organization_name": "Company name (helps with matching)",
        },
        "example_response": {
            "person": {
                "id": "abc123",
                "first_name": "John",
                "last_name": "Doe",
                "title": "CEO",
                "email": "john@company.com",
                "phone_numbers": ["+1-555-0123"],
                "linkedin_url": "linkedin.com/in/johndoe",
                "organization": {
                    "name": "Company Inc",
                    "website": "company.com",
                    "industry": "Technology",
                    "estimated_num_employees": 500
                }
            }
        }
    },
    "apollo_enrich_company": {
        "description": "Enrich company data using Apollo.io. Get company details from domain.",
        "endpoint": "https://api.apollo.io/v1/organizations/enrich",
        "method": "GET",
        "parameters": {
            "domain": "Company website domain (e.g., 'stripe.com')",
        },
        "example_response": {
            "organization": {
                "id": "abc123",
                "name": "Stripe",
                "website_url": "stripe.com",
                "industry": "Financial Technology",
                "estimated_num_employees": 7000,
                "founded_year": 2010,
                "keywords": ["payments", "fintech", "api"],
                "linkedin_url": "linkedin.com/company/stripe"
            }
        }
    }
}

PHANTOMBUSTER_TOOLS = {
    "phantombuster_launch": {
        "description": "Launch a Phantombuster agent/phantom for LinkedIn automation tasks.",
        "endpoint": "https://api.phantombuster.com/api/v2/agents/launch",
        "method": "POST",
        "parameters": {
            "id": "Phantom ID to launch",
            "argument": "JSON object with phantom-specific arguments",
        },
        "phantoms": {
            "linkedin_profile_scraper": "Scrapes LinkedIn profile data",
            "linkedin_search_export": "Exports LinkedIn search results",
            "linkedin_message_sender": "Sends personalized LinkedIn messages",
            "linkedin_auto_connect": "Sends connection requests",
            "sales_navigator_search": "Exports Sales Navigator search results",
        }
    },
    "phantombuster_fetch_output": {
        "description": "Fetch the output/results from a Phantombuster agent run.",
        "endpoint": "https://api.phantombuster.com/api/v2/agents/fetch-output",
        "method": "GET",
        "parameters": {
            "id": "Phantom ID to fetch output from",
        }
    }
}

PERPLEXITY_TOOLS = {
    "perplexity_search": {
        "description": "AI-powered web search using Perplexity. Returns comprehensive research with citations.",
        "endpoint": "https://api.perplexity.ai/chat/completions",
        "method": "POST",
        "parameters": {
            "query": "The research question or topic to search",
            "focus": "Optional focus area: 'company', 'person', 'market', 'news'",
        }
    }
}

# Combine all tools
ALL_TOOLS = {**APOLLO_TOOLS, **PHANTOMBUSTER_TOOLS, **PERPLEXITY_TOOLS}

# Security: Allowed tools
ALLOWED_TOOLS = {
    "apollo_search_people",
    "apollo_enrich_person",
    "apollo_enrich_company",
    "phantombuster_launch",
    "phantombuster_fetch_output",
    "perplexity_search",
    "http_fetch",
    "database_query",
    "json_transform",
}

# Patterns that indicate potential prompt injection
INJECTION_PATTERNS = [
    r"ignore\s+(?:previous|above|all)\s+instructions",
    r"disregard\s+(?:previous|above|all)",
    r"new\s+instructions?:",
    r"system\s*:\s*",
    r"<\/?(?:system|instruction|prompt)>",
]


class AgentRunRequest(BaseModel):
    """Request body for agent execution."""
    
    agent_name: str = Field(..., description="Name of the agent to run")
    input: dict = Field(..., description="Input data for the agent")
    context: Optional[dict] = Field(
        default_factory=dict,
        description="Additional context from workflow execution",
    )
    tools_allowed: list[str] = Field(
        default_factory=list,
        description="List of tools this agent is allowed to use",
    )


class AgentRunResponse(BaseModel):
    """Response body for agent execution."""
    
    output: dict = Field(..., description="Agent output")
    metadata: dict = Field(
        default_factory=dict,
        description="Execution metadata (tokens, duration, etc.)",
    )


def detect_prompt_injection(text: str) -> bool:
    """Check for potential prompt injection attempts."""
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def redact_secrets(data: dict) -> dict:
    """Redact sensitive information from logs."""
    sensitive_keys = {"api_key", "password", "secret", "token", "credential"}
    redacted = {}
    for key, value in data.items():
        if any(s in key.lower() for s in sensitive_keys):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_secrets(value)
        else:
            redacted[key] = value
    return redacted


# =============================================================================
# API EXECUTION FUNCTIONS
# =============================================================================

async def execute_apollo_search_people(params: dict) -> dict:
    """Execute Apollo people search API call."""
    api_key = settings.apollo_api_key
    if not api_key:
        return {"error": "Apollo API key not configured", "data": None}
    
    # Build request body (no api_key in body - it goes in header)
    body = {}
    
    if params.get("domains") or params.get("q_organization_domains"):
        domains = params.get("domains") or params.get("q_organization_domains")
        if isinstance(domains, str):
            domains = [domains]
        body["q_organization_domains"] = domains
    
    if params.get("titles") or params.get("person_titles"):
        titles = params.get("titles") or params.get("person_titles")
        if isinstance(titles, str):
            titles = [titles]
        body["person_titles"] = titles
    
    if params.get("seniorities") or params.get("person_seniorities"):
        seniorities = params.get("seniorities") or params.get("person_seniorities")
        if isinstance(seniorities, str):
            seniorities = [seniorities]
        body["person_seniorities"] = seniorities
    
    # Add keyword search for ICP-based searches
    if params.get("keywords") or params.get("q_keywords"):
        keywords = params.get("keywords") or params.get("q_keywords")
        if isinstance(keywords, list):
            keywords = " ".join(keywords)
        body["q_keywords"] = keywords
    
    # Add industry filters
    if params.get("industries") or params.get("organization_industry_tag_ids"):
        industries = params.get("industries") or params.get("organization_industry_tag_ids")
        if isinstance(industries, str):
            industries = [industries]
        # Apollo uses industry tags, but we can search by keywords instead
        if "q_keywords" in body:
            body["q_keywords"] += " " + " ".join(industries)
        else:
            body["q_keywords"] = " ".join(industries)
    
    # Add location filters
    if params.get("locations") or params.get("person_locations"):
        locations = params.get("locations") or params.get("person_locations")
        if isinstance(locations, str):
            locations = [locations]
        body["person_locations"] = locations
    
    # Request more results to filter down to those with LinkedIn
    requested_count = min(params.get("per_page", 25), 50)
    body["per_page"] = min(requested_count * 3, 100)  # Request 3x to filter down
    body["page"] = params.get("page", 1)
    
    # IMPORTANT: Filter for contacts with LinkedIn URLs
    # This is the key filter to ensure we get actionable data
    if params.get("require_linkedin", True):  # Default to requiring LinkedIn
        body["linkedin_url_exists"] = True
    
    # Request email reveal if available (uses Apollo credits)
    if params.get("reveal_emails", False):
        body["reveal_personal_emails"] = True
    
    # Additional quality filters
    body["include_similar_people"] = False  # Don't pad with similar people
    
    logger.info("apollo_search_people_request", body_keys=list(body.keys()), per_page=body["per_page"], require_linkedin=body.get("linkedin_url_exists"))
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Use the new API search endpoint (api_search)
            response = await client.post(
                "https://api.apollo.io/api/v1/mixed_people/api_search",
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": api_key,
                    "Cache-Control": "no-cache"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                # Extract key information
                all_people = data.get("people", [])
                
                # Filter to only include contacts with LinkedIn URLs
                people_with_linkedin = [
                    p for p in all_people 
                    if p.get("linkedin_url")
                ]
                
                # If we required LinkedIn but got none, also return some without as fallback
                if not people_with_linkedin and all_people:
                    logger.warning("no_linkedin_urls_found", total_people=len(all_people))
                    people_with_linkedin = all_people  # Fallback to all
                
                # Limit to requested count
                people = people_with_linkedin[:requested_count]
                
                # Build contacts with LinkedIn search URLs as fallback
                contacts = []
                for p in people:
                    first_name = p.get('first_name', '')
                    last_name = p.get('last_name', '')
                    full_name = f"{first_name} {last_name}".strip()
                    company = p.get("organization", {}).get("name", "")
                    
                    # Get LinkedIn URL from Apollo or construct search URL
                    linkedin_url = p.get("linkedin_url")
                    linkedin_search_url = None
                    
                    if not linkedin_url and full_name and company:
                        # Construct a LinkedIn search URL as fallback
                        import urllib.parse
                        search_query = f"{full_name} {company}"
                        linkedin_search_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(search_query)}"
                    
                    contacts.append({
                        "name": full_name,
                        "first_name": first_name,
                        "last_name": last_name,
                        "title": p.get("title"),
                        "email": p.get("email"),
                        "phone": p.get("phone_numbers", [None])[0] if p.get("phone_numbers") else None,
                        "linkedin_url": linkedin_url,
                        "linkedin_search_url": linkedin_search_url,  # Fallback search URL
                        "city": p.get("city"),
                        "state": p.get("state"),
                        "country": p.get("country"),
                        "company": company,
                        "company_website": p.get("organization", {}).get("website_url"),
                        "company_linkedin": p.get("organization", {}).get("linkedin_url"),
                        "company_industry": p.get("organization", {}).get("industry"),
                        "company_size": p.get("organization", {}).get("estimated_num_employees"),
                    })
                
                return {
                    "success": True,
                    "total_results": data.get("pagination", {}).get("total_entries", len(all_people)),
                    "contacts_with_linkedin": len([p for p in all_people if p.get("linkedin_url")]),
                    "contacts_with_search_urls": len([c for c in contacts if c.get("linkedin_search_url")]),
                    "api_note": "Apollo API tier may not include direct LinkedIn URLs. LinkedIn search URLs provided as fallback.",
                    "contacts": contacts
                }
            else:
                return {"error": f"Apollo API error: {response.status_code}", "details": response.text[:200]}
    except Exception as e:
        logger.error("apollo_search_error", error=str(e))
        return {"error": f"Apollo API call failed: {str(e)}"}


async def execute_apollo_enrich_person(params: dict) -> dict:
    """Execute Apollo person enrichment API call."""
    api_key = settings.apollo_api_key
    if not api_key:
        return {"error": "Apollo API key not configured", "data": None}
    
    # API key goes in header, not body
    body = {}
    
    if params.get("email"):
        body["email"] = params["email"]
    if params.get("linkedin_url"):
        body["linkedin_url"] = params["linkedin_url"]
    if params.get("first_name"):
        body["first_name"] = params["first_name"]
    if params.get("last_name"):
        body["last_name"] = params["last_name"]
    if params.get("organization_name") or params.get("company"):
        body["organization_name"] = params.get("organization_name") or params.get("company")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.apollo.io/v1/people/match",
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": api_key,
                    "Cache-Control": "no-cache"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                person = data.get("person", {})
                return {
                    "success": True,
                    "person": {
                        "name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                        "title": person.get("title"),
                        "email": person.get("email"),
                        "phone": person.get("phone_numbers", [None])[0] if person.get("phone_numbers") else None,
                        "linkedin_url": person.get("linkedin_url"),
                        "city": person.get("city"),
                        "state": person.get("state"),
                        "country": person.get("country"),
                        "company": {
                            "name": person.get("organization", {}).get("name"),
                            "website": person.get("organization", {}).get("website_url"),
                            "industry": person.get("organization", {}).get("industry"),
                            "size": person.get("organization", {}).get("estimated_num_employees"),
                        }
                    }
                }
            else:
                return {"error": f"Apollo API error: {response.status_code}", "details": response.text[:200]}
    except Exception as e:
        logger.error("apollo_enrich_error", error=str(e))
        return {"error": f"Apollo API call failed: {str(e)}"}


async def execute_apollo_enrich_company(params: dict) -> dict:
    """Execute Apollo company enrichment API call."""
    api_key = settings.apollo_api_key
    if not api_key:
        return {"error": "Apollo API key not configured", "data": None}
    
    domain = params.get("domain", "")
    if not domain:
        return {"error": "Domain is required for company enrichment"}
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                "https://api.apollo.io/v1/organizations/enrich",
                params={"domain": domain},
                headers={
                    "X-Api-Key": api_key,
                    "Cache-Control": "no-cache"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                org = data.get("organization", {})
                return {
                    "success": True,
                    "company": {
                        "name": org.get("name"),
                        "website": org.get("website_url"),
                        "industry": org.get("industry"),
                        "employee_count": org.get("estimated_num_employees"),
                        "founded_year": org.get("founded_year"),
                        "description": org.get("short_description"),
                        "linkedin_url": org.get("linkedin_url"),
                        "location": {
                            "city": org.get("city"),
                            "state": org.get("state"),
                            "country": org.get("country"),
                        },
                        "keywords": org.get("keywords", [])[:10],
                    }
                }
            else:
                return {"error": f"Apollo API error: {response.status_code}", "details": response.text[:200]}
    except Exception as e:
        logger.error("apollo_company_enrich_error", error=str(e))
        return {"error": f"Apollo API call failed: {str(e)}"}


async def execute_phantombuster_launch(params: dict) -> dict:
    """Execute Phantombuster agent launch."""
    api_key = settings.phantombuster_api_key
    if not api_key:
        return {"error": "Phantombuster API key not configured", "data": None}
    
    phantom_id = params.get("id") or params.get("phantom_id")
    if not phantom_id:
        return {"error": "Phantom ID is required"}
    
    argument = params.get("argument", {})
    if isinstance(argument, str):
        try:
            argument = json.loads(argument)
        except:
            pass
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.phantombuster.com/api/v2/agents/launch",
                json={
                    "id": phantom_id,
                    "argument": json.dumps(argument) if isinstance(argument, dict) else argument,
                },
                headers={
                    "X-Phantombuster-Key": api_key,
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "container_id": data.get("containerId"),
                    "status": "launched",
                    "message": "Phantom launched successfully. Use phantombuster_fetch_output to get results."
                }
            else:
                return {"error": f"Phantombuster API error: {response.status_code}", "details": response.text[:200]}
    except Exception as e:
        logger.error("phantombuster_launch_error", error=str(e))
        return {"error": f"Phantombuster API call failed: {str(e)}"}


async def execute_phantombuster_fetch_output(params: dict) -> dict:
    """Fetch output from a Phantombuster agent."""
    api_key = settings.phantombuster_api_key
    if not api_key:
        return {"error": "Phantombuster API key not configured", "data": None}
    
    phantom_id = params.get("id") or params.get("phantom_id")
    if not phantom_id:
        return {"error": "Phantom ID is required"}
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                "https://api.phantombuster.com/api/v2/agents/fetch-output",
                params={"id": phantom_id},
                headers={"X-Phantombuster-Key": api_key}
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "output": data.get("output"),
                    "status": data.get("status"),
                }
            else:
                return {"error": f"Phantombuster API error: {response.status_code}", "details": response.text[:200]}
    except Exception as e:
        logger.error("phantombuster_fetch_error", error=str(e))
        return {"error": f"Phantombuster API call failed: {str(e)}"}


async def execute_perplexity_search(params: dict) -> dict:
    """Execute Perplexity AI search."""
    api_key = settings.perplexity_api_key
    if not api_key:
        return {"error": "Perplexity API key not configured", "data": None}
    
    query = params.get("query", "")
    if not query:
        return {"error": "Query is required for Perplexity search"}
    
    focus = params.get("focus", "")
    if focus == "company":
        system_msg = "You are a business research assistant. Provide comprehensive company information including size, funding, products, competitors, and recent news."
    elif focus == "person":
        system_msg = "You are a professional research assistant. Find information about this person's background, experience, and recent activities."
    elif focus == "market":
        system_msg = "You are a market research analyst. Provide market size, trends, key players, and growth projections."
    else:
        system_msg = "You are a thorough research assistant. Provide comprehensive, well-cited information."
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Use the latest sonar model (2026) - see docs.perplexity.ai/getting-started/models
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                json={
                    "model": "sonar",  # Default online model
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": query}
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.1,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                citations = data.get("citations", [])
                return {
                    "success": True,
                    "research": content,
                    "citations": citations[:5] if citations else [],
                    "model": data.get("model"),
                }
            else:
                return {"error": f"Perplexity API error: {response.status_code}", "details": response.text[:200]}
    except Exception as e:
        logger.error("perplexity_search_error", error=str(e))
        return {"error": f"Perplexity API call failed: {str(e)}"}


# Tool execution dispatcher
TOOL_EXECUTORS = {
    "apollo_search_people": execute_apollo_search_people,
    "apollo_enrich_person": execute_apollo_enrich_person,
    "apollo_enrich_company": execute_apollo_enrich_company,
    "phantombuster_launch": execute_phantombuster_launch,
    "phantombuster_fetch_output": execute_phantombuster_fetch_output,
    "perplexity_search": execute_perplexity_search,
}


# =============================================================================
# AGENT SYSTEM PROMPTS
# =============================================================================

AGENT_PROMPTS = {
    "classifier": """You are an intent classifier agent. Analyze the customer message and classify it.

Output JSON with:
- category: "billing" | "outage" | "other"
- urgency: "low" | "medium" | "high"
- summary: Brief summary of the issue
- keywords: Key terms from the message""",

    "billing_drafter": """You are a billing support agent. Draft a helpful response for billing-related issues.

Output JSON with:
- response_text: The drafted response
- suggested_actions: List of actions to take
- requires_escalation: boolean""",

    "outage_drafter": """You are a technical support agent. Draft a response about service outages.

Output JSON with:
- response_text: The drafted response
- current_status: Brief status summary
- eta: Estimated time to resolution if known""",

    "apollo_agent": """You are a sales intelligence agent with access to Apollo.io API.

You can use these tools:
- apollo_search_people: Search for contacts by ICP criteria. Key parameters:
  - person_titles: List of job titles ["CEO", "CTO", "VP Engineering"]
  - person_seniorities: ["owner", "c_suite", "vp", "director", "manager"]
  - q_organization_domains: Specific company domains to search
  - q_keywords: Industry keywords like "SaaS", "fintech", "software"
  - person_locations: Geographic filters ["United States", "San Francisco"]
  - organization_num_employees_ranges: ["1-10", "11-50", "51-200", "201-500"]
  - require_linkedin: true (IMPORTANT - filters to only contacts with LinkedIn URLs)
  - per_page: Number of results (default 25, max 50)
  
- apollo_enrich_person: Get detailed info about a specific person
  - linkedin_url: Their LinkedIn profile URL
  - email: Their email address
  
- apollo_enrich_company: Get company information
  - domain: Company website domain

IMPORTANT: Always request contacts with LinkedIn URLs (require_linkedin: true) for outreach workflows.

STRICT OUTPUT FORMAT (you MUST follow this exactly):
{
  "action_taken": "apollo_search_people",
  "filters_applied": {...},
  "contacts": [
    {
      "name": "Full Name",
      "title": "Job Title",
      "company": "Company Name",
      "email": "email@example.com or null",
      "linkedin_url": "https://linkedin.com/in/... or null",
      "location": "City, State"
    }
  ],
  "total_count": 25,
  "contacts_with_linkedin": 20
}

CRITICAL: The "contacts" array MUST be at the TOP LEVEL of your output, not nested inside "results".
Extract contacts from the API results and place them directly in the "contacts" array.""",

    "phantombuster_agent": """You are a LinkedIn automation agent with access to Phantombuster.

You can use these tools:
- phantombuster_launch: Launch a LinkedIn automation phantom
- phantombuster_fetch_output: Get results from a phantom run

Available phantoms include profile scrapers, search exporters, message senders, and auto-connectors.

Output JSON with:
- action_taken: What Phantombuster action was performed
- status: Current status of the automation
- results: Any available results""",

    "research_agent": """You are a research agent with access to Perplexity AI for web searches.

You can use:
- perplexity_search: Search the web for comprehensive research

Output JSON with:
- research_summary: Key findings from the research
- sources: Relevant sources/citations
- recommendations: Action items based on research""",

    "icp_prospect_searcher": """You are a prospect research agent specialized in finding ideal customers.

Given an ICP (Ideal Customer Profile) description, you will:
1. Parse the ICP into search criteria
2. Search Apollo.io for matching contacts WITH LinkedIn URLs (require_linkedin: true)
3. Return structured prospect data

Apollo search parameters you should determine from the ICP:
- person_titles: Job titles that match the ICP (e.g., ["Founder", "CEO", "CTO"])
- person_seniorities: Seniority levels (e.g., ["owner", "c_suite", "vp", "director"])  
- q_keywords: Industry/company keywords (e.g., "SaaS", "fintech", "B2B")
- organization_num_employees_ranges: Company size (e.g., ["11-50", "51-200"])
- person_locations: Geographic filters if mentioned

CRITICAL: Always set require_linkedin: true to ensure contacts have LinkedIn URLs for outreach.

STRICT OUTPUT FORMAT (you MUST follow this exactly):
{
  "search_criteria": {...},
  "contacts": [
    {
      "name": "Full Name",
      "title": "Job Title",
      "company": "Company Name",
      "email": "email@example.com or null",
      "linkedin_url": "https://linkedin.com/in/... or null",
      "location": "City, State"
    }
  ],
  "total_count": 25,
  "contacts_with_linkedin": 20
}

CRITICAL: The "contacts" array MUST be at the TOP LEVEL of your output, not nested.
Extract contacts from API results and place them directly in the "contacts" array.""",

    "full_prospect_pipeline": """You are a comprehensive prospect pipeline agent.

Given an ICP description, you will:
1. Search Apollo for matching contacts (will include LinkedIn search URLs if direct URLs unavailable)
2. For each prospect, draft a personalized outreach message based on available data

Apollo Search:
- Parse ICP into: person_titles, person_seniorities, q_keywords, organization_num_employees_ranges
- Note: Apollo API may provide linkedin_search_url (search link) instead of direct linkedin_url

Message Drafting (for each prospect):
- Use their name, title, company, and industry context
- Keep messages under 300 characters for LinkedIn
- Be professional but personalized
- Include a clear value proposition
- End with a soft call-to-action

STRICT OUTPUT FORMAT (you MUST follow this exactly):
{
  "contacts": [
    {
      "name": "Full Name",
      "title": "Job Title", 
      "company": "Company Name",
      "email": "email@example.com or null",
      "linkedin_url": "https://linkedin.com/in/... or null",
      "personalized_message": "Your personalized outreach message here"
    }
  ],
  "total_count": 25,
  "pipeline_summary": {"found": 25, "messages_drafted": 25}
}

CRITICAL: The "contacts" array MUST be at the TOP LEVEL of your output, not nested.
Each contact MUST have a "personalized_message" field.""",
}


def validate_tools(requested_tools: list[str]) -> list[str]:
    """Validate and filter requested tools against allowlist."""
    validated = []
    for tool in requested_tools:
        if tool in ALLOWED_TOOLS:
            validated.append(tool)
        else:
            logger.warning("tool_not_allowed", tool=tool)
    return validated


async def execute_tool_if_needed(agent_name: str, input_data: dict) -> Optional[dict]:
    """Execute relevant tools based on agent name and input."""
    
    input_str = str(input_data).lower()
    
    # Apollo agent - automatically call Apollo APIs
    # Detect Apollo-related agent names or inputs
    is_apollo_agent = any(k in agent_name.lower() for k in ["apollo", "prospect", "search", "lead", "icp"])
    is_apollo_input = any(k in input_str for k in ["domain", "enrich", "search_people", "find_contacts", "icp", "prospect", "executive"])
    
    if is_apollo_agent or is_apollo_input:
        # Determine which Apollo tool to use
        if input_data.get("domain") or input_data.get("company_domain"):
            domain = input_data.get("domain") or input_data.get("company_domain")
            
            # Search for people at the company
            if input_data.get("titles") or input_data.get("find_people") or "contact" in input_str:
                result = await execute_apollo_search_people({
                    "domains": [domain],
                    "titles": input_data.get("titles", ["CEO", "CTO", "VP", "Director", "Head"]),
                    "per_page": input_data.get("per_page", 10),
                    "require_linkedin": True,  # Always require LinkedIn URLs for outreach
                })
                return {"apollo_people_search": result}
            else:
                # Just enrich the company
                result = await execute_apollo_enrich_company({"domain": domain})
                return {"apollo_company_enrichment": result}
        
        elif input_data.get("email") or input_data.get("linkedin_url"):
            result = await execute_apollo_enrich_person(input_data)
            return {"apollo_person_enrichment": result}
        
        # Handle ICP-based searches without specific domains
        elif input_data.get("icp_description") or input_data.get("search_criteria") or \
             any(k in input_str for k in ["icp", "ideal customer", "prospect", "executive", "find people"]):
            # Build search parameters from ICP description or search criteria
            search_criteria = input_data.get("search_criteria", {})
            
            # Extract titles from search criteria or use defaults for executive search
            titles = search_criteria.get("titles") or input_data.get("titles") or ["Founder", "CEO", "CTO", "VP", "Director", "Head of"]
            
            # Try to extract seniorities
            seniorities = search_criteria.get("seniorities") or ["owner", "c_suite", "vp", "director"]
            
            # Extract any industries/keywords from the input
            icp_desc = input_data.get("icp_description", "")
            keywords = []
            if "saas" in icp_desc.lower():
                keywords.append("saas")
            if "b2b" in icp_desc.lower():
                keywords.append("b2b software")
            if "tech" in icp_desc.lower():
                keywords.append("technology")
                
            per_page = input_data.get("per_page", 25)
            
            logger.info(
                "apollo_icp_search",
                titles=titles,
                seniorities=seniorities,
                keywords=keywords,
                per_page=per_page,
            )
            
            result = await execute_apollo_search_people({
                "titles": titles,
                "seniorities": seniorities,
                "keywords": keywords if keywords else ["software", "technology"],
                "per_page": per_page,
                "require_linkedin": True,  # CRITICAL: Filter for contacts with LinkedIn URLs
            })
            return {"apollo_people_search": result}
    
    # Phantombuster agent
    if "phantombuster" in agent_name.lower() or "linkedin_automation" in agent_name.lower():
        if input_data.get("phantom_id") or input_data.get("id"):
            if input_data.get("fetch_output"):
                result = await execute_phantombuster_fetch_output(input_data)
            else:
                result = await execute_phantombuster_launch(input_data)
            return {"phantombuster_result": result}
    
    # Research agent / Perplexity
    if "research" in agent_name.lower() or "perplexity" in agent_name.lower():
        query = input_data.get("query") or input_data.get("topic") or input_data.get("company_name")
        if query:
            result = await execute_perplexity_search({
                "query": query,
                "focus": input_data.get("focus", "")
            })
            return {"perplexity_research": result}
    
    return None


@router.post("/agent/run", response_model=AgentRunResponse)
async def run_agent(request: AgentRunRequest) -> AgentRunResponse:
    """
    Execute an agent step within an n8n workflow.
    
    This endpoint supports real API integrations:
    - Apollo.io for lead/company enrichment
    - Phantombuster for LinkedIn automation
    - Perplexity for AI-powered research
    
    Security guardrails:
    - Tool allowlist validation
    - Timeout enforcement
    - Max tokens limit
    - Secret redaction in logs
    - Prompt injection detection
    """
    logger.info(
        "agent_run_request",
        agent_name=request.agent_name,
        input_keys=list(request.input.keys()),
        tools_requested=request.tools_allowed,
    )
    
    # Security check: Prompt injection detection
    input_text = str(request.input)
    if detect_prompt_injection(input_text):
        logger.warning(
            "prompt_injection_detected",
            agent_name=request.agent_name,
            input_preview=input_text[:100],
        )
        raise HTTPException(
            status_code=400,
            detail="Input rejected: potential prompt injection detected",
        )
    
    # Validate tools
    validated_tools = validate_tools(request.tools_allowed)
    
    # Execute real API tools if applicable
    tool_results = await execute_tool_if_needed(request.agent_name, request.input)
    
    # Get agent system prompt
    system_prompt = AGENT_PROMPTS.get(request.agent_name)
    if not system_prompt:
        # Build a dynamic prompt based on available tools
        tool_docs = []
        for tool_name in validated_tools:
            if tool_name in ALL_TOOLS:
                tool_info = ALL_TOOLS[tool_name]
                tool_docs.append(f"- {tool_name}: {tool_info['description']}")
        
        system_prompt = f"""You are a helpful agent named {request.agent_name}.

Available tools and APIs:
{chr(10).join(tool_docs) if tool_docs else 'No specific tools configured.'}

Process the input and return structured JSON output appropriate for the task.
If API results are provided, incorporate them into your response."""
    
    try:
        # Build context with tool results
        context_data = request.context or {}
        if tool_results:
            context_data["api_results"] = tool_results
        
        # Execute with timeout
        llm = get_llm_adapter()
        
        user_message = f"""Input data:
{json.dumps(request.input, indent=2)}

Context:
{json.dumps(context_data, indent=2)}

{"API Results:" + json.dumps(tool_results, indent=2) if tool_results else ""}

Respond with valid JSON only."""

        result = await asyncio.wait_for(
            llm.generate(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=settings.agent_runner_max_tokens,
                response_format="json",
            ),
            timeout=settings.agent_runner_timeout,
        )
        
        # Merge tool results into output if they exist
        output = result.content
        if tool_results and isinstance(output, dict):
            output["_api_data"] = tool_results
        
        # Normalize output: ensure "contacts" exists at top level for Apollo agents
        # This handles cases where LLM outputs results.people instead of contacts
        if isinstance(output, dict) and "apollo" in request.agent_name.lower():
            if "contacts" not in output:
                # Try to extract contacts from various possible paths
                contacts = None
                if "results" in output and isinstance(output["results"], dict):
                    if "people" in output["results"]:
                        contacts = output["results"]["people"]
                    elif "contacts" in output["results"]:
                        contacts = output["results"]["contacts"]
                
                if contacts:
                    # Normalize contact format
                    normalized_contacts = []
                    for c in contacts:
                        normalized_contacts.append({
                            "name": c.get("name") or f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                            "title": c.get("title", ""),
                            "company": c.get("company") or c.get("organization_name") or (c.get("organization", {}).get("name") if isinstance(c.get("organization"), dict) else ""),
                            "email": c.get("email"),
                            "linkedin_url": c.get("linkedin_url"),
                            "location": c.get("location") or c.get("city", ""),
                        })
                    output["contacts"] = normalized_contacts
                    logger.info("normalized_contacts", count=len(normalized_contacts))
        
        logger.info(
            "agent_run_success",
            agent_name=request.agent_name,
            tokens_used=result.metadata.get("tokens_used", 0),
            tools_executed=list(tool_results.keys()) if tool_results else [],
        )
        
        return AgentRunResponse(
            output=output,
            metadata={
                "agent_name": request.agent_name,
                "tokens_used": result.metadata.get("tokens_used", 0),
                "model": result.metadata.get("model", "unknown"),
                "tools_used": validated_tools,
                "api_calls_made": list(tool_results.keys()) if tool_results else [],
            },
        )
        
    except asyncio.TimeoutError:
        logger.error(
            "agent_run_timeout",
            agent_name=request.agent_name,
            timeout=settings.agent_runner_timeout,
        )
        raise HTTPException(
            status_code=504,
            detail=f"Agent execution timed out after {settings.agent_runner_timeout}s",
        )
    except Exception as e:
        logger.error(
            "agent_run_error",
            agent_name=request.agent_name,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
