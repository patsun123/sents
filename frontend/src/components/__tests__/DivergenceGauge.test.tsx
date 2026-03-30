import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { DivergenceGauge } from '../DivergenceGauge'

describe('DivergenceGauge', () => {
  it('shows positive divergence', () => {
    const { container } = render(
      <DivergenceGauge sentimentPrice={110} realPrice={100} />
    )
    expect(container.textContent).toContain('+10.0%')
  })

  it('shows negative divergence', () => {
    const { container } = render(
      <DivergenceGauge sentimentPrice={90} realPrice={100} />
    )
    expect(container.textContent).toContain('-10.0%')
  })

  it('renders placeholder for null prices', () => {
    const { container } = render(
      <DivergenceGauge sentimentPrice={null} realPrice={100} />
    )
    expect(container.textContent).toBe('—')
  })

  it('renders placeholder for zero real price', () => {
    const { container } = render(
      <DivergenceGauge sentimentPrice={110} realPrice={0} />
    )
    expect(container.textContent).toBe('—')
  })

  it('supports md size', () => {
    const { container } = render(
      <DivergenceGauge sentimentPrice={110} realPrice={100} size="md" />
    )
    expect(container.textContent).toContain('+10.0%')
  })
})
