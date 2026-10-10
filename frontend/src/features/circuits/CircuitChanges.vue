<template>
  <div class="circuit-changes">
    <div class="page-header">
      <button class="back-btn" @click="goBack">
        <el-icon><ArrowLeft /></el-icon> 返回
      </button>
    </div>
    <el-card class="page-card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Document /></el-icon>
          变更记录
          <span class="circuit-name">- {{ circuitName }}</span>
        </div>
      </template>
      
      <div class="empty-state" v-if="loading">
        <el-spinner size="medium" />
      </div>
      
      <div class="empty-state" v-else-if="changes.length === 0">
        <el-icon :size="48" color="#ccc"><Files /></el-icon>
        <p>暂无变更记录</p>
      </div>
      
      <el-table class="circuit-changes-table" v-else :data="changes" border stripe>
        <el-table-column prop="id" label="ID" min-width="80" />
        <el-table-column prop="change_type" label="变更类型">
          <template #default="scope">
            <el-tag :type="getChangeTypeTag(scope.row.change_type)">
              {{ getChangeTypeName(scope.row.change_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="field_name" label="变更字段" />
        <el-table-column prop="old_value" label="原值" />
        <el-table-column prop="new_value" label="新值" />
        <el-table-column prop="operator" label="操作人" />
        <el-table-column prop="remark" label="备注" />
        <el-table-column prop="created_at" label="变更时间">
          <template #default="scope">
            {{ formatDateTime(scope.row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Document, Files, ArrowLeft } from '@element-plus/icons-vue'
import { getCircuitChanges, type CircuitChange } from '../../api/circuits'
import { formatDateTime } from '@/lib/utils'

const route = useRoute()
const router = useRouter()
const circuitId = route.params.id as string

function goBack() {
  router.push(`/circuits/${circuitId}`)
}

const loading = ref(false)
const changes = ref<CircuitChange[]>([])

const circuitName = computed(() => {
  return route.query.name || `专线 ${circuitId}`
})

function getChangeTypeName(type: string): string {
  const types: Record<string, string> = {
    'create': '创建',
    'update': '更新',
    'delete': '删除'
  }
  return types[type] || type
}

function getChangeTypeTag(type: string): string {
  const types: Record<string, string> = {
    'create': 'success',
    'update': 'warning',
    'delete': 'danger'
  }
  return types[type] || 'info'
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await getCircuitChanges(parseInt(circuitId))
    changes.value = data
  } catch (error) {
    console.error('Failed to fetch circuit changes:', error)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.circuit-changes {
  padding: 20px;
}

.page-header {
  margin-bottom: 16px;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  color: #1890ff;
  cursor: pointer;
  padding: 8px 0;
  font-size: 14px;
}

.back-btn:hover {
  text-decoration: underline;
}

.page-card {
  margin-bottom: 20px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}

.circuit-name {
  font-size: 14px;
  font-weight: normal;
  color: #999;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #999;
}

.empty-state p {
  margin-top: 16px;
}

.circuit-changes-table :deep(.cell) {
  line-height: 1.5;
}

.circuit-changes-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>