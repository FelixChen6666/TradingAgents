<template>
  <div class="tool-call-entry">
    <span class="tc-time">{{ tc.timestamp }}</span>
    <span class="tc-type">Tool</span>
    <span class="tc-name">{{ tc.name }}</span>
    <span class="tc-args">{{ formattedArgs }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ tc: { timestamp: string; name: string; args: Record<string, unknown> } }>()

const formattedArgs = computed(() => {
  try {
    const str = JSON.stringify(props.tc.args)
    return str.length > 100 ? str.slice(0, 100) + '...' : str
  } catch {
    return String(props.tc.args)
  }
})
</script>

<style scoped>
.tool-call-entry {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.4;
  border-bottom: 1px solid var(--border-subtle);
}

.tc-time {
  color: var(--text-dim);
  font-size: 12px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  min-width: 56px;
}

.tc-type {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  background: var(--color-purple);
  color: #fff;
  white-space: nowrap;
}

.tc-name {
  color: var(--color-orange);
  font-weight: 500;
}

.tc-args {
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  flex: 1;
  word-break: break-all;
}
</style>
