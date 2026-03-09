import { useState } from 'react'
import { MarketTable } from './components/MarketTable'
import { TickerDetail } from './components/TickerDetail'

export default function App() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold tracking-tight">
              Sentiment Stock Exchange
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Reddit sentiment → synthetic price
            </p>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Ticker detail panel (shown when a ticker is selected) */}
        {selectedTicker && (
          <TickerDetail
            ticker={selectedTicker}
            onClose={() => setSelectedTicker(null)}
          />
        )}

        {/* Market overview table */}
        <MarketTable
          onSelectTicker={setSelectedTicker}
          selectedTicker={selectedTicker}
        />
      </main>
    </div>
  )
}
