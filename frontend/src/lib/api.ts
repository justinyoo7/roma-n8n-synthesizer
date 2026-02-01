import type { 
  SynthesizeRequest, 
  SynthesizeResponse, 
  ExecutionsResponse,
  ExecutionDetail,
  ActivateResponse,
  ExecutionStatus,
} from '../types/workflow'

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

console.log('API Client initialized with base URL:', API_BASE)

class APIClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`
    console.log(`[API] ${options.method || 'GET'} ${url}`)
    
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
      })

      console.log(`[API] Response status: ${response.status}`)

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
        console.error('[API] Error response:', error)
        throw new Error(error.detail || `HTTP ${response.status}`)
      }

      const data = await response.json()
      console.log('[API] Response data received')
      return data
    } catch (err) {
      console.error('[API] Request failed:', err)
      throw err
    }
  }

  // Health check
  async health(): Promise<{ status: string; version: string }> {
    return this.request('/health')
  }

  // Synthesize a workflow from natural language
  async synthesize(request: SynthesizeRequest): Promise<SynthesizeResponse> {
    return this.request('/api/synthesize', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  }

  // Iterate on a workflow (manual iteration with feedback)
  async iterate(
    workflowId: string,
    iterationId: string,
    failureTraces: Array<Record<string, unknown>>,
    userFeedback?: string
  ): Promise<SynthesizeResponse> {
    return this.request('/api/iterate', {
      method: 'POST',
      body: JSON.stringify({
        workflow_id: workflowId,
        iteration_id: iterationId,
        failure_traces: failureTraces,
        user_feedback: userFeedback,
      }),
    })
  }

  // Auto-iterate on a workflow (regenerate with auto-iteration)
  async autoIterate(
    prompt: string,
    workflowId?: string,
    maxIterations: number = 3
  ): Promise<SynthesizeResponse> {
    return this.request('/api/synthesize', {
      method: 'POST',
      body: JSON.stringify({
        prompt,
        workflow_id: workflowId,
        auto_iterate: true,
        max_iterations: maxIterations,
      }),
    })
  }

  // Run tests on a workflow - REAL EXECUTION via n8n webhook
  async runTests(
    workflowIR: Record<string, unknown>,
    n8nJson?: Record<string, unknown>,
    n8nWorkflowId?: string,
  ): Promise<{
    results: Array<{
      test_name: string
      passed: boolean
      failure_reason?: string
      duration_ms: number
      execution_mode: string  // "real" or "simulated"
      webhook_url?: string
    }>
    passed_count: number
    total_count: number
    all_passed: boolean
    real_execution_count: number
    simulated_execution_count: number
    webhook_url?: string
  }> {
    return this.request('/api/test', {
      method: 'POST',
      body: JSON.stringify({
        workflow_ir: workflowIR,
        n8n_json: n8nJson,
        n8n_workflow_id: n8nWorkflowId,
        force_real: true,  // Always try real execution
      }),
    })
  }

  // Simplify a workflow
  async simplify(
    workflowId: string,
    iterationId: string
  ): Promise<{
    iteration_id: string
    workflow_ir: Record<string, unknown>
    simplifications_applied: string[]
    nodes_removed: number
    original_score: number
    new_score: number
  }> {
    return this.request('/api/simplify', {
      method: 'POST',
      body: JSON.stringify({
        workflow_id: workflowId,
        iteration_id: iterationId,
        preserve_tests: true,
      }),
    })
  }

  // Check n8n connection status
  async checkN8NStatus(): Promise<{
    connected: boolean
    base_url?: string
    message: string
  }> {
    return this.request('/api/n8n/status')
  }

  // Push workflow to n8n
  async pushToN8N(
    workflowJson: Record<string, unknown>,
    options?: { workflowName?: string; activate?: boolean }
  ): Promise<{
    success: boolean
    n8n_workflow_id?: string
    n8n_workflow_url?: string
    message: string
  }> {
    return this.request('/api/n8n/push', {
      method: 'POST',
      body: JSON.stringify({
        workflow_json: workflowJson,
        workflow_name: options?.workflowName,
        activate: options?.activate ?? false,
      }),
    })
  }

  // Proxy webhook request through backend (avoids CORS issues)
  async proxyWebhook(
    webhookUrl: string,
    payload: Record<string, unknown>,
    method: string = 'POST'
  ): Promise<{
    status_code: number
    body: unknown
    success: boolean
    error?: string
  }> {
    return this.request('/api/webhook/proxy', {
      method: 'POST',
      body: JSON.stringify({
        webhook_url: webhookUrl,
        payload,
        method,
      }),
    })
  }

  // ============================================================================
  // Execution History
  // ============================================================================

  // Get execution history for a workflow
  async getExecutions(
    workflowId: string,
    options?: { limit?: number; status?: ExecutionStatus }
  ): Promise<ExecutionsResponse> {
    const params = new URLSearchParams()
    if (options?.limit) params.set('limit', String(options.limit))
    if (options?.status) params.set('status', options.status)
    
    const queryString = params.toString()
    const endpoint = `/api/n8n/executions/${workflowId}${queryString ? `?${queryString}` : ''}`
    
    return this.request(endpoint)
  }

  // Get detailed execution data (with node outputs)
  async getExecutionDetail(
    workflowId: string,
    executionId: string
  ): Promise<ExecutionDetail> {
    return this.request(`/api/n8n/executions/${workflowId}/${executionId}`)
  }

  // ============================================================================
  // Workflow Activation
  // ============================================================================

  // Activate or deactivate a workflow in n8n
  async activateWorkflow(
    workflowId: string,
    active: boolean
  ): Promise<ActivateResponse> {
    return this.request(`/api/n8n/activate/${workflowId}`, {
      method: 'POST',
      body: JSON.stringify({ active }),
    })
  }
}

export const api = new APIClient(API_BASE)
