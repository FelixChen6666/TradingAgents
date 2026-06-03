/** WebSocket protocol types — matches the Python `ws_messages.py` contract. */

export type AgentStatusValue = 'pending' | 'in_progress' | 'completed' | 'error'
export type MessageTypeValue = 'Agent' | 'User' | 'Data' | 'Tool' | 'Control' | 'System'

/** Server → Client messages */
export type WsOutboundMessage =
  | { type: 'connection_established'; payload: { session_id: string } }
  | { type: 'analysis_started'; payload: { ticker: string; date: string; analysts: string[] } }
  | { type: 'agent_status_update'; payload: { agent_name: string; status: AgentStatusValue } }
  | { type: 'message'; payload: { timestamp: string; type: MessageTypeValue; content: string } }
  | { type: 'tool_call'; payload: { timestamp: string; name: string; args: Record<string, unknown> } }
  | { type: 'report_section_update'; payload: { section: string; content: string } }
  | { type: 'stats_update'; payload: StatsPayload }
  | { type: 'analysis_complete'; payload: { summary: string; wall_times: Record<string, number> } }
  | { type: 'error'; payload: { message: string } }

/** Client → Server messages */
export type WsInboundMessage =
  | { type: 'start_analysis'; payload: AnalysisConfig }
  | { type: 'cancel_analysis'; payload: Record<string, never> }

export interface StatsPayload {
  llm_calls: number
  tool_calls: number
  tokens_in: number
  tokens_out: number
  elapsed_seconds: number
}

export interface AnalysisConfig {
  ticker: string
  analysis_date: string
  analysts: string[]
  research_depth: number
  llm_provider: string
  backend_url: string | null
  shallow_thinker: string
  deep_thinker: string
  google_thinking_level: string | null
  openai_reasoning_effort: string | null
  anthropic_effort: string | null
  output_language: string
  data_vendors: Record<string, string>
  asset_type: string
  checkpoint_enabled: boolean
  api_keys: Record<string, string>
  holds_stock: boolean
  position_quantity: number | null
  position_avg_cost: number | null
}

export interface TeamDefinition {
  name: string
  agents: string[]
}

export const ALL_TEAMS: TeamDefinition[] = [
  { name: 'Analyst Team', agents: ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'] },
  { name: 'Research Team', agents: ['Bull Researcher', 'Bear Researcher', 'Research Manager'] },
  { name: 'Trading Team', agents: ['Trader'] },
  { name: 'Risk Management', agents: ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'] },
  { name: 'Portfolio Management', agents: ['Portfolio Manager'] },
]

export interface MessageEntry {
  id: number
  timestamp: string
  type: MessageTypeValue
  content: string
}

export interface ToolCallEntry {
  id: number
  timestamp: string
  name: string
  args: Record<string, unknown>
}

export interface PanelDefinition {
  id: string
  title: string
  component: unknown
  defaultWidth?: number
  defaultPosition?: 'left' | 'center' | 'right'
}

export const MSG_TYPE_COLORS: Record<MessageTypeValue, string> = {
  Agent: '#4fc3f7',
  User: '#81c784',
  Data: '#ffb74d',
  Tool: '#ce93d8',
  Control: '#9e9e9e',
  System: '#90a4ae',
}
