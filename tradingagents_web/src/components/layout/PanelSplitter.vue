<template>
  <div
    class="panel-splitter"
    @mousedown.prevent="startDrag"
  />
</template>

<script setup lang="ts">
const emit = defineEmits<{ resize: [delta: number] }>()

function startDrag(e: MouseEvent) {
  const startX = e.clientX

  function onMouseMove(e: MouseEvent) {
    emit('resize', e.clientX - startX)
  }

  function onMouseUp() {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}
</script>

<style scoped>
.panel-splitter {
  width: var(--splitter-width);
  min-width: var(--splitter-width);
  background: var(--splitter-color);
  cursor: col-resize;
  transition: background 0.15s;
  flex-shrink: 0;
}

.panel-splitter:hover {
  background: var(--splitter-hover);
}
</style>
