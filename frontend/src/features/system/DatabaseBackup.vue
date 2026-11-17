<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { listDatabaseBackups, downloadDatabaseBackup } from '../../api/databaseBackup'
import type { DatabaseBackupFile } from '../../api/databaseBackup'

const loading = ref(false)
const files = ref<DatabaseBackupFile[]>([])
const dir = ref('')
const exists = ref(true)

const fmtTime = (ts: number) => new Date(ts * 1000).toLocaleString()

const load = async () => {
  loading.value = true
  try {
    const r = await listDatabaseBackups()
    dir.value = r.dir
    exists.value = r.exists
    files.value = r.files
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载备份列表失败')
  } finally {
    loading.value = false
  }
}

const download = async (f: DatabaseBackupFile) => {
  try {
    const blob = await downloadDatabaseBackup(f.name)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = f.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error('下载失败：' + (e?.message || '未知错误'))
  }
}

onMounted(load)
</script>

<template>
  <div class="dbbackup-page" v-loading="loading">
    <div class="card">
      <div class="head">
        <div>
          <div class="title">数据库备份</div>
          <p class="hint">
            目录：<code>{{ dir }}</code>（宿主机 cron 每日 pg_dump 产物）。下载后用
            <code>pg_restore</code> 恢复，详见备份恢复手册。
          </p>
        </div>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>

      <el-alert v-if="!exists" type="warning" :closable="false" show-icon
        title="备份目录不存在或为空"
        description="尚未生成每日备份，请先在服务器安装 db_backup.sh + cron（见部署手册）。" />

      <el-table v-else :data="files" style="width: 100%">
        <el-table-column prop="name" label="文件名" min-width="320" />
        <el-table-column prop="size_mb" label="大小(MB)" width="120" />
        <el-table-column label="修改时间" width="220">
          <template #default="{ row }">{{ fmtTime(row.modified_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="download(row)">下载</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无备份文件</template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.dbbackup-page { padding: 20px; }
.card {
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 8px;
  padding: 24px;
}
.head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.hint { font-size: 12px; color: var(--text-tertiary); margin-top: 6px; }
.hint code { background: var(--bg-secondary); padding: 1px 5px; border-radius: 4px; }
</style>
