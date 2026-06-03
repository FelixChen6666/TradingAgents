<template>
  <div class="panel messages-panel">
    <div class="panel-header">消息与工具</div>
    <div class="panel-body" ref="scrollRef" @scroll="onScroll">
      <div v-if="entries.length === 0" class="empty-state">
        等待消息...
      </div>
      <template v-else>
        <MessageEntry v-for="entry in entries" :key="entry.id" :msg="entry" />
      </template>
      <div ref="scrollAnchor" />
    </div>
    <button v-if="showScrollBtn" class="scroll-btn" @click="scrollToBottom">
      ↓ 最新
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useAnalysisStore } from '../../stores/analysis'
import MessageEntry from '../common/MessageEntry.vue'

const store = useAnalysisStore()
const scrollRef = ref<HTMLElement | null>(null)
const scrollAnchor = ref<HTMLElement | null>(null)
const showScrollBtn = ref(false)

const entries = computed(() => {
  // Merge messages and tool calls, sort by timestamp
  const all = [
    ...store.messages.map(m => ({ ...m, _sortTime: m.timestamp })),
    ...store.toolCalls.map(tc => ({
      id: tc.id,
      timestamp: tc.timestamp,
      type: 'Tool' as const,
      content: `${tc.name}: ${JSON.stringify(tc.args)}`,
      _sortTime: tc.timestamp,
    })),
  ]
  // Show most recent first? No - oldest first, so reverse
  all.sort((a, b) => a.id - b.id)
  return all.slice(-100)
})

let autoScroll = true

watch(entries, async () => {
  if (autoScroll) {
    await nextTick()
    scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  }
})

function onScroll() {
  if (!scrollRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = scrollRef.value
  autoScroll = scrollHeight - scrollTop - clientHeight < 100
  showScrollBtn.value = !autoScroll
}

function scrollToBottom() {
  scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  showScrollBtn.value = false
  autoScroll = true
}
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-right: 1px solid var(--border-color);
  position: relative;
}

.panel-header {
  padding: var(--panel-padding);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-blue);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
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

.scroll-btn {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  padding: 4px 16px;
  font-size: 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  z-index: 10;
}

.scroll-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
</style>
