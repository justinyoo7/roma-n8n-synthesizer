# Perseus Workflow Synthesizer - Backend API Documentation

**Base URLs:**
- Local Development: `http://127.0.0.1:8000`
- Production (Railway): `https://perseus-tech-production.up.railway.app`

**Content-Type:** All requests use `application/json`

**n8n Cloud Instance:** `https://perseustech.app.n8n.cloud`

---

## Table of Contents

1. [Health Check](#1-health-check)
2. [Workflow Synthesis](#2-workflow-synthesis)
3. [Agent Execution](#3-agent-execution)
4. [Test Execution](#4-test-execution)
5. [Workflow Iteration](#5-workflow-iteration)
6. [n8n Operations](#6-n8n-operations)
   - Push Workflow
   - Get Executions
   - Activate/Deactivate
   - Print Workflow
7. [Webhook Proxy](#7-webhook-proxy)
8. [Data Types & Schemas](#8-data-types--schemas)
9. [Error Handling](#9-error-handling)
10. [Integration Examples](#10-integration-examples)
11. [Tested Workflow Examples](#11-tested-workflow-examples)
12. [Known Issues & Limitations](#12-known-issues--limitations)

---

## 1. Health Check

### `GET /health`

Check if the backend is running.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-03T12:00:00Z"
}
```

---

## 2. Workflow Synthesis

### `POST /api/synthesize`

Generate an n8n workflow from a natural language description. The workflow is automatically pushed to n8n and activated.

**Request Body:**
```typescript
interface SynthesizeRequest {
  prompt: string;              // Natural language workflow description (10-5000 chars)
  auto_iterate?: boolean;      // Auto-test and fix until passing (default: false)
  max_iterations?: number;     // Max iterations if auto_iterate=true (1-10, default: 5)
  workflow_id?: string;        // Existing workflow ID to iterate on (UUID)
  previous_iteration_id?: string; // Previous iteration to build upon (UUID)
  user_id?: string;            // User ID for tracking (UUID)
}
```

**Response:**
```typescript
interface SynthesizeResponse {
  // Identifiers
  workflow_id: string;         // UUID of the workflow
  iteration_id: string;        // UUID of this iteration
  iteration_version: number;   // Version number (1, 2, 3...)
  
  // Workflow Data
  workflow_ir: WorkflowIR;     // Intermediate representation (see schema below)
  n8n_json: object;            // Raw n8n workflow JSON
  
  // n8n Integration
  n8n_workflow_id: string | null;  // ID in n8n Cloud
  n8n_workflow_url: string | null; // URL to open in n8n
  webhook_url: string | null;      // Ready-to-use webhook URL
  webhook_path: string | null;     // Just the path portion
  
  // Quality Metrics
  score: number | null;        // Quality score (0-100)
  score_breakdown: {           // Individual scores
    correctness: number;
    simplicity: number;
    clarity: number;
    robustness: number;
  } | null;
  
  // Metadata
  rationale: string;           // Explanation of design decisions
  test_plan: TestCase[];       // Generated test cases
  
  // Auto-iteration fields (only if auto_iterate=true)
  auto_iterated?: boolean;
  total_iterations?: number;
  iteration_history?: IterationSummary[];
  success?: boolean;
  stop_reason?: string;
}
```

**Example Request:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/synthesize" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Create a webhook that analyzes sentiment of incoming text",
    "auto_iterate": false
  }'
```

**Example Response:**
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "iteration_id": "550e8400-e29b-41d4-a716-446655440001",
  "iteration_version": 1,
  "workflow_ir": {
    "name": "Sentiment Analysis Webhook",
    "description": "Analyzes sentiment of incoming text",
    "trigger": {
      "trigger_type": "webhook",
      "parameters": {"path": "sentiment-analysis", "httpMethod": "POST"}
    },
    "steps": [...]
  },
  "n8n_json": {...},
  "n8n_workflow_id": "abc123xyz",
  "n8n_workflow_url": "https://perseustech.app.n8n.cloud/workflow/abc123xyz",
  "webhook_url": "https://perseustech.app.n8n.cloud/webhook/sentiment-analysis",
  "webhook_path": "sentiment-analysis",
  "score": 85,
  "score_breakdown": {
    "correctness": 90,
    "simplicity": 85,
    "clarity": 80,
    "robustness": 85
  },
  "rationale": "Created a simple webhook → agent → respond pattern...",
  "test_plan": [...]
}
```

---

## 3. Agent Execution

### `POST /api/agent/run`

Execute an AI agent directly. Agents can search Apollo, research with Perplexity, draft messages, analyze sentiment, etc.

**Request Body:**
```typescript
interface AgentRunRequest {
  agent_name: string;          // Name of the agent to run
  input: object;               // Input data for the agent
  context?: object;            // Additional context
  tools_allowed?: string[];    // Allowed tool names (empty = auto-detect)
}
```

**Available Agents:**

| Agent Name | Purpose | Input Fields | API Calls Made |
|------------|---------|--------------|----------------|
| `apollo_agent` | Search Apollo.io for leads | `task`, `icp_description`, `titles`, `seniorities` | Apollo People Search |
| `perplexity_agent` | Perplexity AI research | `query`, `topic`, `focus` | Perplexity Search |
| `research_agent` | General AI research | `query`, `topic`, `task` | Perplexity Search |
| `full_prospect_pipeline` | Complete prospecting | `icp_description` | Apollo + Analysis |
| `icp_prospect_searcher` | ICP-based search | `icp_description`, `search_criteria` | Apollo People Search |
| `message_drafter` | Draft personalized messages | `prospect`, `task` | None (LLM only) |
| `sentiment_analyzer` | Analyze text sentiment | `text`, `task` | None (LLM only) |
| `phantombuster_agent` | LinkedIn automation | `phantom_id`, `arguments` | Phantombuster API |
| `company_researcher` | Research company info | `company`, `task` | Perplexity Search |
| `executive_researcher` | Research individual exec | `name`, `title`, `company` | Perplexity Search |
| `email_writer` | Draft cold emails | `prospect`, `research`, `task` | None (LLM only) |
| `content_researcher` | Content research | `topic`, `url` | Perplexity Search |
| `twitter_thread_creator` | Create Twitter threads | `content`, `insights` | None (LLM only) |
| `linkedin_content_creator` | Create LinkedIn posts | `content`, `insights` | None (LLM only) |
| `action_generator` | Generate follow-up actions | `lead`, `score`, `route` | None (LLM only) |

**Response:**
```typescript
interface AgentRunResponse {
  output: object;              // Agent's response (structure varies by agent)
  metadata: {
    agent_name: string;
    tokens_used: number;
    model: string;
    tools_used: string[];
    api_calls_made: string[];
  };
}
```

**Example - Apollo Search:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/agent/run" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "apollo_agent",
    "input": {
      "task": "Search for B2B SaaS founders",
      "icp_description": "Founders and CEOs at B2B SaaS companies with 10-200 employees"
    },
    "context": {},
    "tools_allowed": []
  }'
```

**Example Response - Apollo:**
```json
{
  "output": {
    "action_taken": "apollo_search_people",
    "filters_applied": {
      "person_titles": ["CEO", "Founder", "Co-Founder"],
      "person_seniorities": ["owner", "c_suite"],
      "q_keywords": "SaaS",
      "require_linkedin": true
    },
    "contacts": [
      {
        "name": "Sarah Johnson",
        "title": "CEO & Co-Founder",
        "email": "sarah@techflow.com",
        "linkedin_url": "https://linkedin.com/in/sarah-johnson",
        "company": "TechFlow Solutions",
        "location": "San Francisco, CA"
      }
    ],
    "total_count": 847,
    "contacts_with_linkedin": 25,
    "_api_data": {
      "apollo_people_search": {
        "success": true,
        "contacts": [...],
        "total_results": 847
      }
    }
  },
  "metadata": {
    "agent_name": "apollo_agent",
    "tokens_used": 1234,
    "model": "claude-sonnet-4-20250514",
    "api_calls_made": ["apollo_people_search"]
  }
}
```

**Example - Perplexity Research:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/agent/run" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "perplexity_agent",
    "input": {
      "query": "Latest AI automation trends in enterprise sales 2026",
      "task": "Research current trends and key players"
    },
    "context": {},
    "tools_allowed": []
  }'
```

**Example - Full Prospect Pipeline:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/agent/run" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "full_prospect_pipeline",
    "input": {
      "icp_description": "Enterprise CTOs at Fortune 500 companies in the fintech sector"
    },
    "context": {},
    "tools_allowed": []
  }'
```

---

## 4. Test Execution

### `POST /api/tests/run`

Run tests against a workflow. Tests execute via real n8n webhooks.

**Request Body:**
```typescript
interface TestRunRequest {
  workflow_ir: WorkflowIR;     // The workflow intermediate representation
  n8n_json: object;            // The compiled n8n workflow JSON
  n8n_workflow_id?: string;    // n8n workflow ID (required for real execution)
  force_real?: boolean;        // Force real n8n execution (default: true)
  test_cases?: TestCase[];     // Custom test cases (optional, auto-generated if omitted)
}
```

**Response:**
```typescript
interface TestRunResponse {
  results: TestResult[];
  passed_count: number;
  total_count: number;
  all_passed: boolean;
  real_execution_count: number;
  simulated_execution_count: number;
  webhook_url?: string;
  timestamp: string;
}

interface TestResult {
  test_name: string;
  passed: boolean;
  input_payload: object;
  actual_output?: object;
  expected_output?: object;
  failure_reason?: string;
  duration_ms: number;
  execution_mode: "real" | "simulated";
  executed_at: string;
}
```

**Example:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/tests/run" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_ir": {...},
    "n8n_json": {...},
    "n8n_workflow_id": "abc123",
    "force_real": true
  }'
```

---

## 5. Workflow Iteration

### `POST /api/iterate`

Analyze test failures and generate fixes for a workflow.

**Request Body:**
```typescript
interface IterateRequest {
  workflow_ir: WorkflowIR;     // Current workflow
  test_results: TestResult[];  // Failed test results
  n8n_errors?: string[];       // Any n8n execution errors
}
```

**Response:**
```typescript
interface IterateResponse {
  analysis: string;            // LLM analysis of failures
  fixes: Fix[];                // Proposed fixes
  updated_workflow_ir: WorkflowIR;  // Fixed workflow IR
  updated_n8n_json: object;    // Fixed n8n JSON
}

interface Fix {
  fix_type: "update_parameters" | "replace_node" | "add_edge" | "remove_edge" | "add_step" | "remove_step";
  step_id: string;
  description: string;
  changes: object;
}
```

**Example:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/iterate" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_ir": {...},
    "test_results": [
      {
        "test_name": "Happy path",
        "passed": false,
        "failure_reason": "Timeout after 30s"
      }
    ],
    "n8n_errors": []
  }'
```

---

## 6. n8n Operations

### `POST /api/n8n/push`

Push a workflow to n8n Cloud.

**Request Body:**
```typescript
interface PushRequest {
  workflow_json: object;       // n8n workflow JSON
  activate?: boolean;          // Activate after push (default: true)
  workflow_id?: string;        // Existing workflow ID to update
}
```

**Response:**
```typescript
interface PushResponse {
  success: boolean;
  n8n_workflow_id: string;
  n8n_workflow_url: string;
  message: string;
}
```

---

### `GET /api/n8n/executions/{workflow_id}`

Get execution history for a workflow.

**Query Parameters:**
- `limit` (optional): Number of executions to return (default: 10)

**Response:**
```typescript
interface ExecutionsResponse {
  executions: ExecutionSummary[];
  workflow_id: string;
}

interface ExecutionSummary {
  id: string;
  workflowId: string;
  status: "waiting" | "running" | "success" | "error";
  startedAt: string;
  stoppedAt?: string;
  duration?: number;
}
```

---

### `GET /api/n8n/executions/{workflow_id}/{execution_id}`

Get detailed execution data including node outputs.

**Response:**
```typescript
interface ExecutionDetailResponse {
  execution: ExecutionDetail;
  workflow_id: string;
  execution_id: string;
}

interface ExecutionDetail {
  id: string;
  status: string;
  startedAt: string;
  stoppedAt?: string;
  data: {
    resultData: {
      runData: {
        [nodeName: string]: NodeExecutionData[];
      };
      error?: object;
    };
  };
}
```

---

### `POST /api/n8n/activate/{workflow_id}`

Activate or deactivate a workflow.

**Request Body:**
```typescript
interface ActivateRequest {
  active: boolean;
}
```

**Response:**
```typescript
interface ActivateResponse {
  success: boolean;
  workflow_id: string;
  active: boolean;
  message: string;
}
```

---

### `POST /api/n8n/print`

Print a workflow in a clean, human-readable text format.

**Request Body:**
```typescript
interface PrintWorkflowRequest {
  workflow_json: object;       // n8n workflow JSON to print
  include_params?: boolean;    // Include node parameters (default: false)
  format?: "full" | "compact"; // Output format (default: "full")
}
```

**Response:**
```typescript
interface PrintWorkflowResponse {
  text: string;                // Formatted text representation
  format: string;              // Format used
}
```

**Formats:**
- `full`: Detailed view with all nodes, connections, and optional parameters
- `compact`: One-line summary showing node flow

**Example:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/n8n/print" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_json": {...},
    "include_params": false,
    "format": "full"
  }'
```

**Example Output (full format):**
```
============================================================
  WORKFLOW: Apollo Prospect Research
============================================================
  ID: WrKMNdAjCpnI2HnL
  Active: ✓ Yes

  NODES:
  --------------------------------------------------------
  🔗 [1] Trigger
       Type: webhook (v1)
       Position: (0, 200)

  🌐 [2] Search Apollo
       Type: httpRequest (v4)
       Position: (300, 200)

  🤖 [3] AI Agent
       Type: httpRequest (v4)
       Position: (600, 200)

  📤 [4] Respond
       Type: respondToWebhook (v1)
       Position: (900, 200)

  FLOW:
  --------------------------------------------------------
  🔗 Trigger
    └──→ 🌐 Search Apollo
      └──→ 🤖 AI Agent
        └──→ 📤 Respond

  WEBHOOK:
  --------------------------------------------------------
  Method: POST
  Path: /apollo-research

============================================================
```

**Example Output (compact format):**
```
📋 Apollo Prospect Research

🔗 Trigger → 🌐 Search Apollo → 🤖 AI Agent → 📤 Respond
```

---

### `GET /api/n8n/print/{workflow_id}`

Fetch a workflow from n8n and print it in text format.

**Path Parameters:**
- `workflow_id`: n8n workflow ID

**Query Parameters:**
- `include_params` (optional): Include node parameters (default: false)
- `format` (optional): Output format - "full" or "compact" (default: "full")

**Response:**
```typescript
interface PrintWorkflowResponse {
  text: string;                // Formatted text representation
  format: string;              // Format used
}
```

**Example:**
```bash
# Full view
curl "https://perseus-tech-production.up.railway.app/api/n8n/print/WrKMNdAjCpnI2HnL"

# Compact view
curl "https://perseus-tech-production.up.railway.app/api/n8n/print/WrKMNdAjCpnI2HnL?format=compact"

# With parameters
curl "https://perseus-tech-production.up.railway.app/api/n8n/print/WrKMNdAjCpnI2HnL?include_params=true"
```

**Node Icons Legend:**
| Icon | Node Type |
|------|-----------|
| 🔗 | Webhook |
| 🌐 | HTTP Request |
| 🤖 | AI Agent |
| 📝 | Set |
| 🔀 | If/Switch |
| 📤 | Respond to Webhook |
| 🔄 | Item Lists / Split |
| 📦 | Aggregate / Merge |
| 💬 | Slack |
| 📧 | Email / Gmail |
| 🗄️ | Database |
| ⏰ | Schedule / Cron |
| ⚙️ | Other |

---

## 7. Webhook Proxy

### `POST /api/webhook/proxy`

Forward a request to an n8n webhook. Use this to bypass CORS restrictions in the browser.

**Request Body:**
```typescript
interface WebhookProxyRequest {
  webhook_url: string;         // Full n8n webhook URL
  payload: object;             // Request body to send
  method?: string;             // HTTP method (default: "POST")
}
```

**Response:**
```typescript
interface WebhookProxyResponse {
  status_code: number;
  body: any;                   // Response from n8n webhook
  success: boolean;
  error?: string;
}
```

**Example:**
```bash
curl -X POST "https://perseus-tech-production.up.railway.app/api/webhook/proxy" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_url": "https://perseustech.app.n8n.cloud/webhook/lead-qualification",
    "payload": {"message": "Find VP-level executives at fintech startups"},
    "method": "POST"
  }'
```

---

## 8. Data Types & Schemas

### WorkflowIR (Intermediate Representation)

```typescript
interface WorkflowIR {
  id?: string;
  name: string;
  description: string;
  
  trigger: {
    trigger_type: "webhook" | "manual" | "schedule";
    parameters: {
      path?: string;           // Webhook path
      httpMethod?: string;     // GET, POST, etc.
      schedule?: {             // For schedule triggers
        mode: string;
        value: number;
        unit: string;
      };
    };
  };
  
  steps: StepSpec[];
  edges: EdgeSpec[];
  
  error_strategy?: {
    on_error: "stop" | "continue" | "retry";
    retry_count?: number;
    retry_delay_ms?: number;
  };
  
  test_invariants?: TestInvariant[];
  metadata?: object;
}
```

### StepSpec

```typescript
interface StepSpec {
  id: string;
  name: string;
  description?: string;
  
  type: "action" | "transform" | "agent" | "branch" | "merge";
  
  n8n_node_type: string;       // e.g., "n8n-nodes-base.httpRequest"
  n8n_type_version?: number;
  
  parameters: object;          // Node-specific parameters
  
  // For agent steps
  agent?: {
    name: string;
    role: string;
    system_prompt?: string;
    output_schema?: object;
  };
  
  // For branch steps
  branch_conditions?: BranchCondition[];
  
  // Positioning
  position: {
    x: number;
    y: number;
  };
  
  // Data contracts
  input_contract?: DataContract;
  output_contract?: DataContract;
}
```

### EdgeSpec

```typescript
interface EdgeSpec {
  from_step: string;           // Step ID or "trigger"
  to_step: string;             // Step ID
  condition?: string;          // Optional condition expression
  output_index?: number;       // For nodes with multiple outputs
}
```

### TestCase

```typescript
interface TestCase {
  name: string;
  description?: string;
  input: object;
  expected_output_contains?: string[];
  expected_status?: string;
  timeout_ms?: number;
}
```

---

## 9. Error Handling

All endpoints return errors in this format:

```typescript
interface ErrorResponse {
  detail: string;              // Error message
  status_code?: number;        // HTTP status code
}
```

**Common Error Codes:**

| Code | Meaning |
|------|---------|
| 400 | Bad Request - Invalid input |
| 404 | Not Found - Workflow/resource doesn't exist |
| 422 | Validation Error - Schema validation failed |
| 500 | Internal Server Error |
| 504 | Gateway Timeout - Agent/API call timed out |

**Example Error Response:**
```json
{
  "detail": "ANTHROPIC_API_KEY not configured"
}
```

---

## 10. Integration Examples

### Frontend Integration (React/TypeScript)

```typescript
// api.ts
const API_BASE = process.env.REACT_APP_API_URL || 'https://perseus-tech-production.up.railway.app';

export const api = {
  async synthesize(prompt: string, autoIterate = false) {
    const response = await fetch(`${API_BASE}/api/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, auto_iterate: autoIterate }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },

  async runAgent(agentName: string, input: object) {
    const response = await fetch(`${API_BASE}/api/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_name: agentName,
        input,
        context: {},
        tools_allowed: [],
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },

  async runTests(workflowIr: object, n8nJson: object, n8nWorkflowId: string) {
    const response = await fetch(`${API_BASE}/api/tests/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workflow_ir: workflowIr,
        n8n_json: n8nJson,
        n8n_workflow_id: n8nWorkflowId,
        force_real: true,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },

  async proxyWebhook(webhookUrl: string, payload: object) {
    const response = await fetch(`${API_BASE}/api/webhook/proxy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ webhook_url: webhookUrl, payload }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },

  async getExecutions(workflowId: string, limit = 10) {
    const response = await fetch(
      `${API_BASE}/api/n8n/executions/${workflowId}?limit=${limit}`
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },

  async activateWorkflow(workflowId: string, active: boolean) {
    const response = await fetch(`${API_BASE}/api/n8n/activate/${workflowId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },

  async printWorkflow(workflowId: string, format = 'full') {
    const response = await fetch(
      `${API_BASE}/api/n8n/print/${workflowId}?format=${format}`
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },
};
```

### Usage in React Component

```tsx
import { useState } from 'react';
import { api } from './api';

function WorkflowBuilder() {
  const [prompt, setPrompt] = useState('');
  const [workflow, setWorkflow] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSynthesize = async () => {
    setLoading(true);
    try {
      const result = await api.synthesize(prompt, false);
      setWorkflow(result);
    } catch (error) {
      console.error('Synthesis failed:', error);
    }
    setLoading(false);
  };

  const handleTest = async () => {
    if (!workflow) return;
    const results = await api.runTests(
      workflow.workflow_ir,
      workflow.n8n_json,
      workflow.n8n_workflow_id
    );
    console.log('Test results:', results);
  };

  const handleTryWebhook = async () => {
    if (!workflow?.webhook_url) return;
    const result = await api.proxyWebhook(workflow.webhook_url, {
      message: 'Test message',
    });
    console.log('Webhook response:', result);
  };

  return (
    <div>
      <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      <button onClick={handleSynthesize} disabled={loading}>
        {loading ? 'Generating...' : 'Generate Workflow'}
      </button>
      {workflow && (
        <>
          <p>Webhook URL: {workflow.webhook_url}</p>
          <button onClick={handleTest}>Run Tests</button>
          <button onClick={handleTryWebhook}>Try Webhook</button>
        </>
      )}
    </div>
  );
}
```

---

## 11. Tested Workflow Examples

These workflows have been tested and verified on Railway (February 2026):

### 1. Lead Qualification Pipeline ✅

**Webhook:** `https://perseustech.app.n8n.cloud/webhook/lead-qualification`
**n8n ID:** `ivIuTXqftiO5lmeN`
**Steps:** 9 (Search → Split → Research → Qualify → Check → Draft → Format → Aggregate → Respond)
**Status:** SUCCESS - 901KB response

```bash
curl -X POST "https://perseustech.app.n8n.cloud/webhook/lead-qualification" \
  -H "Content-Type: application/json" \
  -d '{"message": "Find VP-level executives at fintech startups"}'
```

**Sample Response:**
```json
{
  "qualified_leads": [
    {
      "output": {
        "personalized_emails": [
          {
            "prospect": {
              "name": "Hakan",
              "title": "Deputy Chief Executive Officer (CTO)",
              "company": "Odeon Software & Technology"
            },
            "email": {
              "subject": "Technology Modernization Strategy for Odeon Software & Technology",
              "body": "Dear Hakan,\n\nAs Deputy CEO and CTO at Odeon Software...",
              "personalization_notes": [
                "Addresses dual CEO/CTO role and decision-making authority",
                "Focuses on technology modernization challenges"
              ]
            }
          }
        ]
      }
    }
  ]
}
```

---

### 2. Content Repurposing Pipeline ✅

**Webhook:** `https://perseustech.app.n8n.cloud/webhook/content-repurpose`
**n8n ID:** `YzMnFJ3JTGct13GZ`
**Steps:** 6 (Research → Twitter → LinkedIn → Newsletter → Format → Respond)
**Status:** SUCCESS - 3KB response

```bash
curl -X POST "https://perseustech.app.n8n.cloud/webhook/content-repurpose" \
  -H "Content-Type: application/json" \
  -d '{"topic": "AI agents in enterprise workflows - how companies are automating complex business processes with LLMs"}'
```

**Sample Response:**
```json
{
  "twitter_thread": {
    "hook_tweet": "🤖 AI agents are quietly revolutionizing enterprise workflows...",
    "thread_tweets": [
      "1/ Traditional RPA tools follow rigid scripts. AI agents powered by LLMs? They reason through exceptions...",
      "2/ The magic happens through \"observe-plan-act\" cycles...",
      "..."
    ],
    "engagement_elements": {
      "hashtags": ["#AIAgents", "#WorkflowAutomation", "#EnterpriseAI"],
      "call_to_action": "What workflows in your organization could benefit from intelligent agents?"
    },
    "thread_metrics": {
      "total_tweets": 10,
      "estimated_read_time": "2-3 minutes"
    }
  }
}
```

---

### 3. Lead Scoring & Routing ✅

**Webhook:** `https://perseustech.app.n8n.cloud/webhook/lead-scoring`
**n8n ID:** `oVC0kCIw6AYDafGH`
**Steps:** 6 (Enrich → Research → Score → Actions → Format → Respond)
**Status:** SUCCESS - 2.4KB response

```bash
curl -X POST "https://perseustech.app.n8n.cloud/webhook/lead-scoring" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sarah Chen",
    "email": "sarah.chen@techcorp.com",
    "company": "TechCorp AI",
    "job_title": "VP of Engineering"
  }'
```

**Sample Response:**
```json
{
  "follow_up_actions": [
    {
      "action_type": "research_enhancement",
      "priority": "high",
      "tasks": [
        {
          "task": "company_website_analysis",
          "description": "Search and analyze TechCorp AI's official website...",
          "assigned_to": "research_team",
          "deadline": "24_hours"
        }
      ]
    }
  ],
  "lead_score_adjustment": {
    "current_score": 30,
    "recommended_score": 45,
    "adjustment_reason": "Identified key contact with relevant title in growing AI sector..."
  },
  "escalation_criteria": {
    "escalate_if": [
      "Company research reveals Series A+ funding",
      "Employee count exceeds 50 people"
    ],
    "escalate_to": "senior_sales_manager"
  }
}
```

---

### 4. Competitive Intelligence ⚠️

**Webhook:** `https://perseustech.app.n8n.cloud/webhook/competitive-intel`
**n8n ID:** `GsiHVPBiyIcpnyI4`
**Steps:** 8 (Research → Find Competitors → Split → Research Each → Combine → Battle Card → Format → Respond)
**Status:** PARTIAL - Executes but returns empty response (known Set node bug)

---

### 5. ABM Pipeline ❌

**Webhook:** `https://perseustech.app.n8n.cloud/webhook/abm-pipeline`
**n8n ID:** `kCPruMuipcIwd3DV`
**Steps:** 9 (Find Execs → Split → Research → Pain Points → Aggregate → Stakeholder Map → Outreach → Playbook → Respond)
**Status:** TIMEOUT - Exceeds n8n Cloud 100s webhook limit

---

## 12. Known Issues & Limitations

### Timeout Constraints

**n8n Cloud has a 100-second webhook response timeout.** Workflows that process multiple items through loops (e.g., researching 5+ executives) will timeout.

**Workarounds:**
1. Limit the number of items per execution (e.g., max 3)
2. Use async patterns with callback webhooks
3. Batch multiple items into single agent calls

**Affected Workflows:** ABM Pipeline, any workflow with `itemLists` → loop → `aggregate` patterns processing 5+ items

---

### Empty Response Bug

**Set nodes after agent steps may return empty responses.** This occurs when Set nodes reference `$json.field_name` but the agent output is at `$json.output`.

**Affected Workflows:** Competitive Intelligence pipeline

**Workaround:** Use simpler workflows without intermediate Set nodes, or ensure Set nodes reference `$json.output.field_name`.

---

### Agent Output Structure

Apollo agent output follows this structure:
```json
{
  "output": {
    "action_taken": "apollo_search_people",
    "contacts": [...],
    "total_count": 50,
    "_api_data": {
      "apollo_people_search": {...}
    }
  }
}
```

For `itemLists` nodes to work correctly, they must split on `output.contacts` (not `output._api_data.apollo_people_search.contacts`).

---

### Execution Time Estimates

| Workflow Complexity | Typical Duration |
|---------------------|------------------|
| Simple (3-4 nodes) | 10-20 seconds |
| Medium (5-6 nodes) | 25-40 seconds |
| Complex with loops | 60-120+ seconds |

---

## Environment Variables

The backend requires these environment variables:

```bash
# Required - LLM
ANTHROPIC_API_KEY=sk-ant-...

# Required - n8n Integration
N8N_API_KEY=n8n_api_...
N8N_BASE_URL=https://perseustech.app.n8n.cloud/api/v1

# Required - Agent Runner (for n8n to call back)
AGENT_RUNNER_URL=https://perseus-tech-production.up.railway.app

# API Integrations
APOLLO_API_KEY=...
PERPLEXITY_API_KEY=...
PHANTOMBUSTER_API_KEY=...

# Optional
OPENAI_API_KEY=sk-...
SUPABASE_URL=...
SUPABASE_KEY=...
CLEARBIT_API_KEY=...
```

---

## Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/synthesize` | POST | Generate workflow from prompt |
| `/api/agent/run` | POST | Run AI agent directly |
| `/api/tests/run` | POST | Run tests on workflow |
| `/api/iterate` | POST | Analyze failures & generate fixes |
| `/api/n8n/push` | POST | Push workflow to n8n |
| `/api/n8n/executions/{id}` | GET | Get execution history |
| `/api/n8n/activate/{id}` | POST | Activate/deactivate workflow |
| `/api/n8n/print/{id}` | GET | Print workflow as text |
| `/api/n8n/print` | POST | Print workflow JSON as text |
| `/api/webhook/proxy` | POST | Proxy webhook requests |

---

*Last updated: February 3, 2026*
