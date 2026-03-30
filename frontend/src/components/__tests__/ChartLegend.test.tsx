import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChartLegend } from '../ChartLegend'

describe('ChartLegend', () => {
  it('renders legend items', () => {
    render(
      <ChartLegend items={[
        { label: 'Sentiment Price', color: '#3b82f6', style: 'solid' },
        { label: 'Real Price', color: '#94a3b8', style: 'dashed' },
      ]} />
    )
    expect(screen.getByText('Sentiment Price')).toBeInTheDocument()
    expect(screen.getByText('Real Price')).toBeInTheDocument()
  })

  it('renders empty when no items', () => {
    const { container } = render(<ChartLegend items={[]} />)
    expect(container.querySelector('.flex')).toBeInTheDocument()
  })
})
