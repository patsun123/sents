import { useRef, useEffect } from 'react'

interface Props {
  data: number[]
  width?: number
  height?: number
  color?: string
}

export function SparklineChart({ data, width = 80, height = 32, color = '#3b82f6' }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length < 2) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)

    const min = Math.min(...data)
    const max = Math.max(...data)
    const range = max - min || 1
    const padding = 2

    const stepX = (width - padding * 2) / (data.length - 1)
    const scaleY = (height - padding * 2) / range

    ctx.beginPath()
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    data.forEach((val, i) => {
      const x = padding + i * stepX
      const y = height - padding - (val - min) * scaleY
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()
  }, [data, width, height, color])

  if (data.length < 2) {
    return <span className="text-slate-600 text-xs">—</span>
  }

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height }}
      className="block"
      aria-label={`Sparkline chart: ${data.length} data points, range ${Math.min(...data).toFixed(2)}–${Math.max(...data).toFixed(2)}`}
      role="img"
    />
  )
}
