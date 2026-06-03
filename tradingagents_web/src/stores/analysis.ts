import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AgentStatusValue, MessageTypeValue, MessageEntry, ToolCallEntry, StatsPayload } from '../types/ws'

export interface TeamDef {
  name: string
  agents: string[]
}

const ALL_TEAMS: TeamDef[] = [
  { name: '分析师团队', agents: ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'] },
  { name: '研究团队', agents: ['Bull Researcher', 'Bear Researcher', 'Research Manager'] },
  { name: '交易团队', agents: ['Trader'] },
  { name: '风险控制', agents: ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'] },
  { name: '投资组合管理', agents: ['Portfolio Manager'] },
]

export const useAnalysisStore = defineStore('analysis', () => {
  // ── Connection state ────────────────────────────────────────────────
  const running = ref(false)
  const connected = ref(false)
  const sessionId = ref<string | null>(null)
  const startTime = ref<number | null>(null)

  // ── Agent status tracking ───────────────────────────────────────────
  const agentStatuses = ref<Record<string, AgentStatusValue>>({})

  // ── Message log ─────────────────────────────────────────────────────
  const messages = ref<MessageEntry[]>([])
  const toolCalls = ref<ToolCallEntry[]>([])
  let msgCounter = 0

  // ── Report sections ─────────────────────────────────────────────────
  const reportSections = ref<Record<string, string | null>>({})
  const currentReport = ref<string | null>(null)
  const finalReport = ref<string | null>(null)

  // ── Stats ───────────────────────────────────────────────────────────
  const stats = ref<StatsPayload>({
    llm_calls: 0,
    tool_calls: 0,
    tokens_in: 0,
    tokens_out: 0,
    elapsed_seconds: 0,
  })

  // ── Error state ─────────────────────────────────────────────────────
  const errorMessage = ref<string | null>(null)

  // ── Computed ────────────────────────────────────────────────────────
  const agentsCompleted = computed(() =>
    Object.values(agentStatuses.value).filter(s => s === 'completed').length
  )
  const agentsTotal = computed(() => Object.keys(agentStatuses.value).length)

  const displayAgentsByTeam = computed(() =>
    ALL_TEAMS
      .map(team => ({
        ...team,
        agents: team.agents.filter(a => a in agentStatuses.value),
      }))
      .filter(team => team.agents.length > 0)
  )

  const elapsedDisplay = computed(() => {
    if (!startTime.value) return '00:00'
    const s = Math.floor((Date.now() - startTime.value) / 1000)
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  })

  // ── Actions ─────────────────────────────────────────────────────────
  function reset() {
    running.value = false
    // Don't reset connected — it's managed by WebSocket lifecycle, not analysis state.
    // reset() is called when starting a new analysis or going back to config; the
    // connection remains open across runs.
    sessionId.value = null
    startTime.value = null
    agentStatuses.value = {}
    messages.value = []
    toolCalls.value = []
    reportSections.value = {}
    currentReport.value = null
    finalReport.value = null
    errorMessage.value = null
    stats.value = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0, elapsed_seconds: 0 }
    msgCounter = 0
  }

  function handleAnalysisStarted(_payload: { ticker: string; date: string; analysts: string[] }) {
    running.value = true
    startTime.value = Date.now()
  }

  function handleAgentStatus(payload: { agent_name: string; status: AgentStatusValue }) {
    agentStatuses.value = { ...agentStatuses.value, [payload.agent_name]: payload.status }
  }

  function handleMessage(payload: { timestamp: string; type: MessageTypeValue; content: string }) {
    messages.value.push({ id: msgCounter++, ...payload })
    if (messages.value.length > 200) {
      messages.value = messages.value.slice(-100)
    }
  }

  function handleToolCall(payload: { timestamp: string; name: string; args: Record<string, unknown> }) {
    toolCalls.value.push({ id: msgCounter++, ...payload })
    if (toolCalls.value.length > 200) {
      toolCalls.value = toolCalls.value.slice(-100)
    }
  }

  function handleReportSection(payload: { section: string; content: string }) {
    reportSections.value = { ...reportSections.value, [payload.section]: payload.content }
  }

  function handleStats(payload: StatsPayload) {
    stats.value = payload
  }

  function handleComplete(payload: { summary: string }) {
    running.value = false
    if (payload.summary) {
      finalReport.value = payload.summary
    }
  }

  function handleError(message: string) {
    errorMessage.value = message
    running.value = false
  }

  return {
    running, connected, sessionId, startTime,
    agentStatuses, messages, toolCalls, reportSections,
    currentReport, finalReport, errorMessage, stats,
    agentsCompleted, agentsTotal, displayAgentsByTeam, elapsedDisplay,
    reset, handleAnalysisStarted, handleAgentStatus, handleMessage,
    handleToolCall, handleReportSection, handleStats, handleComplete, handleError,
  }
})
