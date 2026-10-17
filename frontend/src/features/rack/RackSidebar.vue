<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Refresh, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import type { Rack } from '../../types/domain'

const props = defineProps<{
  racks: Rack[]
  selectedId: number | null
  search: string
}>()

const emit = defineEmits<{
  (e: 'update:search', v: string): void
  (e: 'select', id: number): void
  (e: 'refresh'): void
}>()

const { t } = useI18n()

// ---- 排序：default 按机房/排位分组；utilization 按利用率降序平铺 ----
const sortMode = ref<'default' | 'utilization'>('default')
const setSortMode = (mode: 'default' | 'utilization') => {
  sortMode.value = mode
}

// 折叠的机房分组
const collapsed = ref<Set<string>>(new Set())
const toggleGroup = (room: string) => {
  const next = new Set(collapsed.value)
  if (next.has(room)) next.delete(room)
  else next.add(room)
  collapsed.value = next
}

const utilLevel = (r: Rack): 'low' | 'mid' | 'high' => {
  const p = r.utilization || 0
  if (p > 90) return 'high'
  if (p >= 70) return 'mid'
  return 'low'
}

const byUtil = (a: Rack, b: Rack) => (b.utilization || 0) - (a.utilization || 0)

// 按 room → 分组（仅 default 模式）
const grouped = computed(() => {
  const map = new Map<string, Rack[]>()
  for (const r of props.racks) {
    const k = r.room || t('rack.unassigned')
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(r)
  }
  return Array.from(map.entries()).map(([room, items]) => ({
    room,
    items: items.slice().sort((a, b) => (a.rowPosition || 0) - (b.rowPosition || 0) || a.name.localeCompare(b.name)),
  }))
})

// 平铺列表（utilization 模式）
const flatSorted = computed(() => props.racks.slice().sort(byUtil))
</script>

<template>
  <div class="rack-sidebar">
    <div class="sidebar-header">
      <el-input
        :model-value="search"
        @update:model-value="(v: string) => emit('update:search', v)"
        :placeholder="t('rack.navSearchPlaceholder')"
        size="small"
        clearable
        class="sidebar-search"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button :icon="Refresh" size="small" circle @click="emit('refresh')" />
    </div>

    <div class="sidebar-sort">
      <el-radio-group :model-value="sortMode" size="small" @update:model-value="(v: any) => setSortMode(v)">
        <el-radio-button value="default">{{ t('rack.sortDefault') }}</el-radio-button>
        <el-radio-button value="utilization">{{ t('rack.sortUtilization') }}</el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="!racks.length" class="sidebar-empty">
      <el-empty :description-size="12" :image-size="50" />
    </div>

    <!-- 利用率排序：平铺 -->
    <ul v-else-if="sortMode === 'utilization'" class="rack-group-list rack-tree">
      <li
        v-for="r in flatSorted"
        :key="r.id"
        class="rack-item"
        :class="{ active: r.id === selectedId }"
        @click="emit('select', r.id)"
      >
        <span class="rack-item-name" :title="r.name">{{ r.name }}</span>
        <span class="rack-item-util">
          <span class="util-bar">
            <span class="util-fill" :class="`util-${utilLevel(r)}`" :style="{ width: Math.min(r.utilization || 0, 100) + '%' }"></span>
          </span>
          <span class="util-text">{{ (r.utilization || 0).toFixed(0) }}%</span>
          <span class="util-u">{{ r.totalU || 42 }}U</span>
        </span>
      </li>
    </ul>

    <!-- 默认：机房分组，可折叠 -->
    <div v-else class="rack-tree">
      <div v-for="g in grouped" :key="g.room" class="rack-group">
        <div class="rack-group-title" @click="toggleGroup(g.room)">
          <el-icon class="collapse-arrow">
            <ArrowDown v-if="!collapsed.has(g.room)" />
            <ArrowRight v-else />
          </el-icon>
          <span>{{ g.room }}</span>
          <el-tag size="small" type="info">{{ g.items.length }}</el-tag>
        </div>
        <ul v-show="!collapsed.has(g.room)" class="rack-group-list">
          <li
            v-for="r in g.items"
            :key="r.id"
            class="rack-item"
            :class="{ active: r.id === selectedId }"
            @click="emit('select', r.id)"
          >
            <span class="rack-item-name" :title="r.name">{{ r.name }}</span>
            <span class="rack-item-util">
              <span class="util-bar">
                <span class="util-fill" :class="`util-${utilLevel(r)}`" :style="{ width: Math.min(r.utilization || 0, 100) + '%' }"></span>
              </span>
              <span class="util-text">{{ (r.utilization || 0).toFixed(0) }}%</span>
              <span class="util-u">{{ r.totalU || 42 }}U</span>
            </span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { Search } from '@element-plus/icons-vue'
export default { components: { Search } }
</script>

<style scoped>
.rack-sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 520px;
}
.sidebar-header {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color, #eef0f3);
}
.sidebar-search { flex: 1; }
.sidebar-empty { padding: 20px 0; }
.sidebar-sort { margin-bottom: 10px; }
.sidebar-sort :deep(.el-radio-button__inner) {
  padding: 4px 10px;
  font-size: 12px;
}

.rack-tree { flex: 1; overflow-y: auto; padding-right: 4px; }
.rack-group + .rack-group { margin-top: 12px; }
.rack-group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary, #6b7280);
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 6px;
  cursor: pointer;
  user-select: none;
}
.rack-group-title:hover { color: var(--text-primary, #1f2937); }
.collapse-arrow { font-size: 12px; }
.rack-group-title .el-tag { margin-left: auto; }

.rack-group-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.rack-item {
  padding: 6px 8px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary, #1f2937);
  transition: background .12s;
}
.rack-item:hover { background: var(--bg-hover, #eef3ff); }
.rack-item.active {
  background: var(--primary-light, #e8f1ff);
  color: var(--primary, #1e40af);
  font-weight: 500;
}
.rack-item-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 利用率迷你进度条（阈值配色与 IP 管理页一致：<70% 蓝 / 70-90% 橙 / >90% 红） */
.rack-item-util {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.util-bar {
  width: 40px;
  height: 6px;
  border-radius: 999px;
  background: var(--el-fill-color, #f0f2f5);
  overflow: hidden;
  display: inline-block;
}
.util-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}
.util-fill.util-low { background: var(--el-color-primary, #409eff); }
.util-fill.util-mid { background: var(--el-color-warning, #e6a23c); }
.util-fill.util-high { background: var(--el-color-danger, #f56c6c); }
.util-text {
  width: 30px;
  font-size: 11px;
  color: var(--text-secondary, #6b7280);
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  text-align: right;
}
.util-u {
  font-size: 11px;
  color: var(--text-secondary, #6b7280);
  opacity: 0.75;
}
</style>
