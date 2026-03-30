import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock EventSource
class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  readyState = 0
  close = vi.fn()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }
}

describe('useSSE', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('EventSource mock is available', () => {
    const es = new EventSource('http://test/stream')
    expect(es).toBeDefined()
    expect(MockEventSource.instances).toHaveLength(1)
  })
})
