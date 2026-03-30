interface LegendItem {
  label: string
  color: string
  style?: 'solid' | 'dashed' | 'dotted'
}

interface Props {
  items: LegendItem[]
}

export function ChartLegend({ items }: Props) {
  return (
    <div className="flex flex-wrap gap-4 px-2 py-2">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-2">
          <div className="w-5 h-0 border-t-2" style={{
            borderColor: item.color,
            borderStyle: item.style ?? 'solid',
          }} />
          <span className="text-xs text-slate-400">{item.label}</span>
        </div>
      ))}
    </div>
  )
}
