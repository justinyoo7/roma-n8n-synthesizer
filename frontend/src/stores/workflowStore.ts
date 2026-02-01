import { create } from 'zustand'
import type { 
  WorkflowIR, 
  Iteration, 
  SynthesizeResponse, 
  IterationSummary,
  ExecutionSummary,
  TestRunSummary,
} from '../types/workflow'

interface WorkflowState {
  // Current workflow state
  currentWorkflowId: string | null
  currentIterationId: string | null
  workflowIR: WorkflowIR | null
  n8nJson: Record<string, unknown> | null
  iterations: Iteration[]
  
  // UI state
  selectedNodeId: string | null
  isLoading: boolean
  error: string | null
  
  // Score
  score: number | null
  scoreBreakdown: Record<string, number> | null
  
  // Auto-iteration state
  autoIterated: boolean
  totalIterations: number
  iterationHistory: IterationSummary[]
  n8nWorkflowId: string | null
  n8nWorkflowUrl: string | null
  webhookUrl: string | null
  webhookPath: string | null
  success: boolean
  stopReason: string | null
  
  // Execution history state (NEW)
  executions: ExecutionSummary[]
  executionsLoading: boolean
  executionsError: string | null
  isPolling: boolean
  
  // Test results state (NEW)
  lastTestRun: TestRunSummary | null
  
  // Workflow active state (NEW)
  isActive: boolean
  
  // Actions
  setWorkflow: (response: SynthesizeResponse) => void
  setSelectedNode: (nodeId: string | null) => void
  setError: (error: string | null) => void
  addIteration: (iteration: Iteration) => void
  setExecutions: (executions: ExecutionSummary[]) => void
  setExecutionsLoading: (loading: boolean) => void
  setExecutionsError: (error: string | null) => void
  setPolling: (polling: boolean) => void
  setLastTestRun: (testRun: TestRunSummary | null) => void
  setIsActive: (active: boolean) => void
  setN8nWorkflowId: (id: string | null) => void
  setN8nWorkflowUrl: (url: string | null) => void
  setWebhookUrl: (url: string | null) => void
  reset: () => void
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  // Initial state
  currentWorkflowId: null,
  currentIterationId: null,
  workflowIR: null,
  n8nJson: null,
  iterations: [],
  selectedNodeId: null,
  isLoading: false,
  error: null,
  score: null,
  scoreBreakdown: null,
  // Auto-iteration state
  autoIterated: false,
  totalIterations: 1,
  iterationHistory: [],
  n8nWorkflowId: null,
  n8nWorkflowUrl: null,
  webhookUrl: null,
  webhookPath: null,
  success: true,
  stopReason: null,
  // Execution history state (NEW)
  executions: [],
  executionsLoading: false,
  executionsError: null,
  isPolling: false,
  // Test results state (NEW)
  lastTestRun: null,
  // Workflow active state (NEW)
  isActive: false,

  // Actions
  setWorkflow: (response) =>
    set({
      currentWorkflowId: response.workflow_id,
      currentIterationId: response.iteration_id,
      workflowIR: response.workflow_ir,
      n8nJson: response.n8n_json,
      score: response.score ?? null,
      scoreBreakdown: response.score_breakdown ?? null,
      error: null,
      isLoading: false,
      // Auto-iteration fields
      autoIterated: response.auto_iterated ?? false,
      totalIterations: response.total_iterations ?? 1,
      iterationHistory: response.iteration_history ?? [],
      n8nWorkflowId: response.n8n_workflow_id ?? null,
      n8nWorkflowUrl: response.n8n_workflow_url ?? null,
      webhookUrl: (response as SynthesizeResponse & { webhook_url?: string }).webhook_url ?? null,
      webhookPath: (response as SynthesizeResponse & { webhook_path?: string }).webhook_path ?? null,
      success: response.success ?? true,
      stopReason: response.stop_reason ?? null,
      // Reset executions on new workflow
      executions: [],
      lastTestRun: null,
      isActive: false,
    }),

  setSelectedNode: (nodeId) =>
    set({ selectedNodeId: nodeId }),

  setError: (error) =>
    set({ error }),

  addIteration: (iteration) =>
    set((state) => ({
      iterations: [...state.iterations, iteration],
      currentIterationId: iteration.id,
      workflowIR: iteration.workflow_ir,
      score: iteration.score ?? null,
      scoreBreakdown: iteration.score_breakdown ?? null,
    })),

  // Execution history actions (NEW)
  setExecutions: (executions) =>
    set({ executions, executionsError: null }),

  setExecutionsLoading: (loading) =>
    set({ executionsLoading: loading }),

  setExecutionsError: (error) =>
    set({ executionsError: error }),

  setPolling: (polling) =>
    set({ isPolling: polling }),

  // Test results actions (NEW)
  setLastTestRun: (testRun) =>
    set({ lastTestRun: testRun }),

  // Active state action (NEW)
  setIsActive: (active) =>
    set({ isActive: active }),

  // n8n state setters (NEW)
  setN8nWorkflowId: (id) =>
    set({ n8nWorkflowId: id }),

  setN8nWorkflowUrl: (url) =>
    set({ n8nWorkflowUrl: url }),

  setWebhookUrl: (url) =>
    set({ webhookUrl: url }),

  reset: () =>
    set({
      currentWorkflowId: null,
      currentIterationId: null,
      workflowIR: null,
      n8nJson: null,
      iterations: [],
      selectedNodeId: null,
      isLoading: false,
      error: null,
      score: null,
      scoreBreakdown: null,
      autoIterated: false,
      totalIterations: 1,
      iterationHistory: [],
      n8nWorkflowId: null,
      n8nWorkflowUrl: null,
      webhookUrl: null,
      webhookPath: null,
      success: true,
      stopReason: null,
      // Reset new state (NEW)
      executions: [],
      executionsLoading: false,
      executionsError: null,
      isPolling: false,
      lastTestRun: null,
      isActive: false,
    }),
}))
