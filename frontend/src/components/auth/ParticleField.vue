<template>
  <canvas ref="canvasRef" class="particle-field" />
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'

interface FocusPoint { x: number; y: number }

const props = withDefaults(
  defineProps<{
    focusPoint?: FocusPoint | null
    accelerate?: boolean
    densityMult?: number
    glowColor?: string
  }>(),
  {
    focusPoint: null,
    accelerate: false,
    densityMult: 1.0,
    glowColor: '#c6ac57',
  }
)

const canvasRef = ref<HTMLCanvasElement | null>(null)

type Particle = {
  x: number; y: number
  vx: number; vy: number
  r: number; baseR: number
  twinkle: number
}

type Trail = { x: number; y: number; vx: number; len: number; life: number }

const state = {
  focus: null as FocusPoint | null,
  accel: false,
  mouse: { x: -9999, y: -9999 },
}

watch(() => props.focusPoint, (v) => { state.focus = v }, { immediate: true })
watch(() => props.accelerate, (v) => { state.accel = v }, { immediate: true })

let raf = 0
let ro: ResizeObserver | null = null

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

function start() {
  const c = canvasRef.value
  if (!c) return
  const ctx = c.getContext('2d')
  if (!ctx) return

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  let w = 0
  let h = 0

  const N = Math.round(90 * props.densityMult)
  const pts: Particle[] = Array.from({ length: N }, () => ({
    x: Math.random(),
    y: Math.random(),
    vx: (Math.random() - 0.5) * 0.0004,
    vy: (Math.random() - 0.5) * 0.0004,
    r: Math.random() * 1.6 + 0.5,
    baseR: 0,
    twinkle: Math.random() * Math.PI * 2,
  }))
  pts.forEach((p) => { p.baseR = p.r })

  const trails: Trail[] = Array.from({ length: 6 }, () => ({
    x: Math.random(),
    y: Math.random() * 0.6,
    vx: 0.0003 + Math.random() * 0.0004,
    len: 80 + Math.random() * 120,
    life: Math.random(),
  }))

  const resize = () => {
    const r = c.getBoundingClientRect()
    w = r.width
    h = r.height
    c.width = w * dpr
    c.height = h * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()

  const onMove = (e: PointerEvent) => {
    const r = c.getBoundingClientRect()
    state.mouse.x = e.clientX - r.left
    state.mouse.y = e.clientY - r.top
  }
  const onLeave = () => {
    state.mouse.x = -9999
    state.mouse.y = -9999
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerleave', onLeave)

  const [gr, gg, gb] = hexToRgb(props.glowColor)

  const tick = () => {
    ctx.clearRect(0, 0, w, h)
    const { focus, accel, mouse } = state
    const speedMult = accel ? 3.2 : 1

    // Star trails
    for (const tr of trails) {
      tr.x += tr.vx * speedMult
      tr.life += 0.004
      if (tr.x > 1.2 || tr.life > 1) {
        tr.x = -0.1
        tr.y = Math.random() * 0.7
        tr.life = 0
      }
      const alpha = Math.sin(tr.life * Math.PI) * 0.4
      const x = tr.x * w
      const y = tr.y * h
      const g = ctx.createLinearGradient(x - tr.len, y, x, y)
      g.addColorStop(0, `rgba(${gr},${gg},${gb},0)`)
      g.addColorStop(1, `rgba(${gr},${gg},${gb},${alpha})`)
      ctx.strokeStyle = g
      ctx.lineWidth = 1.2
      ctx.beginPath()
      ctx.moveTo(x - tr.len, y)
      ctx.lineTo(x, y)
      ctx.stroke()
    }

    // Particles physics
    for (const p of pts) {
      p.twinkle += 0.04
      const nx = p.x * w
      const ny = p.y * h
      const mdx = mouse.x - nx
      const mdy = mouse.y - ny
      const md = Math.hypot(mdx, mdy)
      if (md < 180 && md > 1) {
        const f = (180 - md) / 180 * 0.00012
        p.vx += (mdx / md) * f
        p.vy += (mdy / md) * f
      }
      if (focus) {
        const fdx = focus.x - nx
        const fdy = focus.y - ny
        const fd = Math.hypot(fdx, fdy)
        if (fd > 1) {
          const f = 0.00006
          p.vx += (fdx / fd) * f
          p.vy += (fdy / fd) * f
        }
      }
      p.vx *= 0.985
      p.vy *= 0.985
      p.x += p.vx * speedMult
      p.y += p.vy * speedMult
      if (p.x < 0) { p.x = 0; p.vx *= -0.6 }
      if (p.x > 1) { p.x = 1; p.vx *= -0.6 }
      if (p.y < 0) { p.y = 0; p.vy *= -0.6 }
      if (p.y > 1) { p.y = 1; p.vy *= -0.6 }
    }

    // Connecting lines
    ctx.lineWidth = 0.5
    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        const a = pts[i]
        const b = pts[j]
        const dx = (a.x - b.x) * w
        const dy = (a.y - b.y) * h
        const d = Math.hypot(dx, dy)
        if (d < 120) {
          const alpha = (1 - d / 120) * 0.28
          ctx.strokeStyle = `rgba(${gr},${gg},${gb},${alpha})`
          ctx.beginPath()
          ctx.moveTo(a.x * w, a.y * h)
          ctx.lineTo(b.x * w, b.y * h)
          ctx.stroke()
        }
      }
    }

    // Dots with twinkle + glow
    for (const p of pts) {
      const tw = 0.7 + Math.sin(p.twinkle) * 0.3
      const r = p.baseR * tw
      const x = p.x * w
      const y = p.y * h
      const g = ctx.createRadialGradient(x, y, 0, x, y, r * 5)
      g.addColorStop(0, `rgba(${gr},${gg},${gb},${0.55 * tw})`)
      g.addColorStop(1, `rgba(${gr},${gg},${gb},0)`)
      ctx.fillStyle = g
      ctx.beginPath()
      ctx.arc(x, y, r * 5, 0, Math.PI * 2)
      ctx.fill()
      ctx.fillStyle = `rgba(${gr + 20},${gg + 20},${gb + 20},${0.9 * tw})`
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }

    raf = requestAnimationFrame(tick)
  }
  tick()

  ro = new ResizeObserver(resize)
  ro.observe(c)

  // Cleanup refs closed over
  ;(canvasRef as any)._cleanup = () => {
    cancelAnimationFrame(raf)
    ro?.disconnect()
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerleave', onLeave)
  }
}

onMounted(start)
onBeforeUnmount(() => {
  ;(canvasRef as any)._cleanup?.()
})
</script>

<style scoped>
.particle-field {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
