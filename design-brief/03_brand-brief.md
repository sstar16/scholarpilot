I'm designing UI for ScholarPilot — a Chinese academic research intelligence platform. Before any page design, absorb these constraints.

## DESIGN SYSTEM (locked, do not deviate)

**Name:** Ink & Signal — Chinese ink wash meets scientific instruments.

**Ink palette (9 steps, light theme primary):**
```
#0a0e14  #111827  #1a2233  #243044  #334155
#475569  #64748b  #94a3b8  #cbd5e1  #e8edf3
```

**Signal colors (functional accents, use sparingly):**
- Teal `#0d9488` — primary action
- Amber `#d97706` — warning
- Coral `#dc2626` — destructive
- Blue `#2563eb` — info
- Emerald `#059669` — success

**Paper surfaces:**
`#ffffff` / `#fefcf9` (warm) / `#f8fafc` (cool) / `#f1f5f9` (hover)

**Typography:**
- Display: `Noto Serif SC`, `Georgia`, `Songti SC` — for page titles, section headers, card titles
- Body: `DM Sans`, `PingFang SC`, `Microsoft YaHei`
- Mono: `JetBrains Mono`, `Fira Code`

**Radius scale:** 6 / 10 / 14 / 20 / pill(100px)

**Shadows:** layered paper effect (subtle, no harsh drop shadows).
Example: `0 4px 16px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)`

**Motion:** `cubic-bezier(0.22, 1, 0.36, 1)` easing, 150–400ms.
Spring variant: `cubic-bezier(0.34, 1.56, 0.64, 1)` for tactile feedback.

## AESTHETIC DIRECTION

- 科研仪器 feel: precise, editorial, restrained density
- Chinese literary sensibility: `Noto Serif SC` for headings brings ink-wash warmth
- **NOT** typical "AI SaaS" — no purple gradients, no Inter, no generic cards, no dark-mode-default
- Light theme primary; dark theme comes later
- Information density **moderate** — not dashboard-dense, not marketing-airy

## USERS

中国研究生 + 科研人员. Reads lots of English papers, uses Chinese UI.
Needs both dense data views (search results, paper metadata) and chat-focused views.

## PRODUCT STRUCTURE (three core features)

1. **Search** — multi-source academic retrieval, AI summary, feedback loops update user profile
2. **Collaboration mode** — chat against a curated literature library (only when library not empty)
3. **Scheduled monitoring** — daily auto-search, updates library in background

Three entry scenarios after project creation:
- Fresh project (round 0) → run search flow
- Has rounds, library empty → new round or monitoring
- Has rounds, library non-empty → new round, monitoring, or **collaboration**

## OUTPUT RULES

- All UI labels: **中文**
- Export code: **HTML prototype** (I'll translate to Vue 3 + Element Plus myself)
- Do not use component libraries (no Tailwind, no Bootstrap, no shadcn) — vanilla CSS so tokens stay readable

## FIRST TASK

Acknowledge the system. Generate a **style guide page** as interactive HTML containing:

1. Color swatches (all ink + signal + paper with hex labels)
2. Type scale (H1/H2/H3/body/caption/mono with actual Noto Serif SC + DM Sans loaded)
3. Button states (primary/secondary/text/danger × default/hover/active/disabled)
4. Card variants (default / hover-lifted / selected)
5. Message bubbles (user / AI / system confirmation / rich card container)
6. Form elements (input/select/checkbox/radio/textarea with focus states)
7. Tag/chip variants (domain / status / filter)
8. Shadow tiers demo (xs / sm / md / lg / xl with captions)

This is the visual source of truth. Keep copy minimal — no marketing language.

I will attach `design-system.css` and 5 current-state screenshots next.
