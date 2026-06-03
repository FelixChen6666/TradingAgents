<template>
  <div class="message-entry" :class="msg.type.toLowerCase()">
    <span class="msg-time">{{ msg.timestamp }}</span>
    <span class="msg-type" :style="{ background: bgColor }">{{ msg.type }}</span>
    <span class="msg-content">{{ truncated }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { MSG_TYPE_COLORS } from '../../types/ws'
import type { MessageEntry as MsgEntry } from '../../types/ws'

const props = defineProps<{ msg: MsgEntry }>()

const bgColor = computed(() => MSG_TYPE_COLORS[props.msg.type] || '#888')

const truncated = computed(() => {
  if (props.msg.content.length > 300) {
    return props.msg.content.slice(0, 300) + '...'
  }
  return props.msg.content
})
</script>

<style scoped>
.message-entry {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.4;
  border-bottom: 1px solid var(--border-subtle);
}

.msg-time {
  color: var(--text-dim);
  font-size: 12px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  min-width: 56px;
}

.msg-type {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
  min-width: 40px;
  text-align: center;
}

.msg-content {
  color: var(--text-primary);
  flex: 1;
  word-break: break-word;
}
</style>
