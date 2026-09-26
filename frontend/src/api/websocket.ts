/**
 * Creates a WebSocket connection to the backend job stream.
 * The Vite proxy forwards /ws/* to ws://localhost:8000/ws/*
 */
export function createJobSocket(
  jobId: string,
  onMessage: (data: Record<string, unknown>) => void,
  onClose?: () => void,
): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/${jobId}`)

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data as string) as Record<string, unknown>
      onMessage(data)
    } catch {
      // raw text line — wrap it
      onMessage({ event: 'raw', line: event.data })
    }
  }

  ws.onclose = () => onClose?.()

  return ws
}
