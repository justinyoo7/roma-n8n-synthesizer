import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import {
  Webhook,
  Play,
  Clock,
  Bot,
  GitBranch,
  GitMerge,
  Cog,
  Zap,
  Database,
  Mail,
  MessageSquare,
  Code,
} from 'lucide-react'
import type { StepSpec } from '../types/workflow'

interface WorkflowNodeData {
  step: StepSpec
  isSelected: boolean
}

interface WorkflowNodeProps {
  data: WorkflowNodeData
}

const getNodeIcon = (step: StepSpec) => {
  const nodeType = step.n8n_node_type.toLowerCase()
  
  // Match by n8n node type
  if (nodeType.includes('webhook')) return Webhook
  if (nodeType.includes('manual')) return Play
  if (nodeType.includes('schedule') || nodeType.includes('cron')) return Clock
  if (nodeType.includes('database') || nodeType.includes('postgres') || nodeType.includes('mysql')) return Database
  if (nodeType.includes('email') || nodeType.includes('gmail') || nodeType.includes('smtp')) return Mail
  if (nodeType.includes('slack') || nodeType.includes('discord') || nodeType.includes('telegram')) return MessageSquare
  if (nodeType.includes('code') || nodeType.includes('function')) return Code
  if (nodeType.includes('http') || nodeType.includes('request')) return Zap
  
  // Match by step type
  switch (step.type) {
    case 'trigger': return Play
    case 'agent': return Bot
    case 'branch': return GitBranch
    case 'merge': return GitMerge
    case 'transform': return Cog
    default: return Zap
  }
}

const getNodeStyle = (_step: StepSpec, isSelected: boolean) => {
  const baseStyle = 'transition-all duration-200 ease-out'
  
  if (isSelected) {
    return `${baseStyle} ring-2 ring-amber-400 ring-offset-2 ring-offset-zinc-900 scale-105`
  }
  
  return baseStyle
}

const getIconBgColor = (step: StepSpec) => {
  switch (step.type) {
    case 'trigger': return 'bg-emerald-500/20 text-emerald-400'
    case 'agent': return 'bg-violet-500/20 text-violet-400'
    case 'branch': return 'bg-amber-500/20 text-amber-400'
    case 'merge': return 'bg-sky-500/20 text-sky-400'
    case 'transform': return 'bg-orange-500/20 text-orange-400'
    case 'action': return 'bg-blue-500/20 text-blue-400'
    default: return 'bg-zinc-500/20 text-zinc-400'
  }
}

function WorkflowNode({ data }: WorkflowNodeProps) {
  const { step, isSelected } = data
  const Icon = getNodeIcon(step)
  const nodeTypeName = step.n8n_node_type.split('.').pop() || step.type

  return (
    <div className={`group ${getNodeStyle(step, isSelected)} relative`}>
      {/* Animated glow effect behind the node */}
      <div className="absolute inset-0 -z-10 rounded-xl opacity-0 group-hover:opacity-100 
                      transition-opacity duration-500">
        <div className="absolute inset-[-2px] rounded-xl bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-amber-500/20
                        animate-pulse blur-md" />
      </div>
      
      {/* Subtle pulse ring animation */}
      <div className="absolute inset-[-8px] -z-20 rounded-2xl">
        <div className="absolute inset-0 rounded-2xl border border-amber-500/10 animate-ping 
                        [animation-duration:3s] opacity-50" />
      </div>
      
      {/* Input handle with glow */}
      {step.type !== 'trigger' && (
        <Handle
          type="target"
          position={Position.Left}
          id="main"
          className="!w-3 !h-3 !bg-zinc-600 !border-2 !border-zinc-800 
                     group-hover:!bg-amber-500 group-hover:!shadow-[0_0_8px_rgba(245,158,11,0.5)]
                     transition-all duration-300"
        />
      )}

      {/* Node content */}
      <div className="bg-zinc-800/90 backdrop-blur-sm border border-zinc-700/50 
                      rounded-xl px-4 py-3 min-w-[160px] max-w-[200px]
                      shadow-lg shadow-black/20
                      group-hover:border-amber-500/30 group-hover:bg-zinc-800
                      group-hover:shadow-[0_0_20px_rgba(245,158,11,0.1)]
                      transition-all duration-300">
        
        {/* Header with icon and type */}
        <div className="flex items-center gap-3 mb-2">
          <div className={`p-2 rounded-lg ${getIconBgColor(step)}`}>
            <Icon className="w-4 h-4" />
          </div>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500 font-medium">
            {nodeTypeName}
          </span>
        </div>
        
        {/* Node name */}
        <div className="text-sm font-medium text-zinc-100 truncate">
          {step.name}
        </div>
        
        {/* Description if available */}
        {step.description && (
          <div className="text-xs text-zinc-500 mt-1 truncate">
            {step.description}
          </div>
        )}
        
        {/* Agent badge */}
        {step.agent && (
          <div className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 
                          bg-violet-500/10 border border-violet-500/20 
                          rounded-full text-[10px] text-violet-400">
            <Bot className="w-3 h-3" />
            {step.agent.name}
          </div>
        )}
      </div>

      {/* Output handle(s) with glow effects */}
      {step.type === 'branch' ? (
        <>
          <Handle
            type="source"
            position={Position.Right}
            id="output0"
            style={{ top: '30%' }}
            className="!w-3 !h-3 !bg-amber-500 !border-2 !border-zinc-800
                       !shadow-[0_0_6px_rgba(245,158,11,0.4)]
                       hover:!shadow-[0_0_10px_rgba(245,158,11,0.6)]
                       transition-shadow duration-300"
          />
          <Handle
            type="source"
            position={Position.Right}
            id="output1"
            style={{ top: '50%' }}
            className="!w-3 !h-3 !bg-amber-500 !border-2 !border-zinc-800
                       !shadow-[0_0_6px_rgba(245,158,11,0.4)]
                       hover:!shadow-[0_0_10px_rgba(245,158,11,0.6)]
                       transition-shadow duration-300"
          />
          <Handle
            type="source"
            position={Position.Right}
            id="output2"
            style={{ top: '70%' }}
            className="!w-3 !h-3 !bg-amber-500 !border-2 !border-zinc-800
                       !shadow-[0_0_6px_rgba(245,158,11,0.4)]
                       hover:!shadow-[0_0_10px_rgba(245,158,11,0.6)]
                       transition-shadow duration-300"
          />
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Right}
          id="main"
          className="!w-3 !h-3 !bg-zinc-600 !border-2 !border-zinc-800
                     group-hover:!bg-amber-500 group-hover:!shadow-[0_0_8px_rgba(245,158,11,0.5)]
                     transition-all duration-300"
        />
      )}
    </div>
  )
}

export default memo(WorkflowNode)
