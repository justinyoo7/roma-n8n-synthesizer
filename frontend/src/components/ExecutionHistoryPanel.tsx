import { useEffect, useCallback, useState } from 'react'
import {
  History,
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Play,
} from 'lucide-react'
import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../lib/api'
import type { ExecutionSummary, ExecutionStatus } from '../types/workflow'

// Status color and icon mapping
const STATUS_CONFIG: Record<ExecutionStatus, { color: string; bgColor: string; icon: React.ComponentType<{ className?: string }> }> = {
  success: { color: 'text-emerald-400', bgColor: 'bg-emerald-500/20', icon: CheckCircle },
  error: { color: 'text-red-400', bgColor: 'bg-red-500/20', icon: XCircle },
  running: { color: 'text-amber-400', bgColor: 'bg-amber-500/20', icon: Loader2 },
  waiting: { color: 'text-blue-400', bgColor: 'bg-blue-500/20', icon: Clock },
  unknown: { color: 'text-zinc-400', bgColor: 'bg-zinc-500/20', icon: AlertCircle },
}

function formatDuration(ms: number | null): string {
  if (ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

function formatTime(isoString: string | null): string {
  if (!isoString) return '-'
  try {
    const date = new Date(isoString)
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return '-'
  }
}

function formatDate(isoString: string | null): string {
  if (!isoString) return '-'
  try {
    const date = new Date(isoString)
    const today = new Date()
    const isToday = date.toDateString() === today.toDateString()
    
    if (isToday) return 'Today'
    
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
    
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return '-'
  }
}

interface ExecutionRowProps {
  execution: ExecutionSummary
  workflowId: string
  isExpanded: boolean
  onToggle: () => void
}

function ExecutionRow({ execution, workflowId, isExpanded, onToggle }: ExecutionRowProps) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  
  const config = STATUS_CONFIG[execution.status as ExecutionStatus] || STATUS_CONFIG.unknown
  const StatusIcon = config.icon
  
  // Load execution detail when expanded
  useEffect(() => {
    if (isExpanded && !detail && !loadingDetail) {
      setLoadingDetail(true)
      api.getExecutionDetail(workflowId, execution.id)
        .then(data => setDetail(data.data))
        .catch(() => setDetail(null))
        .finally(() => setLoadingDetail(false))
    }
  }, [isExpanded, detail, loadingDetail, workflowId, execution.id])
  
  return (
    <div className="border-b border-zinc-800/50 last:border-b-0">
      {/* Row Header */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-zinc-800/30 transition-colors text-left"
      >
        {/* Status Icon */}
        <div className={`p-1.5 rounded-lg ${config.bgColor}`}>
          <StatusIcon className={`w-4 h-4 ${config.color} ${execution.status === 'running' ? 'animate-spin' : ''}`} />
        </div>
        
        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-zinc-200">
              #{execution.id}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${config.bgColor} ${config.color}`}>
              {execution.status}
            </span>
            {execution.mode && (
              <span className="text-xs text-zinc-500">
                via {execution.mode}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-zinc-500 mt-0.5">
            <span>{formatDate(execution.started_at)} {formatTime(execution.started_at)}</span>
            {execution.duration_ms !== null && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatDuration(execution.duration_ms)}
              </span>
            )}
          </div>
        </div>
        
        {/* Expand Arrow */}
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-zinc-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-zinc-500" />
        )}
      </button>
      
      {/* Expanded Detail */}
      {isExpanded && (
        <div className="px-4 pb-3 pt-1">
          <div className="bg-zinc-800/50 rounded-lg p-3">
            {loadingDetail ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="w-5 h-5 text-zinc-500 animate-spin" />
              </div>
            ) : detail ? (
              <pre className="text-xs text-zinc-400 font-mono overflow-x-auto max-h-48 overflow-y-auto">
                {JSON.stringify(detail, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-zinc-500 text-center py-2">
                No execution data available
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

interface ExecutionHistoryPanelProps {
  isCollapsed?: boolean
  onToggleCollapse?: () => void
}

export default function ExecutionHistoryPanel({ 
  isCollapsed = false, 
  onToggleCollapse 
}: ExecutionHistoryPanelProps) {
  const {
    n8nWorkflowId,
    executions,
    executionsLoading,
    executionsError,
    isPolling,
    setExecutions,
    setExecutionsLoading,
    setExecutionsError,
    setPolling,
  } = useWorkflowStore()
  
  const [expandedId, setExpandedId] = useState<string | null>(null)
  
  // Fetch executions
  const fetchExecutions = useCallback(async () => {
    if (!n8nWorkflowId) return
    
    setExecutionsLoading(true)
    try {
      const response = await api.getExecutions(n8nWorkflowId, { limit: 20 })
      setExecutions(response.executions)
    } catch (err) {
      setExecutionsError(err instanceof Error ? err.message : 'Failed to fetch executions')
    } finally {
      setExecutionsLoading(false)
    }
  }, [n8nWorkflowId, setExecutions, setExecutionsLoading, setExecutionsError])
  
  // Initial fetch
  useEffect(() => {
    if (n8nWorkflowId) {
      fetchExecutions()
    }
  }, [n8nWorkflowId, fetchExecutions])
  
  // Polling
  useEffect(() => {
    if (!isPolling || !n8nWorkflowId) return
    
    const interval = setInterval(fetchExecutions, 5000)
    return () => clearInterval(interval)
  }, [isPolling, n8nWorkflowId, fetchExecutions])
  
  // Count by status
  const successCount = executions.filter(e => e.status === 'success').length
  const errorCount = executions.filter(e => e.status === 'error').length
  const runningCount = executions.filter(e => e.status === 'running').length
  
  if (!n8nWorkflowId) {
    return null
  }
  
  return (
    <div className={`bg-zinc-900/95 backdrop-blur-sm border-t border-zinc-800 transition-all duration-300
                    ${isCollapsed ? 'h-12' : 'h-72'}`}>
      {/* Header */}
      <button
        onClick={onToggleCollapse}
        className="w-full px-4 h-12 flex items-center justify-between hover:bg-zinc-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <History className="w-4 h-4 text-zinc-400" />
          <span className="text-sm font-medium text-zinc-200">
            Execution History
          </span>
          
          {/* Quick Stats */}
          <div className="flex items-center gap-2 ml-2">
            {runningCount > 0 && (
              <span className="flex items-center gap-1 text-xs text-amber-400">
                <Loader2 className="w-3 h-3 animate-spin" />
                {runningCount}
              </span>
            )}
            {successCount > 0 && (
              <span className="flex items-center gap-1 text-xs text-emerald-400">
                <CheckCircle className="w-3 h-3" />
                {successCount}
              </span>
            )}
            {errorCount > 0 && (
              <span className="flex items-center gap-1 text-xs text-red-400">
                <XCircle className="w-3 h-3" />
                {errorCount}
              </span>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Auto-refresh toggle */}
          <button
            onClick={(e) => {
              e.stopPropagation()
              setPolling(!isPolling)
            }}
            className={`px-2 py-1 text-xs rounded flex items-center gap-1 transition-colors
                       ${isPolling 
                         ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' 
                         : 'bg-zinc-800 text-zinc-400 hover:text-zinc-300'}`}
          >
            <RefreshCw className={`w-3 h-3 ${isPolling ? 'animate-spin' : ''}`} />
            Auto
          </button>
          
          {/* Manual refresh */}
          <button
            onClick={(e) => {
              e.stopPropagation()
              fetchExecutions()
            }}
            disabled={executionsLoading}
            className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-300 
                       transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${executionsLoading ? 'animate-spin' : ''}`} />
          </button>
          
          {/* Collapse icon */}
          {isCollapsed ? (
            <ChevronUp className="w-4 h-4 text-zinc-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-zinc-500" />
          )}
        </div>
      </button>
      
      {/* Content */}
      {!isCollapsed && (
        <div className="h-[calc(100%-48px)] overflow-y-auto">
          {executionsError ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
                <p className="text-sm text-red-400">{executionsError}</p>
                <button
                  onClick={fetchExecutions}
                  className="mt-2 text-xs text-zinc-400 hover:text-zinc-300"
                >
                  Try again
                </button>
              </div>
            </div>
          ) : executions.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <Play className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                <p className="text-sm text-zinc-500">No executions yet</p>
                <p className="text-xs text-zinc-600 mt-1">
                  Test your workflow to see executions here
                </p>
              </div>
            </div>
          ) : (
            <div>
              {executions.map((execution) => (
                <ExecutionRow
                  key={execution.id}
                  execution={execution}
                  workflowId={n8nWorkflowId}
                  isExpanded={expandedId === execution.id}
                  onToggle={() => setExpandedId(expandedId === execution.id ? null : execution.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
