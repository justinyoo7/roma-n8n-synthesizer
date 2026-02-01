import { useCallback, useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Node,
  Edge,
  MarkerType,
  NodeTypes,
  EdgeTypes,
  useReactFlow,
  ReactFlowProvider,
  BaseEdge,
  getSmoothStepPath,
  EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  ArrowLeft,
  Download,
  Loader2,
  Upload,
  CheckCircle,
  AlertCircle,
  ZoomIn,
  ZoomOut,
  Maximize2,
  LayoutGrid,
  X,
  Code,
  Info,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Play,
  RotateCw,
  TestTube,
  Wrench,
  Target,
  Sparkles,
  XCircle,
  Zap,
  Copy,
  Send,
  Terminal,
} from 'lucide-react'

import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../lib/api'
import WorkflowNode from '../components/WorkflowNode'
import ExecutionHistoryPanel from '../components/ExecutionHistoryPanel'
import TestResultsPanel from '../components/TestResultsPanel'
import type { StepSpec, IterationSummary, TestRunSummary } from '../types/workflow'

// Custom Animated Edge with flowing particles
function AnimatedFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
}: EdgeProps) {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 16,
  })

  // Generate unique IDs for this edge's gradients and animations
  const gradientId = `flow-gradient-${id}`
  const filterId = `glow-${id}`
  const particleId1 = `particle-${id}-1`
  const particleId2 = `particle-${id}-2`
  const particleId3 = `particle-${id}-3`

  return (
    <>
      {/* SVG Definitions for gradients and filters */}
      <defs>
        {/* Animated gradient for the edge */}
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.3">
            <animate
              attributeName="stopColor"
              values="#f59e0b;#f97316;#f59e0b"
              dur="2s"
              repeatCount="indefinite"
            />
          </stop>
          <stop offset="50%" stopColor="#f97316" stopOpacity="0.6">
            <animate
              attributeName="offset"
              values="0.3;0.5;0.7;0.5;0.3"
              dur="3s"
              repeatCount="indefinite"
            />
          </stop>
          <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.3">
            <animate
              attributeName="stopColor"
              values="#f59e0b;#f97316;#f59e0b"
              dur="2s"
              repeatCount="indefinite"
            />
          </stop>
        </linearGradient>
        
        {/* Glow filter */}
        <filter id={filterId} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
          <feMerge>
            <feMergeNode in="coloredBlur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>
      
      {/* Base edge with gradient */}
      <BaseEdge 
        path={edgePath} 
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: `url(#${gradientId})`,
          strokeWidth: 2,
        }}
      />
      
      {/* Animated flowing particles */}
      <circle r="4" fill="#f59e0b" filter={`url(#${filterId})`}>
        <animateMotion
          id={particleId1}
          dur="2s"
          repeatCount="indefinite"
          path={edgePath}
        />
        <animate
          attributeName="opacity"
          values="0;1;1;0"
          dur="2s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="r"
          values="2;4;3;2"
          dur="2s"
          repeatCount="indefinite"
        />
      </circle>
      
      {/* Second particle with offset timing */}
      <circle r="3" fill="#fb923c" filter={`url(#${filterId})`}>
        <animateMotion
          id={particleId2}
          dur="2s"
          repeatCount="indefinite"
          path={edgePath}
          begin="0.7s"
        />
        <animate
          attributeName="opacity"
          values="0;0.8;0.8;0"
          dur="2s"
          repeatCount="indefinite"
          begin="0.7s"
        />
      </circle>
      
      {/* Third particle with different offset */}
      <circle r="2.5" fill="#fbbf24" filter={`url(#${filterId})`}>
        <animateMotion
          id={particleId3}
          dur="2s"
          repeatCount="indefinite"
          path={edgePath}
          begin="1.4s"
        />
        <animate
          attributeName="opacity"
          values="0;0.6;0.6;0"
          dur="2s"
          repeatCount="indefinite"
          begin="1.4s"
        />
      </circle>
    </>
  )
}

// Edge types registry
const edgeTypes: EdgeTypes = {
  animatedFlow: AnimatedFlowEdge,
}

// Test Progress Modal
function TestProgressModal({ 
  isVisible, 
  currentTest, 
  totalTests,
  passedTests,
  failedTests,
}: { 
  isVisible: boolean
  currentTest: number
  totalTests: number
  passedTests: number
  failedTests: number
  status: 'running' | 'complete'
}) {
  if (!isVisible) return null
  
  const progress = totalTests > 0 ? (currentTest / totalTests) * 100 : 0
  
  return (
    <div className="fixed inset-0 bg-zinc-950/80 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl
                      animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-center gap-3 mb-6">
          <div className="p-3 rounded-xl bg-amber-500/10">
            <TestTube className="w-6 h-6 text-amber-400 animate-pulse" />
          </div>
          <h3 className="text-xl font-semibold text-zinc-100">Running Tests</h3>
        </div>
        
        {/* Progress Bar */}
        <div className="mb-6">
          <div className="flex justify-between text-sm text-zinc-400 mb-2">
            <span>Test {currentTest} of {totalTests}</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
            <div 
              className="h-full bg-gradient-to-r from-amber-500 to-orange-500 rounded-full
                         transition-all duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
        
        {/* Animated Test Results Grid */}
        <div className="bg-zinc-800/50 rounded-xl p-4 mb-6">
          <div className="grid grid-cols-8 gap-2">
            {Array.from({ length: totalTests }).map((_, idx) => {
              const isPassed = idx < passedTests
              const isFailed = idx >= passedTests && idx < passedTests + failedTests
              const isRunning = idx === currentTest - 1
              
              const isCompleted = idx < currentTest
              return (
                <div
                  key={idx}
                  className={`w-6 h-6 rounded flex items-center justify-center transition-all duration-300
                             ${isPassed ? 'bg-emerald-500/20 scale-100' : 
                               isFailed ? 'bg-red-500/20 scale-100' : 
                               isRunning ? 'bg-amber-500/30 scale-110' : 
                               'bg-zinc-700/50 scale-90'}`}
                  style={{ 
                    animationDelay: `${idx * 50}ms`,
                    transform: isRunning ? 'scale(1.1)' : 'scale(1)',
                  }}
                >
                  {isPassed ? (
                    <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                  ) : isFailed ? (
                    <XCircle className="w-3.5 h-3.5 text-red-400" />
                  ) : isRunning ? (
                    <div className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
                  ) : isCompleted ? (
                    <div className="w-1.5 h-1.5 bg-zinc-400 rounded-full" />
                  ) : (
                    <div className="w-1.5 h-1.5 bg-zinc-500 rounded-full" />
                  )}
                </div>
              )
            })}
          </div>
        </div>
        
        {/* Stats */}
        <div className="flex justify-center gap-6 text-sm">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-emerald-400 font-medium">{passedTests} passed</span>
          </div>
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-red-400" />
            <span className="text-red-400 font-medium">{failedTests} failed</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// Iteration Progress Modal
function IterationProgressModal({ 
  isVisible, 
  iteration,
  phaseIndex,
  testResults,
  currentScore,
}: { 
  isVisible: boolean
  iteration: number
  phase: string
  phaseIndex: number
  testResults: { passed: number; total: number } | null
  currentScore: number
}) {
  if (!isVisible) return null
  
  const phases = [
    { id: 'analyze', label: 'Analyzing Failures', icon: Target, color: 'text-cyan-400' },
    { id: 'fix', label: 'Generating Fixes', icon: Wrench, color: 'text-orange-400' },
    { id: 'apply', label: 'Applying Changes', icon: Code, color: 'text-purple-400' },
    { id: 'push', label: 'Pushing to n8n', icon: Upload, color: 'text-blue-400' },
    { id: 'test', label: 'Running Tests', icon: TestTube, color: 'text-amber-400' },
    { id: 'score', label: 'Calculating Score', icon: Sparkles, color: 'text-emerald-400' },
  ]
  
  const currentPhase = phases[phaseIndex] || phases[0]
  const PhaseIcon = currentPhase.icon
  
  return (
    <div className="fixed inset-0 bg-zinc-950/80 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl
                      animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500/10 to-orange-500/10 
                          border border-amber-500/20 rounded-full mb-4">
            <RotateCw className="w-4 h-4 text-amber-500 animate-spin" />
            <span className="text-sm font-medium text-amber-400">Iterating</span>
          </div>
          <h3 className="text-xl font-semibold text-zinc-100">Iteration {iteration}</h3>
        </div>
        
        {/* Current Phase */}
        <div className="flex items-center justify-center gap-3 mb-6">
          <div className={`p-3 rounded-xl bg-zinc-800 ${currentPhase.color}`}>
            <PhaseIcon className="w-6 h-6 animate-pulse" />
          </div>
          <span className="text-lg font-medium text-zinc-200">{currentPhase.label}</span>
        </div>
        
        {/* Phase Progress */}
        <div className="flex justify-center gap-2 mb-8">
          {phases.map((p, idx) => (
            <div
              key={p.id}
              className={`w-2.5 h-2.5 rounded-full transition-all duration-500 ${
                idx < phaseIndex 
                  ? 'bg-emerald-500' 
                  : idx === phaseIndex 
                    ? 'bg-amber-500 animate-pulse scale-125' 
                    : 'bg-zinc-700'
              }`}
            />
          ))}
        </div>
        
        {/* Test Results (if available) */}
        {testResults && testResults.total > 0 && (
          <div className="bg-zinc-800/50 rounded-xl p-4 mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-zinc-400">Test Results</span>
              <span className={`text-sm font-medium ${
                testResults.passed === testResults.total 
                  ? 'text-emerald-400' 
                  : 'text-amber-400'
              }`}>
                {testResults.passed}/{testResults.total}
              </span>
            </div>
            <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all duration-500 ${
                  testResults.passed === testResults.total 
                    ? 'bg-emerald-500' 
                    : 'bg-amber-500'
                }`}
                style={{ width: `${(testResults.passed / testResults.total) * 100}%` }}
              />
            </div>
          </div>
        )}
        
        {/* Score */}
        {currentScore > 0 && (
          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-4 py-2 bg-zinc-800 rounded-lg">
              <span className="text-sm text-zinc-400">Score:</span>
              <span className={`text-xl font-bold ${
                currentScore >= 80 ? 'text-emerald-400' : 
                currentScore >= 60 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {currentScore}
              </span>
            </div>
          </div>
        )}
        
        <p className="text-center text-sm text-zinc-500 mt-6 animate-pulse">
          Improving your workflow...
        </p>
      </div>
    </div>
  )
}

// Custom node types
const nodeTypes: NodeTypes = {
  workflowNode: WorkflowNode as NodeTypes[string],
}

// Custom Controls Component
function FlowControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  
  return (
    <div className="absolute bottom-6 left-6 flex flex-col gap-1 z-10">
      <button
        onClick={() => zoomIn()}
        className="p-2.5 bg-zinc-800/90 backdrop-blur-sm border border-zinc-700/50 
                   rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/90
                   transition-all duration-200 shadow-lg"
        title="Zoom In"
      >
        <ZoomIn className="w-4 h-4" />
      </button>
      <button
        onClick={() => zoomOut()}
        className="p-2.5 bg-zinc-800/90 backdrop-blur-sm border border-zinc-700/50 
                   rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/90
                   transition-all duration-200 shadow-lg"
        title="Zoom Out"
      >
        <ZoomOut className="w-4 h-4" />
      </button>
      <button
        onClick={() => fitView({ padding: 0.2, duration: 300 })}
        className="p-2.5 bg-zinc-800/90 backdrop-blur-sm border border-zinc-700/50 
                   rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/90
                   transition-all duration-200 shadow-lg"
        title="Fit to View"
      >
        <Maximize2 className="w-4 h-4" />
      </button>
    </div>
  )
}

// Node Detail Panel
function NodePanel({ step, onClose }: { step: StepSpec; onClose: () => void }) {
  return (
    <div className="absolute right-6 top-6 bottom-6 w-80 bg-zinc-900/95 backdrop-blur-sm 
                    border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden z-20
                    animate-in slide-in-from-right-4 duration-200">
      {/* Header */}
      <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
        <h3 className="font-semibold text-zinc-100 truncate pr-4">{step.name}</h3>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-zinc-300
                     transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      
      <div className="p-5 space-y-5 overflow-y-auto max-h-[calc(100%-60px)]">
        {/* Type & Node Info */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-zinc-500 uppercase tracking-wider">
            <Info className="w-3.5 h-3.5" />
            Node Info
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-800/50 rounded-lg px-3 py-2">
              <div className="text-[10px] text-zinc-500 uppercase">Type</div>
              <div className="text-sm text-zinc-200 capitalize">{step.type}</div>
            </div>
            <div className="bg-zinc-800/50 rounded-lg px-3 py-2">
              <div className="text-[10px] text-zinc-500 uppercase">n8n Node</div>
              <div className="text-sm text-zinc-200 font-mono text-xs truncate">
                {step.n8n_node_type.split('.').pop()}
              </div>
            </div>
          </div>
          {step.description && (
            <p className="text-sm text-zinc-400 leading-relaxed">{step.description}</p>
          )}
        </div>

        {/* Agent Config */}
        {step.agent && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs text-zinc-500 uppercase tracking-wider">
              <LayoutGrid className="w-3.5 h-3.5" />
              Agent Configuration
            </div>
            <div className="bg-zinc-800/50 rounded-lg p-3 space-y-2">
              <div>
                <div className="text-[10px] text-zinc-500 uppercase">Name</div>
                <div className="text-sm text-zinc-200">{step.agent.name}</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase">Role</div>
                <div className="text-sm text-zinc-400">{step.agent.role}</div>
              </div>
              {step.agent.tools_allowed.length > 0 && (
                <div>
                  <div className="text-[10px] text-zinc-500 uppercase mb-1">Tools</div>
                  <div className="flex flex-wrap gap-1">
                    {step.agent.tools_allowed.map((tool) => (
                      <span
                        key={tool}
                        className="px-2 py-0.5 bg-violet-500/10 text-violet-400 
                                   text-[10px] rounded-full border border-violet-500/20"
                      >
                        {tool}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Parameters */}
        {Object.keys(step.parameters).length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs text-zinc-500 uppercase tracking-wider">
              <Code className="w-3.5 h-3.5" />
              Parameters
            </div>
            <div className="bg-zinc-800/50 rounded-lg p-3 overflow-x-auto">
              <pre className="text-xs text-zinc-400 font-mono whitespace-pre-wrap">
                {JSON.stringify(step.parameters, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Score Badge
function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null
  
  const getScoreColor = () => {
    if (score >= 85) return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
    if (score >= 70) return 'bg-amber-500/20 text-amber-400 border-amber-500/30'
    return 'bg-red-500/20 text-red-400 border-red-500/30'
  }
  
  return (
    <div className={`px-3 py-1.5 rounded-lg border text-sm font-medium ${getScoreColor()}`}>
      Score: {score}
    </div>
  )
}

// Iteration History Panel
function IterationHistoryPanel({ 
  iterations, 
  totalIterations,
  success,
  stopReason,
}: { 
  iterations: IterationSummary[]
  totalIterations: number
  success: boolean
  stopReason: string | null
}) {
  const [isExpanded, setIsExpanded] = useState(false)
  
  if (iterations.length === 0) return null
  
  return (
    <div className="absolute bottom-6 right-6 z-20">
      <div className="bg-zinc-900/95 backdrop-blur-sm border border-zinc-800 rounded-xl shadow-2xl
                      overflow-hidden min-w-[280px]">
        {/* Header - always visible */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full px-4 py-3 flex items-center justify-between hover:bg-zinc-800/50 transition-colors"
        >
          <div className="flex items-center gap-3">
            <RefreshCw className={`w-4 h-4 ${success ? 'text-emerald-400' : 'text-amber-400'}`} />
            <span className="text-sm font-medium text-zinc-200">
              {totalIterations} iteration{totalIterations > 1 ? 's' : ''}
            </span>
            {success ? (
              <span className="px-2 py-0.5 text-xs bg-emerald-500/20 text-emerald-400 rounded-full">
                Success
              </span>
            ) : (
              <span className="px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded-full">
                {stopReason || 'Stopped'}
              </span>
            )}
          </div>
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-zinc-500" />
          ) : (
            <ChevronUp className="w-4 h-4 text-zinc-500" />
          )}
        </button>
        
        {/* Expanded content */}
        {isExpanded && (
          <div className="border-t border-zinc-800 max-h-60 overflow-y-auto">
            {iterations.map((iter, idx) => (
              <div
                key={idx}
                className="px-4 py-3 border-b border-zinc-800/50 last:border-b-0"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-zinc-500">Iteration {iter.iteration_number}</span>
                  <span className={`text-xs font-medium ${
                    iter.success ? 'text-emerald-400' : 'text-zinc-400'
                  }`}>
                    Score: {iter.score}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-zinc-400">
                  <span>
                    Tests: {iter.tests_passed}/{iter.tests_total}
                  </span>
                  {iter.fixes_applied > 0 && (
                    <span className="text-amber-400">
                      {iter.fixes_applied} fix{iter.fixes_applied > 1 ? 'es' : ''}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Enhanced Try It Panel with presets, cURL export, and response time
function TryItPanel({ 
  webhookUrl, 
  onClose 
}: { 
  webhookUrl: string
  onClose: () => void 
}) {
  const [testInput, setTestInput] = useState('{\n  "message": "Hello, this is a test!"\n}')
  const [testResponse, setTestResponse] = useState<string | null>(null)
  const [responseTime, setResponseTime] = useState<number | null>(null)
  const [isTestingManual, setIsTestingManual] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)
  const [copiedCurl, setCopiedCurl] = useState(false)
  
  // Preset payloads based on workflow type
  const presets = [
    { 
      label: 'Simple Message', 
      payload: '{\n  "message": "Hello, this is a test!"\n}' 
    },
    { 
      label: 'Lead Data', 
      payload: '{\n  "name": "John Doe",\n  "company": "Acme Inc",\n  "email": "john@acme.com",\n  "title": "CTO"\n}' 
    },
    { 
      label: 'Support Ticket', 
      payload: '{\n  "subject": "Login Issue",\n  "body": "I cannot log into my account",\n  "priority": "high",\n  "customer_id": "12345"\n}' 
    },
    { 
      label: 'Product Data', 
      payload: '{\n  "product_name": "Widget Pro",\n  "price": 99.99,\n  "quantity": 5,\n  "category": "electronics"\n}' 
    },
  ]
  
  // Generate cURL command
  const generateCurl = () => {
    try {
      const payload = JSON.parse(testInput)
      return `curl -X POST "${webhookUrl}" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(payload)}'`
    } catch {
      return `curl -X POST "${webhookUrl}" \\
  -H "Content-Type: application/json" \\
  -d '${testInput.replace(/\n/g, '').replace(/'/g, "\\'")}'`
    }
  }
  
  const copyCurl = () => {
    navigator.clipboard.writeText(generateCurl())
    setCopiedCurl(true)
    setTimeout(() => setCopiedCurl(false), 2000)
  }
  
  const handleManualTest = async () => {
    setIsTestingManual(true)
    setTestError(null)
    setTestResponse(null)
    setResponseTime(null)
    
    try {
      let parsedInput: Record<string, unknown>
      try {
        parsedInput = JSON.parse(testInput)
      } catch {
        setTestError('Invalid JSON input. Please check your syntax.')
        setIsTestingManual(false)
        return
      }
      
      const startTime = Date.now()
      const result = await api.proxyWebhook(webhookUrl, parsedInput)
      const endTime = Date.now()
      
      setResponseTime(endTime - startTime)
      
      if (result.success) {
        setTestResponse(JSON.stringify(result.body, null, 2))
      } else {
        setTestError(result.error || `Request failed with status ${result.status_code}`)
      }
    } catch (err) {
      setTestError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setIsTestingManual(false)
    }
  }
  
  return (
    <div className="absolute top-20 left-4 z-40 w-[440px]
                    bg-zinc-900 border border-zinc-700/50 
                    rounded-xl shadow-2xl
                    animate-in fade-in slide-in-from-left-2 duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-violet-400" />
          <span className="font-medium text-zinc-200">Try It</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={copyCurl}
            className="px-2 py-1 text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-400 
                     rounded flex items-center gap-1 transition-colors"
            title="Copy as cURL"
          >
            <Code className="w-3 h-3" />
            {copiedCurl ? 'Copied!' : 'cURL'}
          </button>
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-800 rounded transition-colors"
          >
            <X className="w-4 h-4 text-zinc-500" />
          </button>
        </div>
      </div>
      
      {/* Webhook URL */}
      <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-800/30">
        <div className="flex items-center justify-between">
          <div className="text-xs text-zinc-500 mb-1">POST</div>
          <button
            onClick={() => navigator.clipboard.writeText(webhookUrl)}
            className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
          >
            <Copy className="w-3 h-3" />
          </button>
        </div>
        <code className="text-xs text-violet-400 break-all font-mono">
          {webhookUrl}
        </code>
      </div>
      
      {/* Preset Buttons */}
      <div className="px-4 py-2 border-b border-zinc-800 flex flex-wrap gap-2">
        {presets.map((preset) => (
          <button
            key={preset.label}
            onClick={() => setTestInput(preset.payload)}
            className="px-2 py-1 text-xs bg-zinc-800/50 hover:bg-zinc-700/50 
                     text-zinc-400 hover:text-zinc-300 rounded border border-zinc-700/50
                     transition-colors"
          >
            {preset.label}
          </button>
        ))}
      </div>
      
      {/* Input */}
      <div className="px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-zinc-500">Request Body (JSON)</span>
          <button
            onClick={() => {
              try {
                const formatted = JSON.stringify(JSON.parse(testInput), null, 2)
                setTestInput(formatted)
              } catch {
                // Invalid JSON, can't format
              }
            }}
            className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
          >
            <LayoutGrid className="w-3 h-3" />
            Format
          </button>
        </div>
        <textarea
          value={testInput}
          onChange={(e) => setTestInput(e.target.value)}
          className="w-full h-36 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg
                   text-sm font-mono text-zinc-300
                   focus:outline-none focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30
                   resize-none"
          placeholder='{"message": "Hello!"}'
          spellCheck={false}
        />
        
        {testError && (
          <div className="mt-2 text-xs text-red-400 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            {testError}
          </div>
        )}
        
        <button
          onClick={handleManualTest}
          disabled={isTestingManual}
          className="mt-3 w-full px-4 py-2 flex items-center justify-center gap-2
                   bg-violet-500 hover:bg-violet-400 text-white text-sm font-medium
                   rounded-lg transition-all duration-200
                   disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isTestingManual ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Sending...
            </>
          ) : (
            <>
              <Send className="w-4 h-4" />
              Send Request
            </>
          )}
        </button>
      </div>
      
      {/* Response */}
      {(testResponse || responseTime !== null) && (
        <div className="px-4 py-3 max-h-64 overflow-auto">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-500">Response</span>
              {responseTime !== null && (
                <span className="text-xs px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
                  {responseTime}ms
                </span>
              )}
            </div>
            {testResponse && (
              <button
                onClick={() => navigator.clipboard.writeText(testResponse)}
                className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
              >
                <Copy className="w-3 h-3" />
                Copy
              </button>
            )}
          </div>
          {testResponse && (
            <pre className="text-xs font-mono text-emerald-400 bg-zinc-800/50 
                          px-3 py-2 rounded-lg overflow-x-auto whitespace-pre-wrap">
              {testResponse}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function WorkflowPageContent() {
  const { id: _workflowId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { fitView } = useReactFlow()
  
  const {
    workflowIR,
    n8nJson,
    selectedNodeId,
    setSelectedNode,
    score,
    // Auto-iteration state
    autoIterated,
    totalIterations,
    iterationHistory,
    n8nWorkflowUrl: storeN8nUrl,
    n8nWorkflowId,
    webhookUrl,
    success,
    stopReason,
    // Test results
    lastTestRun,
    setLastTestRun,
    setN8nWorkflowId,
    setN8nWorkflowUrl,
    setWebhookUrl,
  } = useWorkflowStore()

  // Push to n8n state
  const [isPushing, setIsPushing] = useState(false)
  const [n8nUrl, setN8nUrl] = useState<string | null>(storeN8nUrl)
  const [pushError, setPushError] = useState<string | null>(null)
  
  // Test and iterate state
  const [isTesting, setIsTesting] = useState(false)
  const [isIterating, setIsIterating] = useState(false)
  const [testResults, setTestResults] = useState<{
    passed: number
    total: number
    allPassed: boolean
    realExecutions?: number
    simulatedExecutions?: number
    webhookUrl?: string
  } | null>(null)
  
  // Animated progress state
  const [testProgress, setTestProgress] = useState({
    currentTest: 0,
    totalTests: 10,
    passedTests: 0,
    failedTests: 0,
  })
  const [iterationProgress, setIterationProgress] = useState({
    iteration: 1,
    phase: 'analyze',
    phaseIndex: 0,
    testResults: null as { passed: number; total: number } | null,
    score: 0,
  })
  const testAnimationRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const iterationAnimationRef = useRef<ReturnType<typeof setInterval> | null>(null)
  
  // Manual test panel state
  const [showTryIt, setShowTryIt] = useState(false)
  
  // Execution history panel state
  const [executionHistoryCollapsed, setExecutionHistoryCollapsed] = useState(true)
  
  // Test results panel state
  const [showTestResults, setShowTestResults] = useState(false)
  
  // Sync storeN8nUrl to local state
  useEffect(() => {
    if (storeN8nUrl) {
      setN8nUrl(storeN8nUrl)
    }
  }, [storeN8nUrl])

  // Convert WorkflowIR to React Flow nodes and edges
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  useEffect(() => {
    if (!workflowIR) return

    // Convert trigger and steps to React Flow nodes
    const flowNodes: Node[] = []
    
    // Add trigger node
    flowNodes.push({
      id: workflowIR.trigger.id,
      type: 'workflowNode',
      position: { x: workflowIR.trigger.position.x, y: workflowIR.trigger.position.y },
      data: {
        step: workflowIR.trigger,
        isSelected: selectedNodeId === workflowIR.trigger.id,
      },
    })

    // Add step nodes
    workflowIR.steps.forEach((step) => {
      flowNodes.push({
        id: step.id,
        type: 'workflowNode',
        position: { x: step.position.x, y: step.position.y },
        data: {
          step,
          isSelected: selectedNodeId === step.id,
        },
      })
    })

    // Convert edges with animated flow particles
    const flowEdges: Edge[] = workflowIR.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_id,
      target: edge.target_id,
      sourceHandle: edge.source_output,
      targetHandle: edge.target_input,
      type: 'animatedFlow',
      style: { 
        stroke: '#52525b',
        strokeWidth: 2,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#f59e0b',
        width: 16,
        height: 16,
      },
    }))

    setNodes(flowNodes)
    setEdges(flowEdges)
    
    // Fit view after nodes are set
    setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 100)
  }, [workflowIR, selectedNodeId, setNodes, setEdges, fitView])

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  )

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode(node.id)
    },
    [setSelectedNode]
  )

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [setSelectedNode])

  const handleExportJson = () => {
    if (!n8nJson) return
    const blob = new Blob([JSON.stringify(n8nJson, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${workflowIR?.name || 'workflow'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handlePushToN8N = async () => {
    if (!n8nJson) return
    
    setIsPushing(true)
    setPushError(null)
    
    try {
      const result = await api.pushToN8N(n8nJson, {
        workflowName: workflowIR?.name,
        activate: false,
      })
      
      if (result.success && result.n8n_workflow_url) {
        setN8nUrl(result.n8n_workflow_url)
        // Save to store
        setN8nWorkflowUrl(result.n8n_workflow_url)
        if (result.n8n_workflow_id) {
          setN8nWorkflowId(result.n8n_workflow_id)
        }
        // Build webhook URL if not provided
        if (workflowIR?.trigger?.parameters?.path) {
          const webhookPath = workflowIR.trigger.parameters.path as string
          const baseUrl = result.n8n_workflow_url?.replace(/\/workflow\/.*/, '')
          if (baseUrl) {
            setWebhookUrl(`${baseUrl}/webhook/${webhookPath}`)
          }
        }
      } else {
        setPushError(result.message || 'Failed to push to n8n')
      }
    } catch (err) {
      setPushError(err instanceof Error ? err.message : 'Failed to push to n8n')
    } finally {
      setIsPushing(false)
    }
  }

  const handleOpenInN8N = () => {
    if (n8nUrl) {
      window.open(n8nUrl, '_blank')
    }
  }

  const handleRunTests = async () => {
    if (!workflowIR) return
    
    setIsTesting(true)
    setTestResults(null)
    setPushError(null)
    
    // Initialize test progress animation
    const totalTests = workflowIR.success_criteria?.length || 3
    setTestProgress({
      currentTest: 0,
      totalTests,
      passedTests: 0,
      failedTests: 0,
    })
    
    // Animate test progress
    let currentTest = 0
    let passed = 0
    let failed = 0
    
    testAnimationRef.current = setInterval(() => {
      currentTest++
      // Randomly pass/fail tests for animation (will be overwritten by real results)
      if (Math.random() > 0.2) {
        passed++
      } else {
        failed++
      }
      
      setTestProgress({
        currentTest,
        totalTests,
        passedTests: passed,
        failedTests: failed,
      })
      
      if (currentTest >= totalTests) {
        if (testAnimationRef.current) {
          clearInterval(testAnimationRef.current)
        }
      }
    }, 300) // Slower animation for real tests
    
    try {
      // Use the API client for proper typing
      const result = await api.runTests(
        workflowIR as unknown as Record<string, unknown>,
        n8nJson as unknown as Record<string, unknown> | undefined,
        n8nUrl ? n8nUrl.split('/').pop() : undefined,
      )
      
      // Stop animation
      if (testAnimationRef.current) {
        clearInterval(testAnimationRef.current)
      }
      
      // Update with real results
      setTestProgress({
        currentTest: result.total_count,
        totalTests: result.total_count,
        passedTests: result.passed_count,
        failedTests: result.total_count - result.passed_count,
      })
      
      // Brief pause to show final state
      await new Promise(resolve => setTimeout(resolve, 500))
      
      // Show execution mode in results
      const realCount = result.real_execution_count
      const simulatedCount = result.simulated_execution_count
      
      setTestResults({
        passed: result.passed_count,
        total: result.total_count,
        allPassed: result.all_passed,
        realExecutions: realCount,
        simulatedExecutions: simulatedCount,
        webhookUrl: result.webhook_url,
      })
      
      // Save to store for persistent display
      const testRunSummary: TestRunSummary = {
        results: result.results.map(r => ({
          test_name: r.test_name,
          passed: r.passed,
          failure_reason: r.failure_reason,
          duration_ms: r.duration_ms,
          execution_mode: r.execution_mode as 'real' | 'simulated',
          webhook_url: r.webhook_url,
        })),
        passed_count: result.passed_count,
        total_count: result.total_count,
        all_passed: result.all_passed,
        real_execution_count: realCount,
        simulated_execution_count: simulatedCount,
        webhook_url: result.webhook_url,
        executed_at: new Date().toISOString(),
      }
      setLastTestRun(testRunSummary)
      setShowTestResults(true)
      
      // Show info about execution mode
      if (simulatedCount > 0 && realCount === 0) {
        setPushError('⚠️ Tests ran in simulation mode. Push workflow to n8n and activate it for real testing.')
      } else if (result.webhook_url) {
        console.log('Webhook URL for manual testing:', result.webhook_url)
      }
    } catch (err) {
      if (testAnimationRef.current) {
        clearInterval(testAnimationRef.current)
      }
      setPushError(err instanceof Error ? err.message : 'Failed to run tests')
    } finally {
      setIsTesting(false)
    }
  }

  const handleIterate = async () => {
    if (!workflowIR) return
    
    setIsIterating(true)
    setPushError(null)
    
    // Initialize iteration progress animation
    setIterationProgress({
      iteration: 1,
      phase: 'analyze',
      phaseIndex: 0,
      testResults: null,
      score: 0,
    })
    
    // Animate iteration phases
    let phaseIndex = 0
    const phases = ['analyze', 'fix', 'apply', 'push', 'test', 'score']
    
    iterationAnimationRef.current = setInterval(() => {
      phaseIndex = (phaseIndex + 1) % phases.length
      
      setIterationProgress(prev => ({
        ...prev,
        phase: phases[phaseIndex],
        phaseIndex,
        testResults: phaseIndex >= 4 ? { passed: Math.floor(Math.random() * 3) + 7, total: 10 } : prev.testResults,
        score: phaseIndex === 5 ? 70 + Math.floor(Math.random() * 25) : prev.score,
      }))
    }, 1500)
    
    try {
      const response = await api.autoIterate(
        workflowIR.description || workflowIR.name,
        undefined, // Don't pass existing workflow ID to regenerate
        3
      )
      
      // Stop animation
      if (iterationAnimationRef.current) {
        clearInterval(iterationAnimationRef.current)
      }
      
      // Update progress with final values
      const history = response.iteration_history
      const lastIteration = history && history.length > 0 ? history[history.length - 1] : null
      setIterationProgress(prev => ({
        ...prev,
        iteration: response.total_iterations || 1,
        phaseIndex: 5, // Final phase
        testResults: lastIteration 
          ? { 
              passed: lastIteration.tests_passed,
              total: lastIteration.tests_total,
            }
          : null,
        score: response.score || 0,
      }))
      
      // Brief pause to show final state
      await new Promise(resolve => setTimeout(resolve, 800))
      
      // Update the store with new workflow
      const { setWorkflow } = useWorkflowStore.getState()
      setWorkflow(response)
      
      // Update n8n URL if we got one
      if (response.n8n_workflow_url) {
        setN8nUrl(response.n8n_workflow_url)
      }
    } catch (err) {
      if (iterationAnimationRef.current) {
        clearInterval(iterationAnimationRef.current)
      }
      setPushError(err instanceof Error ? err.message : 'Failed to iterate')
    } finally {
      setIsIterating(false)
    }
  }

  // Get selected step
  const selectedStep = workflowIR
    ? workflowIR.trigger.id === selectedNodeId
      ? workflowIR.trigger
      : workflowIR.steps.find((s) => s.id === selectedNodeId)
    : null

  if (!workflowIR) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950">
        <div className="text-center space-y-4">
          <Loader2 className="w-8 h-8 animate-spin text-amber-500 mx-auto" />
          <p className="text-zinc-500">Loading workflow...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      {/* Header */}
      <header className="border-b border-zinc-800/50 px-6 py-4 flex items-center justify-between
                         bg-zinc-900/50 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="p-2 hover:bg-zinc-800 rounded-lg transition-colors text-zinc-500 hover:text-zinc-300"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h1 className="font-semibold text-zinc-100 text-lg">{workflowIR.name}</h1>
            <p className="text-sm text-zinc-500 truncate max-w-md">
              {workflowIR.steps.length + 1} nodes • {workflowIR.edges.length} connections
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <ScoreBadge score={score} />
          
          {/* Test Results Badge - clickable to show panel */}
          {testResults && (
            <button
              onClick={() => setShowTestResults(!showTestResults)}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              <div className={`px-3 py-1.5 rounded-lg border text-sm font-medium flex items-center gap-2
                             ${testResults.allPassed 
                               ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' 
                               : 'bg-amber-500/20 text-amber-400 border-amber-500/30'}`}
              >
                {testResults.allPassed ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                {testResults.passed}/{testResults.total} Tests
              </div>
              {/* Execution Mode Indicator */}
              {testResults.realExecutions !== undefined && (
                <div className={`px-2 py-1 rounded text-xs font-medium
                               ${testResults.realExecutions > 0 
                                 ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' 
                                 : 'bg-zinc-500/20 text-zinc-400 border border-zinc-500/30'}`}
                  title={testResults.webhookUrl ? `Webhook: ${testResults.webhookUrl}` : undefined}
                >
                  {testResults.realExecutions > 0 ? '⚡ Real' : '🔄 Simulated'}
                </div>
              )}
            </button>
          )}
          
          {/* Run Tests Button */}
          <button
            onClick={handleRunTests}
            disabled={isTesting || isIterating}
            className="px-4 py-2 flex items-center gap-2 text-sm text-zinc-400
                     bg-zinc-800/50 hover:bg-zinc-800 border border-zinc-700/50
                     rounded-lg transition-all duration-200
                     disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isTesting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Testing...
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Test
              </>
            )}
          </button>
          
          {/* Iterate Button */}
          <button
            onClick={handleIterate}
            disabled={isTesting || isIterating}
            className="px-4 py-2 flex items-center gap-2 text-sm text-zinc-400
                     bg-zinc-800/50 hover:bg-zinc-800 border border-zinc-700/50
                     rounded-lg transition-all duration-200
                     disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isIterating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Iterating...
              </>
            ) : (
              <>
                <RotateCw className="w-4 h-4" />
                Iterate
              </>
            )}
          </button>
          
          {/* Try It button - only show when webhook is available */}
          {webhookUrl && (
            <button
              onClick={() => setShowTryIt(!showTryIt)}
              className={`px-4 py-2 flex items-center gap-2 text-sm font-medium
                       rounded-lg transition-all duration-200
                       ${showTryIt 
                         ? 'bg-violet-500 text-white' 
                         : 'bg-violet-500/20 hover:bg-violet-500/30 text-violet-400 border border-violet-500/30'
                       }`}
            >
              <Terminal className="w-4 h-4" />
              Try It
            </button>
          )}
          
          <button
            onClick={handleExportJson}
            className="px-4 py-2 flex items-center gap-2 text-sm text-zinc-400
                     bg-zinc-800/50 hover:bg-zinc-800 border border-zinc-700/50
                     rounded-lg transition-all duration-200"
          >
            <Download className="w-4 h-4" />
            Export
          </button>
          
          {/* Push to n8n or Open in n8n */}
          {n8nUrl ? (
            <button
              onClick={handleOpenInN8N}
              className="px-4 py-2 flex items-center gap-2 text-sm font-medium
                       bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400
                       border border-emerald-500/30 rounded-lg transition-all duration-200"
            >
              <CheckCircle className="w-4 h-4" />
              Open in n8n
            </button>
          ) : (
            <button
              onClick={handlePushToN8N}
              disabled={isPushing}
              className="px-4 py-2 flex items-center gap-2 text-sm font-medium
                       bg-amber-500 hover:bg-amber-400 text-zinc-900
                       rounded-lg transition-all duration-200
                       disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isPushing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Pushing...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" />
                  Push to n8n
                </>
              )}
            </button>
          )}
        </div>
      </header>
      
      {/* Push error toast */}
      {pushError && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-50
                        px-4 py-3 bg-red-500/10 border border-red-500/20 
                        rounded-lg text-red-400 text-sm flex items-center gap-2
                        animate-in fade-in slide-in-from-top-2 duration-200">
          <AlertCircle className="w-4 h-4" />
          {pushError}
          <button
            onClick={() => setPushError(null)}
            className="ml-2 p-1 hover:bg-red-500/20 rounded"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Webhook URL info card - only show when Try It panel is closed */}
      {webhookUrl && n8nUrl && !showTryIt && (
        <div className="absolute top-20 left-4 z-40
                        px-4 py-3 bg-emerald-500/10 border border-emerald-500/20 
                        rounded-xl text-emerald-400 max-w-md
                        animate-in fade-in slide-in-from-left-2 duration-200">
          <div className="flex items-start gap-3">
            <Zap className="w-5 h-5 mt-0.5 text-emerald-500" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-emerald-300 mb-1">Webhook Ready!</div>
              <div className="text-xs text-zinc-400 mb-2">
                Your workflow is active. Send requests to:
              </div>
              <code className="block text-xs bg-zinc-800/50 px-3 py-2 rounded-lg text-emerald-400 
                             break-all font-mono border border-emerald-500/10">
                {webhookUrl}
              </code>
              <button
                onClick={() => navigator.clipboard.writeText(webhookUrl)}
                className="mt-2 text-xs text-emerald-400 hover:text-emerald-300 
                         flex items-center gap-1 transition-colors"
              >
                <Copy className="w-3 h-3" />
                Copy URL
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Try It Panel - Manual webhook testing (Enhanced) */}
      {showTryIt && webhookUrl && (
        <TryItPanel
          webhookUrl={webhookUrl}
          onClose={() => setShowTryIt(false)}
        />
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Graph and side panels */}
        <div className="flex-1 relative flex">
          {/* React Flow Graph */}
          <div className="flex-1 relative">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onPaneClick={onPaneClick}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.1}
              maxZoom={2}
              defaultEdgeOptions={{
                type: 'animatedFlow',
              }}
              proOptions={{ hideAttribution: true }}
            >
              <Background 
                color="#27272a" 
                gap={24} 
                size={1}
              />
              <FlowControls />
            </ReactFlow>

            {/* Node detail panel */}
            {selectedStep && (
              <NodePanel
                step={selectedStep}
                onClose={() => setSelectedNode(null)}
              />
            )}
            
            {/* Iteration history panel (for auto-iterated workflows) */}
            {autoIterated && !showTestResults && (
              <IterationHistoryPanel
                iterations={iterationHistory}
                totalIterations={totalIterations}
                success={success}
                stopReason={stopReason}
              />
            )}
          </div>
          
          {/* Test Results Panel (right side) */}
          {showTestResults && lastTestRun && (
            <div className="absolute right-4 top-4 z-20 animate-in slide-in-from-right-4 duration-200">
              <TestResultsPanel onClose={() => setShowTestResults(false)} />
            </div>
          )}
        </div>
        
        {/* Execution History Panel (bottom) */}
        {n8nWorkflowId && (
          <ExecutionHistoryPanel
            isCollapsed={executionHistoryCollapsed}
            onToggleCollapse={() => setExecutionHistoryCollapsed(!executionHistoryCollapsed)}
          />
        )}
      </div>
      
      {/* Animated Test Progress Modal */}
      <TestProgressModal 
        isVisible={isTesting}
        currentTest={testProgress.currentTest}
        totalTests={testProgress.totalTests}
        passedTests={testProgress.passedTests}
        failedTests={testProgress.failedTests}
        status={isTesting ? 'running' : 'complete'}
      />
      
      {/* Animated Iteration Progress Modal */}
      <IterationProgressModal
        isVisible={isIterating}
        iteration={iterationProgress.iteration}
        phase={iterationProgress.phase}
        phaseIndex={iterationProgress.phaseIndex}
        testResults={iterationProgress.testResults}
        currentScore={iterationProgress.score}
      />
    </div>
  )
}

export default function WorkflowPage() {
  return (
    <ReactFlowProvider>
      <WorkflowPageContent />
    </ReactFlowProvider>
  )
}
