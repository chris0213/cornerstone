import { ref } from 'vue'

type AnimationMode =
  | 'default'
  | 'username'
  | 'password'
  | 'captcha'
  | 'login-click'
  | 'login-loading'
  | 'login-success'
  | 'login-fail'

export interface StarNode {
  id: number
  /** 百分比坐标（0-100），相对插画区域 */
  x: number
  y: number
  radius: number
  opacity: number
  accent: boolean
  /** 构图锚点：更大更亮，带光晕 */
  anchor: boolean
  /** 闪烁节奏，让星点不同步 */
  delay: number
  duration: number
  pulse: boolean
}

export interface StarLink {
  from: number
  to: number
  opacity: number
}

/** 固定种子，保证每次刷新构图一致 */
function mulberry32(seed: number) {
  let t = seed
  return () => {
    t += 0x6d2b79f5
    let r = Math.imul(t ^ (t >>> 15), 1 | t)
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r)
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296
  }
}

const random = mulberry32(20261111)

function gaussian() {
  let u = 0
  let v = 0
  while (u === 0) u = random()
  while (v === 0) v = random()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

/** 文字安全区：Logo 与标语两处椭圆区域不放星点 */
function inTextSafeZone(x: number, y: number) {
  const logo = ((x - 50) / 27) ** 2 + ((y - 23) / 9) ** 2 < 1
  const slogan = ((x - 50) / 32) ** 2 + ((y - 61) / 10) ** 2 < 1
  return logo || slogan
}

interface ClusterSpec {
  cx: number
  cy: number
  spreadX: number
  spreadY: number
  count: number
  minRadius: number
  maxRadius: number
  minOpacity: number
  maxOpacity: number
  accentRate: number
}

/**
 * 三层构图：左中上主星座（视觉重心）→ 右下副星座（与卡片对角呼应）
 * → 左下与四周星尘（疏密层次），非均匀铺满。
 */
const CLUSTERS: ClusterSpec[] = [
  { cx: 33, cy: 30, spreadX: 12, spreadY: 10, count: 20, minRadius: 1.2, maxRadius: 3.2, minOpacity: 0.55, maxOpacity: 0.95, accentRate: 0.45 },
  { cx: 63, cy: 66, spreadX: 11, spreadY: 9, count: 11, minRadius: 0.9, maxRadius: 2.2, minOpacity: 0.4, maxOpacity: 0.8, accentRate: 0.3 },
  { cx: 18, cy: 63, spreadX: 9, spreadY: 11, count: 9, minRadius: 0.7, maxRadius: 1.7, minOpacity: 0.3, maxOpacity: 0.65, accentRate: 0.2 }
]

const DUST_COUNT = 30

function buildNodes() {
  const nodes: StarNode[] = []
  const clusters: number[][] = []

  const pushNode = (spec: {
    x: number
    y: number
    radius: number
    opacity: number
    accent: boolean
    anchor?: boolean
  }) => {
    nodes.push({
      id: nodes.length,
      x: Math.min(98, Math.max(2, spec.x)),
      y: Math.min(98, Math.max(2, spec.y)),
      radius: spec.radius,
      opacity: spec.opacity,
      accent: spec.accent,
      anchor: spec.anchor ?? false,
      delay: random() * 6,
      duration: random() * 4 + 4,
      pulse: false
    })
    return nodes.length - 1
  }

  CLUSTERS.forEach((cluster) => {
    const indices: number[] = []
    let attempts = 0
    while (indices.length < cluster.count && attempts < cluster.count * 30) {
      attempts++
      const x = cluster.cx + gaussian() * cluster.spreadX
      const y = cluster.cy + gaussian() * cluster.spreadY
      if (x < 3 || x > 97 || y < 3 || y > 97 || inTextSafeZone(x, y)) continue

      const weight = (indices.length + 1) / cluster.count
      const radius =
        cluster.minRadius + (cluster.maxRadius - cluster.minRadius) * (0.35 + 0.65 * weight) * (0.75 + random() * 0.5)
      const anchor = indices.length < 2 && cluster.cx < 40
      indices.push(
        pushNode({
          x,
          y,
          radius: Math.min(cluster.maxRadius + 0.4, radius) * (anchor ? 1.15 : 1),
          opacity: cluster.minOpacity + (cluster.maxOpacity - cluster.minOpacity) * random(),
          accent: random() < cluster.accentRate,
          anchor
        })
      )
    }
    clusters.push(indices)
  })

  // 星尘：越靠近主焦点越密，向右下逐渐稀疏
  let dust = 0
  let guard = 0
  while (dust < DUST_COUNT && guard < DUST_COUNT * 40) {
    guard++
    const x = random() * 96 + 2
    const y = random() * 96 + 2
    const focus = Math.hypot(x - 33, (y - 30) * 1.15)
    // 距离主焦点越远，保留概率越低
    if (random() > Math.max(0.12, 1 - focus / 95)) continue
    if (inTextSafeZone(x, y)) continue
    pushNode({
      x,
      y,
      radius: 0.5 + random() * 0.9,
      opacity: 0.2 + random() * 0.35,
      accent: random() < 0.15
    })
    dust++
  }

  return { nodes, clusters }
}

function buildLinks(nodes: StarNode[], clusters: number[][]): StarLink[] {
  const links: StarLink[] = []
  const seen = new Set<string>()

  const addLink = (from: number, to: number, opacity: number) => {
    if (from === to) return
    const key = from < to ? `${from}-${to}` : `${to}-${from}`
    if (seen.has(key)) return
    seen.add(key)
    links.push({ from, to, opacity })
  }

  const connectWithin = (indices: number[], maxDistance: number, maxPerNode: number) => {
    indices.forEach((index) => {
      const node = nodes[index]
      nodes
        .filter((_, i) => indices.includes(i) && i !== index)
        .map((other) => ({
          index: nodes.indexOf(other),
          distance: Math.hypot(other.x - node.x, other.y - node.y)
        }))
        .filter((item) => item.distance < maxDistance)
        .sort((a, b) => a.distance - b.distance)
        .slice(0, maxPerNode)
        .forEach(({ index: otherIndex, distance }) => {
          addLink(index, otherIndex, Math.max(0.08, 0.3 - distance / 110))
        })
    })
  }

  connectWithin(clusters[0], 26, 2)
  connectWithin(clusters[1], 24, 2)
  connectWithin(clusters[2], 22, 1)

  // 斜向桥接：主星座 → 右下副星座/左下星尘，形成指向右侧卡片的对角走势
  const primary = clusters[0]
  const secondary = clusters[1]
  const tertiary = clusters[2]
  if (primary.length && secondary.length) {
    addLink(primary[0], secondary[0], 0.22)
    addLink(primary[1] ?? primary[0], secondary[secondary.length - 1], 0.16)
  }
  if (primary.length && tertiary.length) {
    addLink(primary[0], tertiary[0], 0.14)
  }

  return links
}

const { nodes: initialNodes, clusters } = buildNodes()
const nodes = ref<StarNode[]>(initialNodes)
const links = ref<StarLink[]>(buildLinks(initialNodes, clusters))
const animationMode = ref<AnimationMode>('default')
const hasEntered = ref(false)
const illustrationRef = ref<HTMLElement | null>(null)

let pulseTimer: number | null = null

export function useNetworkAnimation() {
  const setAnimationMode = (mode: AnimationMode) => {
    animationMode.value = mode
    if (mode === 'login-success' || mode === 'login-fail') {
      window.setTimeout(() => {
        animationMode.value = 'default'
      }, 900)
    }
  }

  const triggerNodePulse = () => {
    if (nodes.value.length === 0) return
    const node = nodes.value[Math.floor(Math.random() * nodes.value.length)]
    node.pulse = true
    if (pulseTimer) window.clearTimeout(pulseTimer)
    pulseTimer = window.setTimeout(() => {
      node.pulse = false
    }, 450)
  }

  const markEntered = () => {
    hasEntered.value = true
  }

  return {
    illustrationRef,
    nodes,
    links,
    hasEntered,
    animationMode,
    setAnimationMode,
    triggerNodePulse,
    markEntered
  }
}
