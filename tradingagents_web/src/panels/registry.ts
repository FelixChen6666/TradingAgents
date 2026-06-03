import { ref, type Component } from 'vue'

export interface PanelDefinition {
  id: string
  title: string
  component: Component
  defaultWidth?: number
  minWidth?: number
  defaultPosition?: 'left' | 'center' | 'right'
}

const registeredPanels = ref<PanelDefinition[]>([])

export function registerPanel(def: PanelDefinition) {
  registeredPanels.value.push(def)
}

export function usePanelRegistry() {
  return { panels: registeredPanels }
}
