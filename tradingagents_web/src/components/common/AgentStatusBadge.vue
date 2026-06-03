<template>
  <span class="badge" :class="status">
    <span v-if="status === 'in_progress'" class="spinner" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const label = computed(() => {
  switch (props.status) {
    case 'in_progress': return 'in_progress'
    case 'completed': return 'completed'
    case 'error': return 'error'
    default: return 'pending'
  }
})
</script>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.pending {
  background: rgba(255, 202, 40, 0.15);
  color: var(--color-yellow);
}

.in_progress {
  background: rgba(66, 165, 245, 0.15);
  color: var(--color-blue);
}

.completed {
  background: rgba(76, 175, 80, 0.15);
  color: var(--color-green);
}

.error {
  background: rgba(239, 83, 80, 0.15);
  color: var(--color-red);
}

.spinner {
  width: 8px;
  height: 8px;
  border: 2px solid transparent;
  border-top-color: var(--color-blue);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
