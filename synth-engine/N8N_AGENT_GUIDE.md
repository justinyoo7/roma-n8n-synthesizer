# n8n Agent Configuration Guide

This guide shows how to configure n8n workflows to use Perseus agents for full observability and cost tracking.

## Why Use Perseus Agents?

When n8n calls APIs directly:
- ❌ No visibility into costs
- ❌ No latency tracking per node
- ❌ No centralized logging

When n8n routes through Perseus agents:
- ✅ Every call logged to `queries` table
- ✅ Cost tracking (LLM calls)
- ✅ Latency tracking per node
- ✅ Full analytics dashboard

## Architecture

```
n8n Workflow Node → HTTP Request → Perseus /api/agent/run → API → Response
                                         ↓
                                   Log to Supabase
```

## Available Agent Types

### LLM Agents (AI-powered)
These use language models and incur costs:

| Agent Name | Purpose | Cost |
|------------|---------|------|
| `classifier` | Categorize input | ~$0.001-0.01 per call |
| `drafter` | Generate responses | ~$0.002-0.02 per call |
| `apollo_agent` | Apollo + LLM analysis | ~$0.005-0.03 per call |
| `research_agent` | Perplexity research | ~$0.01-0.05 per call |
| `icp_prospect_searcher` | ICP-based search | ~$0.005-0.03 per call |

### Direct API Agents (No LLM)
These call APIs directly without LLM, no cost but still logged:

| Agent Name | Purpose | Latency |
|------------|---------|---------|
| `apollo_search_people` | Search Apollo for contacts | ~800-1500ms |
| `apollo_enrich_person` | Enrich person data | ~500-1000ms |
| `apollo_enrich_company` | Enrich company data | ~500-1000ms |
| `phantombuster_launch` | Launch LinkedIn automation | ~200-500ms |
| `phantombuster_fetch_output` | Get phantom results | ~300-800ms |
| `perplexity_search` | AI web search | ~2000-5000ms |

## n8n Node Configuration

### HTTP Request Node Setup

**Base Configuration:**
- **Method:** POST
- **URL:** `https://your-perseus-url.railway.app/api/agent/run`
- **Authentication:** None (if needed, add API key header)
- **Body:** JSON

### Example 1: Apollo People Search (Direct API)

**HTTP Request Node Body:**
```json
{
  "agent_name": "apollo_search_people",
  "input": {
    "titles": ["CEO", "CTO", "VP Engineering"],
    "seniorities": ["c_suite", "vp"],
    "q_keywords": "SaaS software",
    "per_page": 25,
    "require_linkedin": true
  },
  "workflow_id": "{{ $('Trigger').item.json.workflow_id }}",
  "node_id": "apollo_search"
}
```

**Response:**
```json
{
  "output": {
    "success": true,
    "contacts": [...],
    "total_results": 25
  },
  "metadata": {
    "latency_ms": 1200,
    "api_calls_made": ["apollo_search_people"]
  },
  "logged": true
}
```

**Access results:** `{{ $json.output.contacts }}`

### Example 2: AI Classification (LLM)

**HTTP Request Node Body:**
```json
{
  "agent_name": "classifier",
  "input": {
    "message": "{{ $json.customer_message }}"
  },
  "workflow_id": "{{ $('Trigger').item.json.workflow_id }}",
  "node_id": "classify_message"
}
```

**Response:**
```json
{
  "output": {
    "category": "billing",
    "urgency": "high",
    "summary": "Customer asking about refund"
  },
  "metadata": {
    "tokens_used": 250,
    "model": "claude-sonnet-4-20250514",
    "latency_ms": 2500
  },
  "logged": true
}
```

### Example 3: ICP Prospect Search (LLM + Apollo)

**HTTP Request Node Body:**
```json
{
  "agent_name": "icp_prospect_searcher",
  "input": {
    "icp_description": "{{ $json.icp }}",
    "per_page": 25
  },
  "workflow_id": "{{ $('Trigger').item.json.workflow_id }}",
  "node_id": "icp_search"
}
```

**Response includes:**
```json
{
  "output": {
    "search_criteria": {...},
    "contacts": [...],
    "total_count": 25
  },
  "metadata": {
    "tokens_used": 450,
    "latency_ms": 3500
  }
}
```

## Workflow Patterns

### Pattern 1: Simple Search → Respond

```
1. Webhook Trigger
   └─ Receives: { "icp": "..." }

2. HTTP Request (apollo_search_people)
   └─ Body: { "agent_name": "apollo_search_people", "input": {...} }

3. Respond to Webhook
   └─ Body: {{ $json.output.contacts }}
```

### Pattern 2: Search → Loop → Process → Aggregate

```
1. Webhook Trigger

2. HTTP Request (apollo_search_people)
   └─ Returns: { "output": { "contacts": [...] } }

3. Loop Over Items (n8n-nodes-base.itemLists)
   └─ Split: {{ $json.output.contacts }}

4. HTTP Request (AI message drafter)
   └─ For each contact: { "agent_name": "drafter", "input": {...} }

5. Aggregate (n8n-nodes-base.aggregate)
   └─ Combine all results

6. Respond to Webhook
```

## Tracking & Analytics

After adding agent nodes:

1. **Queries Table** - Every agent call creates a row:
   - `workflow_id`: Links to workflow
   - `node_id`: Identifies which node
   - `node_name`: Agent name
   - `latency_ms`: How long it took
   - `cost_usd`: LLM cost (0 for direct API)
   - `input_tokens`, `output_tokens`: Token usage

2. **Frontend Dashboard** shows:
   - Cost per workflow
   - Cost per node type
   - Latency trends
   - Query history

## Best Practices

### Always Include workflow_id and node_id

**Good:**
```json
{
  "agent_name": "apollo_search_people",
  "input": {...},
  "workflow_id": "{{ $('Trigger').item.json.workflow_id }}",
  "node_id": "apollo_search"
}
```

**Bad (no tracking):**
```json
{
  "agent_name": "apollo_search_people",
  "input": {...}
}
```

### Name Nodes Clearly

Use descriptive node names that will show up in analytics:
- ✅ "Search Apollo for VPs"
- ✅ "Classify Customer Intent"
- ❌ "HTTP Request"
- ❌ "Agent 1"

### Handle Errors

Check response status:
```javascript
// In n8n expression
{{ $json.output.success ? $json.output.contacts : [] }}
```

Or use n8n's error handling:
- Continue On Fail: Yes
- Retry On Fail: 2 attempts

## Migration Guide

To migrate existing workflows:

### Before (Direct Apollo Call):
```
HTTP Request
- URL: https://api.apollo.io/api/v1/mixed_people/api_search
- Headers: X-Api-Key: {{ $env.APOLLO_API_KEY }}
- Body: { "person_titles": [...] }
```

### After (Via Perseus Agent):
```
HTTP Request
- URL: https://your-perseus.railway.app/api/agent/run
- Body: {
    "agent_name": "apollo_search_people",
    "input": {
      "titles": ["CEO", "CTO"],
      "per_page": 25
    },
    "workflow_id": "{{ $('Trigger').item.json.workflow_id }}",
    "node_id": "apollo_search"
  }
```

## Cost Estimates

| Agent Type | Avg Cost | Avg Latency |
|------------|----------|-------------|
| Direct API (Apollo, Phantombuster) | $0.00 | 800-1500ms |
| Simple LLM (Classification) | $0.001-0.005 | 1000-3000ms |
| Complex LLM (Research, Generation) | $0.01-0.05 | 2000-8000ms |

**Perseus routing overhead: +100-300ms per node**

For a typical workflow with:
- 1 Apollo search
- 1 Loop (10 contacts)
- 10 AI message generations

**Total added latency:** ~2-4 seconds  
**Total cost tracked:** ~$0.10-0.30

## Troubleshooting

### Agent not logging queries?

Check:
1. Railway logs for `agent_run_request` entries
2. Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set in Railway
3. Check queries table for errors

### "Not Found" error?

Make sure your Perseus backend URL is correct and deployed.

### Workflow slow?

Direct API agents are fast (~1s). If slow, check:
- Is it an LLM agent? (LLM adds 2-8s)
- Network latency between n8n Cloud and Railway
- Use async patterns (parallel execution where possible)
