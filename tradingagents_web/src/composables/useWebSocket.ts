import { useAnalysisStore } from '../stores/analysis'
import type { WsOutboundMessage, WsInboundMessage, AnalysisConfig } from '../types/ws'

let wsInstance: WebSocket | null = null
let isConnecting = false

export function useWebSocket() {
  const store = useAnalysisStore()

  function connect(url: string = `ws://${location.hostname}:8000/api/ws`) {
    // Strong guard: only one connection attempt at a time
    if (isConnecting) return
    if (wsInstance?.readyState === WebSocket.OPEN || wsInstance?.readyState === WebSocket.CONNECTING) {
      return
    }

    isConnecting = true
    wsInstance = new WebSocket(url)

    wsInstance.onopen = () => {
      store.connected = true
      isConnecting = false
    }

    wsInstance.onmessage = (event: MessageEvent) => {
      try {
        const msg: WsOutboundMessage = JSON.parse(event.data)
        dispatch(msg)
      } catch (e) {
        console.error('Failed to parse WS message:', e)
      }
    }

    wsInstance.onclose = () => {
      store.connected = false
      isConnecting = false
    }

    wsInstance.onerror = () => {
      isConnecting = false
      wsInstance?.close()
    }
  }

  function dispatch(msg: WsOutboundMessage) {
    switch (msg.type) {
      case 'connection_established':
        store.sessionId = msg.payload.session_id
        break
      case 'analysis_started':
        store.handleAnalysisStarted(msg.payload)
        break
      case 'agent_status_update':
        store.handleAgentStatus(msg.payload)
        break
      case 'message':
        store.handleMessage(msg.payload)
        break
      case 'tool_call':
        store.handleToolCall(msg.payload)
        break
      case 'report_section_update':
        store.handleReportSection(msg.payload)
        break
      case 'stats_update':
        store.handleStats(msg.payload)
        break
      case 'analysis_complete':
        store.handleComplete(msg.payload)
        break
      case 'error':
        console.error('Server error:', msg.payload.message)
        store.handleError(msg.payload.message)
        break
    }
  }

  function send(msg: WsInboundMessage) {
    if (wsInstance?.readyState === WebSocket.OPEN) {
      wsInstance.send(JSON.stringify(msg))
    }
  }

  function startAnalysis(config: AnalysisConfig) {
    store.reset()
    send({ type: 'start_analysis', payload: config })
  }

  function cancelAnalysis() {
    send({ type: 'cancel_analysis', payload: {} })
  }

  function disconnect() {
    wsInstance?.close()
    wsInstance = null
    isConnecting = false
  }

  return { connect, startAnalysis, cancelAnalysis, disconnect }
}
