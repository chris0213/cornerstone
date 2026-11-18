<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  listDatabaseBackups, downloadDatabaseBackup,
  createDatabaseBackup, deleteDatabaseBackup, verifyDatabaseBackup,
} from '../../api/databaseBackup'
import type { DatabaseBackupFile, VerifyResult } from '../../api/databaseBackup'

const loading = ref(false)
const creating = ref(false)
const files = ref<DatabaseBackupFile[]>([])
const dir = ref('')
const exists = ref(true)

// 恢复校验
const verifyingName = ref('')
const verifyDialog = ref(false)
const verifyResult = ref<VerifyResult | null>(null)
const verifyName = ref('')

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

const create = async () => {
  creating.value = true
  try {
    const r = await createDatabaseBackup()
    ElMessage.success(`已生成备份：${r.name}`)
    await load()
  } catch (e: any) {
    ElMessage.error('备份失败：' + (e.response?.data?.detail || e?.message || '未知错误'))
  } finally {
    creating.value = false
  }
}

const remove = async (f: DatabaseBackupFile) => {
  try {
    await ElMessageBox.confirm(
      `确定删除备份「${f.name}」（${f.size_mb} MB）？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteDatabaseBackup(f.name)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || '未知错误'))
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

const verify = async (f: DatabaseBackupFile) => {
  try {
    await ElMessageBox.confirm(
      `将「${f.name}」恢复到一个隔离临时库做校验（不影响生产库），可能需要几十秒。继续？`,
      '恢复校验',
      { type: 'info', confirmButtonText: '开始校验', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  verifyingName.value = f.name
  verifyName.value = f.name
  try {
    verifyResult.value = await verifyDatabaseBackup(f.name)
    verifyDialog.value = true
  } catch (e: any) {
    ElMessage.error('校验失败：' + (e.response?.data?.detail || e?.message || '未知错误'))
  } finally {
    verifyingName.value = ''
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
        <div class="head-actions">
          <el-button type="primary" :loading="creating" @click="create">立即备份</el-button>
          <el-button :icon="Refresh" @click="load">刷新</el-button>
        </div>
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
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="download(row)">下载</el-button>
            <el-button link type="primary" size="small"
              :loading="verifyingName === row.name"
              :disabled="!!verifyingName && verifyingName !== row.name"
              @click="verify(row)">校验</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无备份文件</template>
      </el-table>

      <el-dialog v-model="verifyDialog" title="恢复校验结果" width="520px">
        <div v-if="verifyResult">
          <el-alert
            :type="verifyResult.ok ? 'success' : 'error'"
            :closable="false" show-icon
            :title="verifyResult.ok ? '校验通过：该备份可正常恢复' : '校验未通过'"
            :description="'文件：' + verifyName"
          />
          <p v-if="verifyResult.error" class="verify-err">错误：{{ verifyResult.error }}</p>
          <el-table :data="verifyResult.checks" style="width: 100%; margin-top: 12px">
            <el-table-column prop="table" label="抽查表" />
            <el-table-column label="行数">
              <template #default="{ row }">{{ row.count === null ? '缺失/N-A' : row.count }}</template>
            </el-table-column>
          </el-table>
          <p class="hint" style="margin-top:10px">校验在隔离临时库执行，已自动清理，未触碰生产库。</p>
        </div>
        <template #footer>
          <el-button @click="verifyDialog = false">关闭</el-button>
        </template>
      </el-dialog>
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
.head-actions { display: flex; gap: 8px; }
.verify-err { color: var(--el-color-danger); font-size: 12px; margin: 8px 0 0; }
.title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.hint { font-size: 12px; color: var(--text-tertiary); margin-top: 6px; }
.hint code { background: var(--bg-secondary); padding: 1px 5px; border-radius: 4px; }
</style>
