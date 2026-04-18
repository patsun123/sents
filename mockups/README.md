# Dashboard Mockups

Four alternate visual treatments of the Epic Games Store sentiment dashboard. Same data, same information architecture, four distinctly different aesthetic directions. Each file is standalone — open by double-clicking, no server or build step required.

Start at [index.html](index.html) for a navigation hub with swatches and one-line descriptions of each.

## Shared fixture

All four files embed the same deterministic mock dataset inline: 30 days of daily sentiment buckets (seeded sequence from -28 to +52), 8 communities (EpicGamesPC, GameDeals, FreeGameFindings, pcgaming, pcmasterrace, fuckepic, ShouldIbuythisgame, patientgamers) with realistic mention counts and weighted scores, and 10 recent signals with paraphrased snippets. This means visual comparisons are apples-to-apples — any differences you see come from the treatment, not the data.

All four include `<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">` plus a visible "robots: noindex" micro-note in the footer, mirroring the live site's indexing posture.

## The four directions

### A — Neon Punk ([a-neon-punk.html](a-neon-punk.html))

Gaming HUD / cyberpunk console aesthetic. Near-black canvas with a subtle scanline overlay, hot magenta + electric cyan + lime triadic accent palette, Chakra Petch for headlines (carries faint sci-fi stencil character without tipping into costume), JetBrains Mono for all numerics. Hero block uses clip-path to cut corner bevels and an animated gradient sweep across the top edge. KPI cards have HUD corner-bracket decoration. A circular gauge reading with a rotating conic gradient anchors the right rail. Charts glow; polarity indicators glow; status pulses.

**Who it's for:** The gaming audience who'd actually use this site — Reddit-native, Discord-native, comfortable with dashboards that look like game UIs. It earns attention by being loud and committing to it. The risk is tipping into try-hard; the Chakra Petch + restrained animation is what keeps it on the right side of the line.

### B — Editorial ([b-editorial.html](b-editorial.html))

FT Alphaville / magazine-style. Cream paper (#f5efe5) with deep navy ink, subtle paper grain overlay, Fraunces serif for all headlines (with `opsz` and `SOFT`/`WONK` axes pushed to bring out italic character), Instrument Sans for body, Instrument Serif for italic metadata. The storefront is treated as a story: masthead with dateline, big headline with a red-accent italic emphasis word, a lede and deck, a byline, body copy with a dropcap and pullquote, a labeled Figure 1 for the chart, and a sidebar with ranked communities. Signals are "Dispatches from the field" with pullquote formatting.

**Who it's for:** Readers who want context and interpretation, not just numbers. This treatment positions SentiX as a publication with a point of view rather than a data tool — it frames sentiment as analysis. Great for sharing on social (a pullquote is screenshottable in a way a KPI card isn't); less great for someone who wants to glance at a number in five seconds.

### C — Brutalist ([c-brutalist.html](c-brutalist.html))

Vercel / Linear / are.na light aesthetic. Off-white (#fefdf8) with a faint graph-paper grid, thick 2px black borders carving the page into rectangles, Archivo Black headlines at 900 weight, IBM Plex Mono for all uppercase labels and metadata. One accent color only — Klein blue (#2340ff) — used sparingly for tags, active-nav, and chart lines. Positive green and negative red called in only where they meaningfully disambiguate. A rotating "SENTIX REPORT" stamp gives the page a printed feel. Tables-first for communities. Signals use bordered POS/NEG/MIX chips.

**Who it's for:** Designers and developers who spend time in Linear, Vercel, and Raycast and have opinions about grid systems. This is the "serious, well-made" treatment — it broadcasts craft without being ostentatious. Probably the safest bet if you want a design the ecosystem will respect, though "safe" here means "correct" not "boring."

### D — Terminal ([d-terminal.html](d-terminal.html))

Bloomberg / tmux / vintage quote-desk aesthetic. Near-black (#0a0a0a) with a subtle CRT scanline overlay, amber (#ffb000) as primary accent, green and red for sentiment, JetBrains Mono for absolutely everything. Fixed keyboard-shortcut command bar across the top, status strip with `ENT`/`WIN`/`CLS`/`SRC` segments, a yellow-bar footer with `⌘K SEARCH` / `⌘L LOOKBACK` / `⌘R REFRESH` affordances. Charts are line-only, minimal. Communities rendered as a dense table with ASCII bar-chart distribution cells. Signal feed uses `[+]` / `[-]` polarity markers. A "tracked entities" table shows Epic Games Store, Steam, and a future GOG_GALAXY entry — the multi-storefront frame reads clearly.

**Who it's for:** Power users and finance-brain operators who want maximum density and the keyboard to do everything. This treatment sends a clear signal: "this is a serious instrument." The downside is it's less approachable on a phone, and the aesthetic choice alienates users who find it intimidating. But it's the most distinct from everything else in the gaming-tracker space, which could be a differentiator.

## Picking one

If I had to rank them for the Epic Games Store tracker specifically:

1. **A (Neon Punk)** — thematically strongest for the gaming audience
2. **C (Brutalist)** — most likely to be judged "well designed" by a general audience
3. **D (Terminal)** — most distinct from competitors, sharpest for power users
4. **B (Editorial)** — best for a blog-style write-up, weakest as an at-a-glance dashboard

But these rankings flip depending on what you optimize for: Reddit shareability, designer respect, serious-instrument signaling, or thoughtful-analysis positioning. Open all four side by side and see which makes you want to keep looking.

## Next steps (once you've picked one)

1. Reply with the chosen letter(s).
2. I'll port the winning treatment into `api/src/dashboard.html` (the file the FastAPI app actually serves) using your real API endpoint shapes (`/api/epic/overview`, `/api/epic/sentiment-history`, `/api/epic/communities`, `/api/epic/recent-signals`).
3. Deploy via the existing GitHub Actions pipeline.

If you want to blend (e.g., "C's layout but A's color palette"), that's fine — mockups are disposable artifacts, not commitments.
