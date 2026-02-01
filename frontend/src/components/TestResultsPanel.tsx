import { useState } from 'react'
import {
  TestTube,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Zap,
  Copy,
  X,
  AlertCircle,
} from 'lucide-react'
import { useWorkflowStore } from '../stores/workflowStore'
import type { TestRunResult } from '../types/workflow'

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

interface TestResultRowProps {
  result: TestRunResult
  isExpanded: boolean
  onToggle: () => void
}

function TestResultRow({ result, isExpanded, onToggle }: TestResultRowProps) {
  const [copied, setCopied] = useState(false)
  
  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  
  return (
    <div className="border-b border-zinc-800/50 last:border-b-0">
      {/* Row Header */}
      <button
        onClick={onToggle}
        className="w-full px-3 py-2.5 flex items-center gap-3 hover:bg-zinc-800/30 transition-colors text-left"
      >
        {/* Status Icon */}
        {result.passed ? (
          <CheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0" />
        ) : (
          <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
        )}
        
        {/* Test Name */}
        <span className="flex-1 text-sm text-zinc-200 truncate">
          {result.test_name}
        </span>
        
        {/* Duration & Mode */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-zinc-500 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {formatDuration(result.duration_ms)}
          </span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${
            result.execution_mode === 'real' 
              ? 'bg-blue-500/20 text-blue-400' 
              : 'bg-zinc-500/20 text-zinc-400'
          }`}>
            {result.execution_mode === 'real' ? '⚡' : '🔄'}
          </span>
        </div>
        
        {/* Expand Arrow */}
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-zinc-500 flex-shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-zinc-500 flex-shrink-0" />
        )}
      </button>
      
      {/* Expanded Detail */}
      {isExpanded && (
        <div className="px-3 pb-3 space-y-2">
          {/* Failure Reason */}
          {!result.passed && result.failure_reason && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-2">
              <div className="text-xs text-red-400 font-medium mb-1 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                Failure Reason
              </div>
              <p className="text-xs text-red-300">{result.failure_reason}</p>
            </div>
          )}
          
          {/* Input */}
          {result.input_payload && (
            <div className="bg-zinc-800/50 rounded-lg p-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-zinc-500">Input</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    copyToClipboard(JSON.stringify(result.input_payload, null, 2))
                  }}
                  className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                >
                  <Copy className="w-3 h-3" />
                  {copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <pre className="text-xs text-zinc-400 font-mono overflow-x-auto max-h-24 overflow-y-auto">
                {JSON.stringify(result.input_payload, null, 2)}
              </pre>
            </div>
          )}
          
          {/* Output */}
          {result.actual_output && (
            <div className="bg-zinc-800/50 rounded-lg p-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-zinc-500">Output</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    copyToClipboard(JSON.stringify(result.actual_output, null, 2))
                  }}
                  className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                >
                  <Copy className="w-3 h-3" />
                  Copy
                </button>
              </div>
              <pre className="text-xs text-emerald-400 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                {JSON.stringify(result.actual_output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface TestResultsPanelProps {
  onClose?: () => void
}

export default function TestResultsPanel({ onClose }: TestResultsPanelProps) {
  const { lastTestRun } = useWorkflowStore()
  const [expandedTest, setExpandedTest] = useState<string | null>(null)
  
  if (!lastTestRun) {
    return null
  }
  
  const { results, passed_count, total_count, all_passed, real_execution_count, simulated_execution_count } = lastTestRun
  const passRate = total_count > 0 ? Math.round((passed_count / total_count) * 100) : 0
  
  return (
    <div className="w-80 bg-zinc-900/95 backdrop-blur-sm border border-zinc-800 rounded-xl shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TestTube className={`w-4 h-4 ${all_passed ? 'text-emerald-400' : 'text-amber-400'}`} />
          <span className="font-medium text-zinc-200">Test Results</span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-800 rounded transition-colors"
          >
            <X className="w-4 h-4 text-zinc-500" />
          </button>
        )}
      </div>
      
      {/* Summary */}
      <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-800/30">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-zinc-400">Pass Rate</span>
          <span className={`text-lg font-bold ${
            all_passed ? 'text-emerald-400' : passRate >= 50 ? 'text-amber-400' : 'text-red-400'
          }`}>
            {passRate}%
          </span>
        </div>
        
        {/* Progress bar */}
        <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
          <div 
            className={`h-full rounded-full transition-all duration-500 ${
              all_passed ? 'bg-emerald-500' : 'bg-amber-500'
            }`}
            style={{ width: `${passRate}%` }}
          />
        </div>
        
        {/* Stats */}
        <div className="flex items-center justify-between mt-3 text-xs">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1 text-emerald-400">
              <CheckCircle className="w-3 h-3" />
              {passed_count} passed
            </span>
            <span className="flex items-center gap-1 text-red-400">
              <XCircle className="w-3 h-3" />
              {total_count - passed_count} failed
            </span>
          </div>
        </div>
        
        {/* Execution Mode Stats */}
        <div className="flex items-center gap-2 mt-2">
          {real_execution_count > 0 && (
            <span className="text-xs px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded flex items-center gap-1">
              <Zap className="w-3 h-3" />
              {real_execution_count} real
            </span>
          )}
          {simulated_execution_count > 0 && (
            <span className="text-xs px-2 py-0.5 bg-zinc-500/20 text-zinc-400 rounded">
              {simulated_execution_count} simulated
            </span>
          )}
        </div>
      </div>
      
      {/* Test List */}
      <div className="max-h-80 overflow-y-auto">
        {results.map((result, index) => (
          <TestResultRow
            key={`${result.test_name}-${index}`}
            result={result}
            isExpanded={expandedTest === `${result.test_name}-${index}`}
            onToggle={() => setExpandedTest(
              expandedTest === `${result.test_name}-${index}` 
                ? null 
                : `${result.test_name}-${index}`
            )}
          />
        ))}
      </div>
      
      {/* Footer */}
      <div className="px-4 py-2 border-t border-zinc-800 bg-zinc-800/30">
        <p className="text-xs text-zinc-500 text-center">
          Tested at {new Date(lastTestRun.executed_at).toLocaleTimeString()}
        </p>
      </div>
    </div>
  )
}
