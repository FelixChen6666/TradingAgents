import { ref } from 'vue'

const MIN_WIDTH = 200
const MAX_PROPORTION = 0.4

export function usePanelLayout(containerWidth: number) {
  const leftWidth = ref(320)
  const rightWidth = ref(400)

  function onSplitterResize(delta: number, side: 'left' | 'right') {
    if (side === 'left') {
      leftWidth.value = Math.max(MIN_WIDTH, Math.min(leftWidth.value + delta, containerWidth * MAX_PROPORTION))
    } else {
      rightWidth.value = Math.max(MIN_WIDTH, Math.min(rightWidth.value - delta, containerWidth * MAX_PROPORTION))
    }
  }

  return { leftWidth, rightWidth, onSplitterResize }
}
