<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ content: string }>()

const rendered = computed(() => {
  try {
    return marked(props.content, { async: false }) as string
  } catch {
    return props.content
  }
})
</script>
