import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { 
  Sparkles, ArrowRight, Loader2, Zap, RefreshCw, 
  CheckCircle, XCircle, Play, Wrench, TestTube,
  Upload, Brain, Target
} from 'lucide-react'
import { api } from '../lib/api'
import { useWorkflowStore } from '../stores/workflowStore'

const LOADING_MESSAGES = [
  'Analyzing your request...',
  'Decomposing workflow...',
  'Planning execution graph...',
  'Generating n8n nodes...',
  'Compiling workflow...',
  'Running validation...',
  'Almost there...',
]

// Phase definitions for auto-iteration animation
const ITERATION_PHASES = [
  { id: 'generate', label: 'Generating Workflow', icon: Brain, color: 'text-purple-400' },
  { id: 'push', label: 'Pushing to n8n', icon: Upload, color: 'text-blue-400' },
  { id: 'test', label: 'Running Tests', icon: TestTube, color: 'text-amber-400' },
  { id: 'analyze', label: 'Analyzing Results', icon: Target, color: 'text-cyan-400' },
  { id: 'fix', label: 'Generating Fixes', icon: Wrench, color: 'text-orange-400' },
  { id: 'apply', label: 'Applying Improvements', icon: Play, color: 'text-green-400' },
]

interface IterationProgress {
  currentIteration: number
  maxIterations: number
  phase: string
  phaseIndex: number
  testsPassed: number
  testsTotal: number
  score: number
  status: 'running' | 'success' | 'failed'
}

// Animated Progress Modal Component
function IterationProgressModal({ 
  progress, 
  isVisible 
}: { 
  progress: IterationProgress
  isVisible: boolean 
}) {
  if (!isVisible) return null

  const currentPhase = ITERATION_PHASES[progress.phaseIndex] || ITERATION_PHASES[0]
  const PhaseIcon = currentPhase.icon

  return (
    <div className="fixed inset-0 bg-zinc-950/90 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-amber-500/10 border border-amber-500/20 rounded-full mb-4">
            <RefreshCw className="w-4 h-4 text-amber-500 animate-spin" />
            <span className="text-sm font-medium text-amber-400">Auto-Iterating</span>
          </div>
          <h3 className="text-xl font-semibold text-zinc-100">
            Iteration {progress.currentIteration} of {progress.maxIterations}
          </h3>
        </div>

        {/* Phase Indicator */}
        <div className="mb-8">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className={`p-3 rounded-xl bg-zinc-800 ${currentPhase.color}`}>
              <PhaseIcon className="w-6 h-6 animate-pulse" />
            </div>
            <span className="text-lg font-medium text-zinc-200">{currentPhase.label}</span>
          </div>
          
          {/* Phase Progress Dots */}
          <div className="flex justify-center gap-2">
            {ITERATION_PHASES.map((phase, idx) => (
              <div
                key={phase.id}
                className={`w-2 h-2 rounded-full transition-all duration-300 ${
                  idx < progress.phaseIndex 
                    ? 'bg-emerald-500' 
                    : idx === progress.phaseIndex 
                      ? 'bg-amber-500 animate-pulse scale-125' 
                      : 'bg-zinc-700'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Test Results */}
        {progress.testsTotal > 0 && (
          <div className="bg-zinc-800/50 rounded-xl p-4 mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-zinc-400">Test Results</span>
              <span className={`text-sm font-medium ${
                progress.testsPassed === progress.testsTotal 
                  ? 'text-emerald-400' 
                  : 'text-amber-400'
              }`}>
                {progress.testsPassed}/{progress.testsTotal} passed
              </span>
            </div>
            
            {/* Test Progress Bar */}
            <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all duration-500 ${
                  progress.testsPassed === progress.testsTotal 
                    ? 'bg-emerald-500' 
                    : 'bg-amber-500'
                }`}
                style={{ width: `${(progress.testsPassed / progress.testsTotal) * 100}%` }}
              />
            </div>
            
            {/* Animated Test Icons */}
            <div className="flex flex-wrap gap-1 mt-3 justify-center">
              {Array.from({ length: progress.testsTotal }).map((_, idx) => (
                <div
                  key={idx}
                  className={`w-5 h-5 rounded flex items-center justify-center transition-all duration-300 ${
                    idx < progress.testsPassed 
                      ? 'bg-emerald-500/20' 
                      : idx < progress.testsTotal - (progress.testsTotal - progress.testsPassed)
                        ? 'bg-red-500/20'
                        : 'bg-zinc-700/50'
                  }`}
                  style={{ animationDelay: `${idx * 50}ms` }}
                >
                  {idx < progress.testsPassed ? (
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  ) : idx < progress.testsTotal ? (
                    <div className="w-2 h-2 bg-zinc-500 rounded-full animate-pulse" />
                  ) : (
                    <XCircle className="w-3 h-3 text-red-400" />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Score */}
        {progress.score > 0 && (
          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-4 py-2 bg-zinc-800 rounded-lg">
              <span className="text-sm text-zinc-400">Current Score:</span>
              <span className={`text-lg font-bold ${
                progress.score >= 80 ? 'text-emerald-400' : 
                progress.score >= 60 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {progress.score}
              </span>
            </div>
          </div>
        )}

        {/* Status Message */}
        <p className="text-center text-sm text-zinc-500 mt-6 animate-pulse">
          {progress.status === 'running' && 'Working on improving your workflow...'}
          {progress.status === 'success' && 'Workflow optimized successfully!'}
          {progress.status === 'failed' && 'Reached maximum iterations'}
        </p>
      </div>
    </div>
  )
}

const EXAMPLE_PROMPTS = [
  {
    title: 'AI Sentiment Analysis',
    description: 'Analyze message sentiment using AI',
    prompt: 'Webhook that receives a message and uses AI to classify its sentiment as positive, negative, or neutral. Return the sentiment with confidence score.',
  },
  {
    title: 'Customer Support Triage',
    description: 'Classify messages and route to appropriate handlers',
    prompt: 'Customer support webhook: Receive a message and use AI to classify it as billing, technical, or general inquiry. Return the category and a suggested response.',
  },
  {
    title: 'Content Summarizer',
    description: 'Summarize long text using AI',
    prompt: 'Webhook that receives an article or long text and uses AI to generate a concise summary with key points.',
  },
]

export default function DescribePage() {
  const navigate = useNavigate()
  const { setWorkflow, setError, error } = useWorkflowStore()
  const [prompt, setPrompt] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0)
  const [autoIterate, setAutoIterate] = useState(false)
  
  // Iteration progress state
  const [iterationProgress, setIterationProgress] = useState<IterationProgress>({
    currentIteration: 1,
    maxIterations: 5,
    phase: 'generate',
    phaseIndex: 0,
    testsPassed: 0,
    testsTotal: 0,
    score: 0,
    status: 'running',
  })
  const [showProgress, setShowProgress] = useState(false)

  // Rotate loading messages while generating (for non-auto-iterate)
  useEffect(() => {
    if (!isGenerating || autoIterate) {
      setLoadingMessageIndex(0)
      return
    }
    
    const interval = setInterval(() => {
      setLoadingMessageIndex((prev) => 
        prev < LOADING_MESSAGES.length - 1 ? prev + 1 : prev
      )
    }, 2000)
    
    return () => clearInterval(interval)
  }, [isGenerating, autoIterate])

  // Simulate iteration progress for auto-iterate mode
  const simulateIterationProgress = useCallback(() => {
    let iteration = 1
    let phaseIndex = 0
    let testsRun = 0
    
    const progressInterval = setInterval(() => {
      phaseIndex = (phaseIndex + 1) % ITERATION_PHASES.length
      
      // Simulate test results during test phase
      if (phaseIndex === 2) { // test phase
        testsRun = Math.floor(Math.random() * 5) + 8
      }
      
      setIterationProgress(prev => ({
        ...prev,
        currentIteration: iteration,
        phaseIndex,
        phase: ITERATION_PHASES[phaseIndex].id,
        testsPassed: phaseIndex >= 3 ? Math.floor(testsRun * 0.85) + Math.floor(Math.random() * 2) : prev.testsPassed,
        testsTotal: phaseIndex >= 2 ? testsRun : prev.testsTotal,
        score: phaseIndex >= 3 ? 70 + Math.floor(Math.random() * 25) : prev.score,
      }))
      
      // Move to next iteration after completing all phases
      if (phaseIndex === ITERATION_PHASES.length - 1) {
        iteration++
        if (iteration > 5) {
          clearInterval(progressInterval)
        }
      }
    }, 1500)
    
    return () => clearInterval(progressInterval)
  }, [])

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      setError('Please enter a workflow description')
      return
    }

    setIsGenerating(true)
    setError(null)
    setLoadingMessageIndex(0)
    
    // Show progress modal for auto-iterate
    if (autoIterate) {
      setShowProgress(true)
      setIterationProgress({
        currentIteration: 1,
        maxIterations: 5,
        phase: 'generate',
        phaseIndex: 0,
        testsPassed: 0,
        testsTotal: 0,
        score: 0,
        status: 'running',
      })
      
      // Start simulating progress
      const cleanup = simulateIterationProgress()
      
      try {
        const response = await api.synthesize({ 
          prompt,
          auto_iterate: true,
          max_iterations: 5,
        })
        
        cleanup()
        
        // Update final progress state
        setIterationProgress(prev => ({
          ...prev,
          currentIteration: response.total_iterations || 1,
          phaseIndex: ITERATION_PHASES.length - 1,
          testsPassed: response.iteration_history?.[response.iteration_history.length - 1]?.tests_passed || prev.testsPassed,
          testsTotal: response.iteration_history?.[response.iteration_history.length - 1]?.tests_total || prev.testsTotal,
          score: response.score || 0,
          status: response.success ? 'success' : 'failed',
        }))
        
        // Brief delay to show success state
        await new Promise(resolve => setTimeout(resolve, 1000))
        
        setWorkflow(response)
        setShowProgress(false)
        navigate(`/workflow/${response.workflow_id}`)
      } catch (err) {
        cleanup()
        console.error('Synthesis error:', err)
        const errorMessage = err instanceof Error ? err.message : 'Failed to generate workflow'
        setError(errorMessage)
        setIsGenerating(false)
        setShowProgress(false)
      }
    } else {
      // Non-auto-iterate mode
      try {
        const response = await api.synthesize({ 
          prompt,
          auto_iterate: false,
        })
        setWorkflow(response)
        navigate(`/workflow/${response.workflow_id}`)
      } catch (err) {
        console.error('Synthesis error:', err)
        const errorMessage = err instanceof Error ? err.message : 'Failed to generate workflow'
        setError(errorMessage)
        setIsGenerating(false)
      }
    }
  }

  const handleExampleClick = (examplePrompt: string) => {
    setPrompt(examplePrompt)
  }

  return (
    <div className="min-h-screen flex flex-col bg-zinc-950">
      {/* Header */}
      <header className="border-b border-zinc-800/50 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 
                          border border-amber-500/20 flex items-center justify-center">
            <Zap className="w-5 h-5 text-amber-500" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Workflow Synthesizer</h1>
            <p className="text-sm text-zinc-500">Natural language → n8n workflows</p>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-12">
        <div className="w-full max-w-2xl space-y-8 animate-fade-in">
          {/* Title */}
          <div className="text-center space-y-3">
            <h2 className="text-4xl font-bold text-zinc-100 tracking-tight">
              Describe your workflow
            </h2>
            <p className="text-zinc-500 text-lg">
              Tell us what you want to automate in plain English
            </p>
          </div>

          {/* Input area */}
          <div className="space-y-4">
            <div className="relative group">
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="e.g., When a customer sends a support email, classify the intent, draft a response, and log it to our database..."
                className="w-full h-36 px-5 py-4 bg-zinc-900/50 border border-zinc-800 rounded-2xl 
                         text-zinc-100 placeholder-zinc-600 resize-none
                         focus:outline-none focus:border-amber-500/50 focus:ring-2 focus:ring-amber-500/20
                         transition-all duration-200"
              />
              <div className="absolute bottom-3 right-4 text-xs text-zinc-600">
                {prompt.length} / 5000
              </div>
            </div>

            {error && (
              <div className="px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Auto-iterate toggle */}
            <div className="flex items-center justify-between px-4 py-3 bg-zinc-900/30 border border-zinc-800/50 rounded-xl">
              <div className="flex items-center gap-3">
                <RefreshCw className={`w-5 h-5 ${autoIterate ? 'text-amber-500' : 'text-zinc-500'}`} />
                <div>
                  <div className="text-sm font-medium text-zinc-200">Auto-iterate</div>
                  <div className="text-xs text-zinc-500">
                    Automatically test and improve until workflow passes
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setAutoIterate(!autoIterate)}
                disabled={isGenerating}
                className={`relative w-12 h-6 rounded-full transition-colors duration-200
                          ${autoIterate ? 'bg-amber-500' : 'bg-zinc-700'}
                          disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                <div
                  className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform duration-200
                            ${autoIterate ? 'translate-x-7' : 'translate-x-1'}`}
                />
              </button>
            </div>

            <button
              type="button"
              onClick={handleGenerate}
              disabled={!prompt.trim() || isGenerating}
              className={`w-full px-6 py-4 font-semibold rounded-xl
                       flex items-center justify-center gap-3
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-200 shadow-lg active:scale-[0.98]
                       ${autoIterate 
                         ? 'bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 shadow-orange-500/20 hover:shadow-orange-500/30' 
                         : 'bg-amber-500 hover:bg-amber-400 shadow-amber-500/20 hover:shadow-amber-500/30'
                       } text-zinc-900`}
            >
              {isGenerating && !autoIterate ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>{LOADING_MESSAGES[loadingMessageIndex]}</span>
                </>
              ) : isGenerating && autoIterate ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Iterating...</span>
                </>
              ) : (
                <>
                  {autoIterate ? (
                    <>
                      <RefreshCw className="w-5 h-5" />
                      <span>Generate & Auto-Iterate</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-5 h-5" />
                      <span>Generate Workflow</span>
                    </>
                  )}
                  <ArrowRight className="w-5 h-5" />
                </>
              )}
            </button>
            
            {isGenerating && !autoIterate && (
              <p className="text-center text-sm text-zinc-500 animate-pulse-subtle">
                This may take 10-30 seconds...
              </p>
            )}
          </div>

          {/* Example prompts */}
          <div className="space-y-4 pt-4">
            <p className="text-sm text-zinc-500 text-center">Or try an example:</p>
            <div className="grid gap-3">
              {EXAMPLE_PROMPTS.map((example, i) => (
                <button
                  key={i}
                  onClick={() => handleExampleClick(example.prompt)}
                  disabled={isGenerating}
                  className={`px-5 py-4 bg-zinc-900/30 border border-zinc-800/50 rounded-xl
                           text-left hover:border-zinc-700 hover:bg-zinc-900/50
                           transition-all duration-200 animate-slide-up stagger-${i + 1}
                           disabled:opacity-50 disabled:cursor-not-allowed
                           group`}
                  style={{ animationFillMode: 'both' }}
                >
                  <div className="font-medium text-zinc-200 group-hover:text-zinc-100 
                                  transition-colors">
                    {example.title}
                  </div>
                  <div className="text-sm text-zinc-500 group-hover:text-zinc-400 
                                  transition-colors">
                    {example.description}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-800/50 px-6 py-4 text-center text-sm text-zinc-600">
        Powered by ROMA synthesis engine • n8n integration
      </footer>
      
      {/* Iteration Progress Modal */}
      <IterationProgressModal 
        progress={iterationProgress} 
        isVisible={showProgress} 
      />
    </div>
  )
}
