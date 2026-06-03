<template>
  <div class="app-shell" ref="containerRef">
    <!-- Analysis view: show during and after analysis until user goes back -->
    <template v-if="showAnalysis">
      <header class="app-header">
        <h1>TradingAgents</h1>
        <span class="subtitle">{{ currentLabel }}</span>
        <div class="header-right">
          <span :class="['status-dot', store.connected ? 'connected' : 'disconnected']" />
          <span class="status-label">{{ store.connected ? '已连接' : '未连接' }}</span>
          <template v-if="store.running">
            <button class="cancel-btn" @click="cancelAnalysis">取消</button>
          </template>
          <template v-else>
            <button class="save-btn" @click="saveReport">保存报告</button>
            <button class="back-btn" @click="goBackToConfig">返回配置</button>
          </template>
        </div>
      </header>

      <div v-if="store.errorMessage" class="error-banner">
        {{ store.errorMessage }}
      </div>

      <div class="panels-container">
        <ProgressPanel :style="{ width: leftWidth + 'px', minWidth: '200px' }" />
        <PanelSplitter @resize="(d: number) => onSplitterResize(d, 'left')" />
        <MessagesPanel :style="{ flex: 1, minWidth: 0 }" />
        <PanelSplitter @resize="(d: number) => onSplitterResize(d, 'right')" />
        <ReportPanel :style="{ width: rightWidth + 'px', minWidth: '200px' }" />
      </div>

      <StatusBar />
    </template>

    <!-- Not running — show config panel -->
    <template v-else>
      <ConfigPanel />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, provide, watch } from 'vue'
import { useAnalysisStore } from '../../stores/analysis'
import { useWebSocket } from '../../composables/useWebSocket'
import { usePanelLayout } from '../../composables/usePanelLayout'
import PanelSplitter from './PanelSplitter.vue'
import StatusBar from './StatusBar.vue'
import ProgressPanel from '../panels/ProgressPanel.vue'
import MessagesPanel from '../panels/MessagesPanel.vue'
import ReportPanel from '../panels/ReportPanel.vue'
import ConfigPanel from '../config/ConfigPanel.vue'

const store = useAnalysisStore()
const ws = useWebSocket()

provide('ws', ws)

const showAnalysis = ref(false)
const containerRef = ref<HTMLElement | null>(null)
const containerWidth = ref(1200)

const { leftWidth, rightWidth, onSplitterResize } = usePanelLayout(containerWidth.value)

const currentLabel = computed(() => {
  const ticker = Object.keys(store.agentStatuses)[0] || ''
  if (store.running) return ticker ? `正在分析 ${ticker}...` : '分析进行中...'
  if (store.errorMessage) return '分析出错'
  if (ticker) return `分析完成 — ${ticker}`
  return '分析完成'
})

// Show analysis view when analysis starts, keep visible until user manually goes back
watch(() => store.running, (running) => {
  if (running) showAnalysis.value = true
})

function goBackToConfig() {
  showAnalysis.value = false
  ws.disconnect()
  store.reset()
}

function saveReport() {
  let report = store.finalReport
  // Fallback: assemble from sections if finalReport not yet set
  if (!report) {
    const parts: string[] = []
    for (const [section, text] of Object.entries(store.reportSections)) {
      if (text) {
        const title = section
          .replace(/_/g, ' ')
          .replace(/\b\w/g, (c: string) => c.toUpperCase())
        parts.push(`# ${title}\n\n${text}`)
      }
    }
    report = parts.join('\n\n---\n\n')
  }
  if (!report) return

  const ticker = Object.keys(store.agentStatuses)[0] || 'report'
  const date = new Date().toISOString().slice(0, 10)
  const blob = new Blob([report], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${ticker}_analysis_${date}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function updateContainerWidth() {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.clientWidth
  }
}

function cancelAnalysis() {
  ws.cancelAnalysis()
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  updateContainerWidth()
  resizeObserver = new ResizeObserver(updateContainerWidth)
  if (containerRef.value) {
    resizeObserver.observe(containerRef.value)
  }
  ws.connect()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  ws.disconnect()
})
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
  overflow: hidden;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.app-header h1 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-green);
  margin: 0;
}

.subtitle {
  font-size: 12px;
  color: var(--text-dim);
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.connected { background: var(--color-green); }
.status-dot.disconnected { background: var(--color-red); }

.status-label {
  font-size: 12px;
  color: var(--text-dim);
}

.cancel-btn,
.back-btn,
.save-btn {
  padding: 3px 12px;
  font-size: 12px;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.cancel-btn {
  border: 1px solid var(--color-red);
  color: var(--color-red);
}

.cancel-btn:hover {
  background: rgba(239, 83, 80, 0.15);
}

.back-btn {
  border: 1px solid var(--color-blue);
  color: var(--color-blue);
}

.back-btn:hover {
  background: rgba(66, 165, 245, 0.15);
}

.save-btn {
  border: 1px solid var(--color-green);
  color: var(--color-green);
}

.save-btn:hover {
  background: rgba(76, 175, 80, 0.15);
}

.error-banner {
  padding: 6px 16px;
  background: rgba(239, 83, 80, 0.12);
  color: var(--color-red);
  font-size: 12px;
  border-bottom: 1px solid rgba(239, 83, 80, 0.25);
  flex-shrink: 0;
}

.panels-container {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
