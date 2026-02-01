// Types matching the backend WorkflowIR schema

export interface Position {
  x: number
  y: number
}

export interface FieldSchema {
  name: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'any'
  required: boolean
  description?: string
}

export interface DataContract {
  name: string
  description?: string
  fields: FieldSchema[]
}

export interface AgentSpec {
  name: string
  role: string
  system_prompt?: string
  tools_allowed: string[]
  input_schema: DataContract
  output_schema: DataContract
}

export interface StepSpec {
  id: string
  name: string
  type: 'trigger' | 'action' | 'branch' | 'merge' | 'agent' | 'transform'
  description?: string
  agent?: AgentSpec
  n8n_node_type: string
  n8n_type_version: number
  parameters: Record<string, unknown>
  trigger_type?: 'webhook' | 'manual' | 'schedule' | 'app_event'
  trigger_config?: Record<string, unknown>
  branch_conditions?: Array<Record<string, unknown>>
  position: Position
}

export interface EdgeSpec {
  id: string
  source_id: string
  target_id: string
  source_output: string
  target_input: string
  data_contract?: DataContract
  transform_expression?: string
  condition?: string
  label?: string
}

export interface ErrorStrategy {
  default_action: 'retry' | 'fallback' | 'abort' | 'continue'
  retry_config?: {
    max_retries: number
    backoff_ms: number
    backoff_multiplier: number
  }
  fallback_step_id?: string
}

export interface TestInvariant {
  name: string
  description: string
  type: string
  config: Record<string, unknown>
}

export interface WorkflowIR {
  id: string
  name: string
  description: string
  trigger: StepSpec
  steps: StepSpec[]
  edges: EdgeSpec[]
  error_strategy: ErrorStrategy
  success_criteria: TestInvariant[]
  metadata: Record<string, unknown>
  tags: string[]
}

export interface TestResult {
  test_name: string
  passed: boolean
  input_payload: Record<string, unknown>
  actual_output?: Record<string, unknown>
  expected_output?: Record<string, unknown>
  failure_reason?: string
  duration_ms: number
  checkpoints: Array<Record<string, unknown>>
  executed_at: string
}

export interface Iteration {
  id: string
  workflow_id: string
  version: number
  workflow_ir: WorkflowIR
  n8n_json: Record<string, unknown>
  rationale: string
  score?: number
  score_breakdown?: {
    correctness: number
    simplicity: number
    clarity: number
    robustness: number
  }
  test_results: TestResult[]
  created_at: string
}

export interface Workflow {
  id: string
  name: string
  description: string
  user_id?: string
  n8n_workflow_id?: string
  current_iteration_id?: string
  status: 'draft' | 'testing' | 'passing' | 'deployed'
  iterations: Iteration[]
  created_at: string
  updated_at: string
}

export interface SynthesizeRequest {
  prompt: string
  workflow_id?: string
  previous_iteration_id?: string
  auto_iterate?: boolean
  max_iterations?: number
}

export interface IterationSummary {
  iteration_number: number
  score: number
  tests_passed: number
  tests_total: number
  fixes_applied: number
  success: boolean
}

export interface SynthesizeResponse {
  workflow_id: string
  iteration_id: string
  iteration_version: number
  workflow_ir: WorkflowIR
  n8n_json: Record<string, unknown>
  rationale: string
  test_plan: Array<Record<string, unknown>>
  score?: number
  score_breakdown?: Record<string, number>
  // Auto-iteration fields
  auto_iterated?: boolean
  total_iterations?: number
  iteration_history?: IterationSummary[]
  n8n_workflow_id?: string
  n8n_workflow_url?: string
  webhook_url?: string
  webhook_path?: string
  success?: boolean
  stop_reason?: string
}

// ============================================================================
// Execution History Types
// ============================================================================

export type ExecutionStatus = 'waiting' | 'running' | 'success' | 'error' | 'unknown'
export type ExecutionMode = 'webhook' | 'manual' | 'trigger' | 'retry'

export interface ExecutionSummary {
  id: string
  status: ExecutionStatus
  started_at: string | null
  stopped_at: string | null
  finished_at: string | null
  mode: ExecutionMode | null
  workflow_id: string | null
  workflow_name: string | null
  duration_ms: number | null
  retry_of: string | null
  retry_success_id: string | null
}

export interface ExecutionDetail extends ExecutionSummary {
  data: Record<string, unknown> | null  // Node outputs and full execution data
}

export interface ExecutionsResponse {
  executions: ExecutionSummary[]
  workflow_id: string | null
  total_count: number
}

// ============================================================================
// Enhanced Test Results Types (for persistent display)
// ============================================================================

export interface TestRunResult {
  test_name: string
  passed: boolean
  failure_reason?: string
  duration_ms: number
  execution_mode: 'real' | 'simulated'
  webhook_url?: string
  input_payload?: Record<string, unknown>
  actual_output?: Record<string, unknown>
  expected_output?: Record<string, unknown>
}

export interface TestRunSummary {
  results: TestRunResult[]
  passed_count: number
  total_count: number
  all_passed: boolean
  real_execution_count: number
  simulated_execution_count: number
  webhook_url?: string
  executed_at: string
}

// ============================================================================
// Activation Types
// ============================================================================

export interface ActivateResponse {
  success: boolean
  active: boolean
  workflow_id: string
  message: string
}
