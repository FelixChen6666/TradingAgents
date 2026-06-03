<template>
  <div class="status-bar">
    <span class="stat">
      代理: <strong>{{ store.agentsCompleted }}</strong>/{{ store.agentsTotal }}
    </span>
    <span class="sep">|</span>

    <span class="stat">
      LLM: <strong>{{ store.stats.llm_calls }}</strong>
    </span>
    <span class="sep">|</span>

    <span class="stat">
      工具: <strong>{{ store.stats.tool_calls }}</strong>
    </span>
    <span class="sep">|</span>

    <span class="stat">
      Token: <strong>{{ fmtTokens(store.stats.tokens_in) }}↓</strong>
      <strong>{{ fmtTokens(store.stats.tokens_out) }}↑</strong>
    </span>
    <span class="sep">|</span>

    <span class="stat">
      报告: <strong>{{ reportsCompleted }}</strong>/{{ reportsTotal }}
    </span>
    <span class="sep">|</span>

    <span class="stat time">{{ store.elapsedDisplay }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../../stores/analysis'

const store = useAnalysisStore()

const reportsCompleted = computed(() => {
  // Simplified: count non-null sections
  return Object.values(store.reportSections).filter(v => v !== null).length
})

const reportsTotal = computed(() => {
  return Object.keys(store.reportSections).length
})

function fmtTokens(n: number): string {
  if (n === 0) return '--'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  font-size: 13px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.stat strong {
  color: var(--text-primary);
  font-weight: 500;
}

.sep {
  color: var(--border-color);
  font-size: 11px;
}

.time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
</style>
