<template>
  <div class="searching-animation">
    <canvas ref="canvasRef" width="120" height="120" class="particle-canvas"></canvas>
    <transition name="status-fade" mode="out-in">
      <p class="status-text" :key="displayText">{{ displayText }}</p>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps<{
  status?: string
  message?: string
  docCount?: number
  summaryCount?: number
  currentSource?: string
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const displayText = ref('正在准备检索...')
let animId = 0

// --- Status text logic ---
watch(() => [props.status, props.message, props.docCount, props.summaryCount, props.currentSource], () => {
  if (props.message) {
    displayText.value = props.message
    return
  }
  if (props.status === 'searching') {
    if (props.currentSource) {
      displayText.value = `正在检索 ${props.currentSource}...`
    } else if (props.docCount && props.docCount > 0) {
      displayText.value = `已发现 ${props.docCount} 篇相关文献`
    } else {
      displayText.value = '正在从多个数据库检索文献...'
    }
  } else if (props.status === 'summarizing') {
    if (props.summaryCount && props.summaryCount > 0) {
      displayText.value = `已完成 ${props.summaryCount} 篇摘要生成`
    } else {
      displayText.value = '正在生成 AI 摘要...'
    }
  }
}, { immediate: true })

// --- Particle system ---
interface Particle {
  x: number; y: number
  targetX: number; targetY: number
  originX: number; originY: number
  color: string
  radius: number
  phase: number // 0=scatter, 1=converge, 2=hold, 3=disperse
}

const COLORS = ['#409eff', '#409eff', '#409eff', '#6e40c9', '#53a8ff', '#7c5ce7']
const PARTICLE_COUNT = 30
const W = 120, H = 120, CX = W / 2, CY = H / 2

// Generate "SP" letter target positions (simplified dot pattern)
function generateSPTargets(): { x: number; y: number }[] {
  const points: { x: number; y: number }[] = []
  // S shape
  const S = [
    [38,30],[34,34],[30,38],[30,42],[34,46],[38,50],[42,54],[42,58],[38,62],[34,62],[30,58],
  ]
  // P shape
  const P = [
    [58,30],[58,36],[58,42],[58,48],[58,54],[58,60],
    [62,30],[68,30],[74,32],[76,36],[76,40],[74,44],[68,46],[62,46],
  ]
  for (const [x, y] of S) points.push({ x, y })
  for (const [x, y] of P) points.push({ x, y })
  // Pad with extras near center if we need more
  while (points.length < PARTICLE_COUNT) {
    points.push({
      x: CX + (Math.random() - 0.5) * 40,
      y: CY + (Math.random() - 0.5) * 40,
    })
  }
  return points.slice(0, PARTICLE_COUNT)
}

function randomEdge(): { x: number; y: number } {
  const side = Math.floor(Math.random() * 4)
  switch (side) {
    case 0: return { x: Math.random() * W, y: -10 }
    case 1: return { x: W + 10, y: Math.random() * H }
    case 2: return { x: Math.random() * W, y: H + 10 }
    default: return { x: -10, y: Math.random() * H }
  }
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const targets = generateSPTargets()
  const particles: Particle[] = targets.map((t, i) => {
    const origin = randomEdge()
    return {
      x: origin.x, y: origin.y,
      targetX: t.x, targetY: t.y,
      originX: origin.x, originY: origin.y,
      color: COLORS[i % COLORS.length],
      radius: 2.2 + Math.random() * 1.2,
      phase: 0,
    }
  })

  let cycleTime = 0
  const CONVERGE_DURATION = 1200
  const HOLD_DURATION = 1200
  const DISPERSE_DURATION = 800
  const TOTAL_CYCLE = CONVERGE_DURATION + HOLD_DURATION + DISPERSE_DURATION
  let lastTime = performance.now()

  function animate(now: number) {
    const dt = now - lastTime
    lastTime = now
    cycleTime = (cycleTime + dt) % TOTAL_CYCLE

    ctx!.clearRect(0, 0, W, H)

    for (const p of particles) {
      let progress: number

      if (cycleTime < CONVERGE_DURATION) {
        // Phase: converge
        progress = cycleTime / CONVERGE_DURATION
        const ease = 1 - Math.pow(1 - progress, 3) // easeOutCubic
        p.x = p.originX + (p.targetX - p.originX) * ease
        p.y = p.originY + (p.targetY - p.originY) * ease
      } else if (cycleTime < CONVERGE_DURATION + HOLD_DURATION) {
        // Phase: hold with breathing
        const holdT = (cycleTime - CONVERGE_DURATION) / HOLD_DURATION
        const breath = 1 + 0.04 * Math.sin(holdT * Math.PI * 4)
        p.x = CX + (p.targetX - CX) * breath
        p.y = CY + (p.targetY - CY) * breath
      } else {
        // Phase: disperse
        progress = (cycleTime - CONVERGE_DURATION - HOLD_DURATION) / DISPERSE_DURATION
        const ease = progress * progress // easeInQuad
        p.x = p.targetX + (p.originX - p.targetX) * ease
        p.y = p.targetY + (p.originY - p.targetY) * ease
        // Reset origin for next cycle when disperse ends
        if (progress > 0.95) {
          const newOrigin = randomEdge()
          p.originX = newOrigin.x
          p.originY = newOrigin.y
        }
      }

      // Draw particle with glow
      ctx!.beginPath()
      ctx!.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
      ctx!.fillStyle = p.color
      ctx!.shadowColor = p.color
      ctx!.shadowBlur = 6
      ctx!.fill()
      ctx!.shadowBlur = 0
    }

    // Draw faint connecting lines between nearby particles (during hold phase)
    if (cycleTime >= CONVERGE_DURATION && cycleTime < CONVERGE_DURATION + HOLD_DURATION) {
      const lineAlpha = 0.12
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < 20) {
            ctx!.beginPath()
            ctx!.moveTo(particles[i].x, particles[i].y)
            ctx!.lineTo(particles[j].x, particles[j].y)
            ctx!.strokeStyle = `rgba(64, 158, 255, ${lineAlpha * (1 - dist / 20)})`
            ctx!.lineWidth = 0.5
            ctx!.stroke()
          }
        }
      }
    }

    animId = requestAnimationFrame(animate)
  }

  animId = requestAnimationFrame(animate)
})

onUnmounted(() => {
  if (animId) cancelAnimationFrame(animId)
})
</script>

<style scoped>
.searching-animation {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 0 16px;
}

.particle-canvas {
  width: 120px;
  height: 120px;
}

.status-text {
  margin: 12px 0 0;
  font-size: 14px;
  color: #606266;
  text-align: center;
  min-height: 22px;
  letter-spacing: 0.5px;
}

.status-fade-enter-active,
.status-fade-leave-active {
  transition: opacity 0.35s ease, transform 0.35s ease;
}
.status-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.status-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
