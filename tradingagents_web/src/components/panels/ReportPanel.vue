<template>
  <div class="panel report-panel">
    <div class="panel-header">当前报告</div>
    <div class="panel-body">
      <template v-if="content">
        <MarkdownRenderer :content="content" />
      </template>
      <div v-else class="empty-state">
        等待分析报告...
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../../stores/analysis'
import MarkdownRenderer from '../common/MarkdownRenderer.vue'

const store = useAnalysisStore()

/** Build a live report from sections during analysis, fall back to finalReport. */
const content = computed(() => {
  // After completion, use the assembled final report
  if (store.finalReport) return store.finalReport

  // During analysis, combine sections that have content
  const parts: string[] = []
  for (const [section, text] of Object.entries(store.reportSections)) {
    if (text) {
      const title = section
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c: string) => c.toUpperCase())
      parts.push(`### ${title}\n${text}`)
    }
  }
  return parts.length > 0 ? parts.join('\n\n---\n\n') : null
})
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  flex: 1;
}

.panel-header {
  padding: var(--panel-padding);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-green);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-dim);
  font-size: 13px;
  font-style: italic;
}
</style>
