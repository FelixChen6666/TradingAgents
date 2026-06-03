type EventHandler = (payload: unknown) => void

const listeners = new Map<string, Set<EventHandler>>()

export function useEventBus() {
  function on(eventType: string, handler: EventHandler): () => void {
    if (!listeners.has(eventType)) {
      listeners.set(eventType, new Set())
    }
    listeners.get(eventType)!.add(handler)
    return () => listeners.get(eventType)!.delete(handler)
  }

  function emit(eventType: string, payload: unknown) {
    listeners.get(eventType)?.forEach(h => h(payload))
  }

  return { on, emit }
}
