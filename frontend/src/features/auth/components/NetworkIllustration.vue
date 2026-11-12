<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBrandStore } from '@/store/brand'
import { useNetworkAnimation } from '../composables/useNetworkAnimation'

const { t } = useI18n()
const brandStore = useBrandStore()

const { illustrationRef, nodes, links, hasEntered, animationMode, markEntered } = useNetworkAnimation()

const companyLogo = ref<string>('')

const loadLogo = async () => {
  try {
    const response = await fetch('/api/v1/settings/logo')
    const data = await response.json()
    if (data && data.value) {
      companyLogo.value = `data:image/png;base64,${data.value}`
    }
  } catch (error) {
    console.warn('加载Logo失败，使用默认Logo:', error)
  }
}

onMounted(() => {
  loadLogo()
  // 下一帧再淡入，避免首屏闪现半透明
  requestAnimationFrame(markEntered)
})
</script>

<template>
  <div class="login-illustration" ref="illustrationRef">
    <div
      class="starfield"
      :class="{
        entered: hasEntered,
        'login-success': animationMode === 'login-success',
        'login-fail': animationMode === 'login-fail'
      }"
      aria-hidden="true"
    >
      <svg class="starfield-svg">
        <defs>
          <radialGradient id="starfieldGlow">
            <stop offset="0%" stop-color="var(--color-accent-on-dark)" stop-opacity="0.2" />
            <stop offset="55%" stop-color="var(--color-accent-on-dark)" stop-opacity="0.07" />
            <stop offset="100%" stop-color="var(--color-accent-on-dark)" stop-opacity="0" />
          </radialGradient>
        </defs>
        <!-- 主星座柔光：把视觉重心固定在中部偏上 -->
        <ellipse cx="33%" cy="31%" rx="36%" ry="32%" fill="url(#starfieldGlow)" />
        <g class="star-links">
          <line
            v-for="(link, index) in links"
            :key="'link-' + index"
            :x1="nodes[link.from]?.x + '%'"
            :y1="nodes[link.from]?.y + '%'"
            :x2="nodes[link.to]?.x + '%'"
            :y2="nodes[link.to]?.y + '%'"
            :style="{ opacity: link.opacity }"
            class="star-link"
          />
        </g>
        <g class="star-nodes">
          <template v-for="node in nodes" :key="'node-' + node.id">
            <circle
              :cx="node.x + '%'"
              :cy="node.y + '%'"
              :r="node.radius * 3.2"
              class="star-halo"
              :class="{ accent: node.accent, anchor: node.anchor }"
              :style="{ opacity: node.opacity * (node.anchor ? 0.24 : 0.13) }"
            />
            <circle
              :cx="node.x + '%'"
              :cy="node.y + '%'"
              :r="node.radius"
              class="star-core"
              :class="{ accent: node.accent, anchor: node.anchor, lit: node.pulse }"
              :style="{
                '--tw': node.opacity,
                animationDelay: node.delay + 's',
                animationDuration: node.duration + 's'
              }"
            />
          </template>
        </g>
      </svg>
      <div class="starfield-veil"></div>
    </div>

    <div class="illustration-content">
      <div class="logo-area">
        <div v-if="companyLogo" class="logo-icon">
          <img :src="companyLogo" alt="Logo" class="custom-logo-image" />
        </div>
        <div v-else class="logo-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M24 4L4 20v24l20 16 20-16V20L24 4z" fill="url(#logoGradient)" />
            <path d="M24 10L8 22v16l16 10 16-10V22L24 10z" fill="white" opacity="0.95" />
            <defs>
              <linearGradient id="logoGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color: var(--color-accent)" />
                <stop offset="100%" style="stop-color: var(--lp-grad-end)" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <span class="logo-text">{{ brandStore.brandNameZh }}&nbsp;&nbsp;{{ brandStore.brandNameEn }}</span>
      </div>

      <div class="slogan">
        <h2>{{ brandStore.brandSlogan || t('login.leftTitle') }}</h2>
        <p>{{ t('login.leftSubtitle') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-illustration {
  --lp-grad-end: #8b5cf6;
  flex: 1;
  min-width: 0;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}

/* 深蓝渐变 + 星点连线：铺满整个左侧，无竖条/硬边界 */
.starfield {
  position: absolute;
  inset: 0;
  overflow: hidden;
  opacity: 0;
  transition: opacity 900ms var(--motion-ease);
}

.starfield.entered {
  opacity: 1;
}

.starfield-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.star-link {
  stroke: var(--color-hairline-ink-blue);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.star-halo {
  fill: var(--color-accent-on-dark);
}

.star-halo.accent {
  fill: var(--lp-grad-end);
}

.star-core {
  fill: var(--color-on-ink-blue);
  animation: twinkle 6s ease-in-out infinite;
}

.star-core.accent {
  fill: var(--color-accent-on-dark);
}

.star-core.anchor {
  fill: var(--color-on-ink-blue);
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--color-accent-on-dark) 70%, transparent));
}

.star-core.lit {
  animation: none;
  opacity: 1;
  filter: drop-shadow(0 0 6px var(--color-accent-on-dark));
}

@keyframes twinkle {
  0%,
  100% {
    opacity: var(--tw, 0.6);
  }
  50% {
    opacity: calc(var(--tw, 0.6) * 0.28);
  }
}

/* 文字区柔和遮罩：星点已避开中心椭圆，这层进一步压暗背景保证对比度 */
.starfield-veil {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      ellipse 30% 22% at 50% 21%,
      color-mix(in srgb, var(--color-ink-blue-950) 82%, transparent) 0%,
      transparent 72%
    ),
    radial-gradient(
      ellipse 40% 30% at 50% 55%,
      color-mix(in srgb, var(--color-ink-blue-950) 86%, transparent) 0%,
      transparent 76%
    );
}

.starfield.login-success .star-core {
  animation: none;
  opacity: 0.95;
}

.starfield.login-fail {
  animation: starfieldShake 380ms var(--motion-ease);
}

@keyframes starfieldShake {
  0%,
  100% {
    transform: translateX(0);
  }
  30% {
    transform: translateX(-6px);
  }
  70% {
    transform: translateX(6px);
  }
}

.illustration-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  padding: 0;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 300px;
}

.logo-icon {
  background: transparent;
  border-radius: 12px;
  overflow: hidden;
}

.logo-icon svg {
  width: 58px;
  height: 58px;
  display: block;
  filter: drop-shadow(0 10px 28px color-mix(in srgb, var(--color-accent) 35%, transparent));
}

.custom-logo-image {
  max-width: 80px;
  max-height: 58px;
  width: auto;
  height: auto;
  object-fit: contain;
  filter: drop-shadow(0 10px 28px color-mix(in srgb, var(--color-accent) 35%, transparent));
}

.logo-text {
  font-size: 28px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--color-on-ink-blue);
}

.slogan {
  text-align: center;
}

.slogan h2 {
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 1.5px;
  color: var(--color-on-ink-blue);
  margin: 0 0 12px;
}

.slogan p {
  font-size: 14px;
  letter-spacing: 1px;
  color: var(--color-on-ink-blue-muted);
  margin: 0;
}

@media (max-width: 1024px) {
  .login-illustration {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .starfield,
  .starfield * {
    animation: none !important;
    transition: none !important;
  }

  .starfield {
    opacity: 1;
  }
}
</style>
