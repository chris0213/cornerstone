<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBrandStore } from '@/store/brand'
import { useNetworkAnimation } from '../composables/useNetworkAnimation'

const { t } = useI18n()
const brandStore = useBrandStore()

const { illustrationRef, nodes, links, dataPackets, hasEntered, animationMode } = useNetworkAnimation()

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

loadLogo()
</script>

<template>
  <div class="login-illustration" ref="illustrationRef">
    <div
      class="network-container"
      :class="{
        entered: hasEntered,
        'login-success': animationMode === 'login-success',
        'login-fail': animationMode === 'login-fail'
      }"
    >
      <svg viewBox="0 0 600 800" class="network-svg">
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="3" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <radialGradient id="nodeGradient" cx="30%" cy="30%">
            <stop offset="0%" stop-color="white" stop-opacity="0.8" />
            <stop offset="100%" stop-color="white" stop-opacity="0" />
          </radialGradient>
        </defs>
        <g class="links">
          <line
            v-for="(link, index) in links"
            :key="'link-' + index"
            :x1="nodes[link.from]?.x || 0"
            :y1="nodes[link.from]?.y || 0"
            :x2="nodes[link.to]?.x || 0"
            :y2="nodes[link.to]?.y || 0"
            :stroke="nodes[link.from]?.color || '#3b82f6'"
            :stroke-opacity="link.opacity"
            stroke-width="1"
            class="link-line"
          />
        </g>
        <g class="data-packets">
          <g v-for="packet in dataPackets" :key="'packet-' + packet.id">
            <circle
              :cx="
                (nodes[links[packet.linkIndex]?.from]?.x || 0) +
                ((nodes[links[packet.linkIndex]?.to]?.x || 0) - (nodes[links[packet.linkIndex]?.from]?.x || 0)) *
                  packet.progress
              "
              :cy="
                (nodes[links[packet.linkIndex]?.from]?.y || 0) +
                ((nodes[links[packet.linkIndex]?.to]?.y || 0) - (nodes[links[packet.linkIndex]?.from]?.y || 0)) *
                  packet.progress
              "
              r="4"
              :fill="packet.color"
              filter="url(#glow)"
              class="data-packet"
            />
            <circle
              :cx="
                (nodes[links[packet.linkIndex]?.from]?.x || 0) +
                ((nodes[links[packet.linkIndex]?.to]?.x || 0) - (nodes[links[packet.linkIndex]?.from]?.x || 0)) *
                  packet.progress
              "
              :cy="
                (nodes[links[packet.linkIndex]?.from]?.y || 0) +
                ((nodes[links[packet.linkIndex]?.to]?.y || 0) - (nodes[links[packet.linkIndex]?.from]?.y || 0)) *
                  packet.progress
              "
              r="2"
              fill="white"
              class="data-packet-core"
            />
          </g>
        </g>
        <g class="nodes">
          <g v-for="node in nodes" :key="'node-' + node.id" class="node-group">
            <circle
              :cx="node.x"
              :cy="node.y"
              :r="node.radius * 2.5"
              :fill="node.color"
              :opacity="node.pulse ? 0.3 : 0.1"
              class="node-glow"
            />
            <circle
              :cx="node.x"
              :cy="node.y"
              :r="node.radius"
              :fill="node.color"
              :opacity="node.opacity"
              :filter="node.pulse ? 'url(#glow)' : ''"
              class="node-core"
              :class="{ pulsing: node.pulse }"
            />
            <circle
              :cx="node.x"
              :cy="node.y"
              :r="node.radius * 0.4"
              fill="white"
              :opacity="node.opacity"
              class="node-center"
            />
          </g>
        </g>
      </svg>
    </div>

    <div class="illustration-content">
      <div class="logo-area">
        <div v-if="companyLogo" class="logo-icon">
          <img :src="companyLogo" alt="Logo" class="custom-logo-image" />
        </div>
        <div v-else class="logo-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M24 4L4 20v24l20 16 20-16V20L24 4z" fill="url(#logoGradient)" />
            <path d="M24 10L8 22v16l16 10 16-10V22L24 10z" fill="white" opacity="0.95" />
            <defs>
              <linearGradient id="logoGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#3b82f6" />
                <stop offset="100%" style="stop-color:#8b5cf6" />
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
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  backdrop-filter: none;
  border-right: none;
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
  filter: drop-shadow(0 10px 28px rgba(59, 130, 246, 0.35));
  animation: logoFloat 6s ease-in-out infinite;
}

.custom-logo-image {
  max-width: 80px;
  max-height: 58px;
  width: auto;
  height: auto;
  object-fit: contain;
  filter: drop-shadow(0 10px 28px rgba(59, 130, 246, 0.35));
  animation: logoFloat 6s ease-in-out infinite;
}

@keyframes logoFloat {
  0%,
  100% {
    transform: translateY(0) rotate(0deg);
  }
  25% {
    transform: translateY(-8px) rotate(1.5deg);
  }
  50% {
    transform: translateY(0) rotate(0deg);
  }
  75% {
    transform: translateY(-4px) rotate(-1.5deg);
  }
}

.logo-text {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 1.5px;
  background: linear-gradient(135deg, #f8fafc 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: 0 4px 16px rgba(59, 130, 246, 0.3);
}

.network-container {
  position: absolute;
  inset: 0;
  z-index: 1;
  opacity: 0;
  transform: scale(0.95);
  transition: all 0.8s cubic-bezier(0.22, 1, 0.36, 1);
}

.network-container.entered {
  opacity: 1;
  transform: scale(1);
}

.network-container.login-success {
  animation: networkSuccess 0.6s ease-out;
}

.network-container.login-fail {
  animation: networkFail 0.5s ease-out;
}

@keyframes networkSuccess {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.05);
  }
}

@keyframes networkFail {
  0%,
  100% {
    transform: translateX(0);
  }
  25% {
    transform: translateX(-10px);
  }
  75% {
    transform: translateX(10px);
  }
}

.network-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
  background: transparent;
}

.link-line {
  transition: opacity 0.3s ease;
}

.node-group {
  transition: transform 0.15s ease;
}

.node-glow {
  transition: r 0.3s ease, opacity 0.3s ease;
}

.node-core {
  transition: r 0.3s ease, opacity 0.3s ease;
}

.node-core.pulsing {
  animation: nodePulse 0.4s ease-out;
}

.node-center {
  transition: opacity 0.3s ease;
}

.data-packet {
  transition: r 0.1s ease;
}

.data-packet-core {
  transition: r 0.1s ease;
}

@keyframes nodePulse {
  0%,
  100% {
    r: var(--original-radius, 5);
  }
  50% {
    r: calc(var(--original-radius, 5) * 1.5);
  }
}

.slogan {
  text-align: center;
  animation: sloganFadeIn 1s ease-out 0.5s both;
}

@keyframes sloganFadeIn {
  from {
    opacity: 0;
    transform: translateY(25px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.slogan h2 {
  font-size: 32px;
  font-weight: 700;
  margin-bottom: 12px;
  letter-spacing: 2px;
  background: linear-gradient(135deg, #ffffff 0%, #e2e8f0 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: 0 4px 20px rgba(59, 130, 246, 0.25);
}

.slogan p {
  font-size: 14px;
  opacity: 0.85;
  letter-spacing: 1.5px;
  color: #94a3b8;
}

@media (max-width: 1024px) {
  .login-illustration {
    display: none;
  }
}
</style>