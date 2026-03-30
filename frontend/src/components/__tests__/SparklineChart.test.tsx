import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { SparklineChart } from '../SparklineChart'

describe('SparklineChart', () => {
  it('renders a canvas element with data', () => {
    const { container } = render(<SparklineChart data={[10, 20, 15, 25, 30]} />)
    const canvas = container.querySelector('canvas')
    expect(canvas).toBeInTheDocument()
  })

  it('renders placeholder when data has fewer than 2 points', () => {
    const { container } = render(<SparklineChart data={[10]} />)
    const canvas = container.querySelector('canvas')
    expect(canvas).not.toBeInTheDocument()
    expect(container.textContent).toBe('—')
  })

  it('renders placeholder for empty data', () => {
    const { container } = render(<SparklineChart data={[]} />)
    expect(container.querySelector('canvas')).not.toBeInTheDocument()
  })
})
