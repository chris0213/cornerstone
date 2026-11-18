<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  listDatabaseBackups, downloadDatabaseBackup,
  createDatabaseBackup, deleteDatabaseBackup, verifyDatabaseBackup,
  getBackupConfig, updateBackupConfig, listBackupRuns,
} from '../../api/databaseBackup'
import type { DatabaseBackupFile, VerifyResult, BackupRun } from '../../api/databaseBackup'

const loading = ref(false)
const creating = ref(false)
const files = ref<DatabaseBackupFile[]>([])
const dir = ref('')
const exists = ref(true)

// 本地备份调度配置
const cfgLoading = ref(false)
const cfgSaving = ref(false)
const nextRun = ref<string | null>(null)
const lastVerify = ref<{ name: string; ok: boolean; at: number; error?: string | null } | null>(null)
const cfgForm = reactive({
  enabled: false,
  schedule_time: '03:30',
  retention_days: 30,
  keep_last: 7,
  auto_verify: false,
})

// 最近备份运行台账
const runs = ref<BackupRun[]>([])
const runsLoading = ref(false)

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
    await loadRuns()
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

const loadConfig = async () => {
  cfgLoading.value = true
  try {
    const c = await getBackupConfig()
    cfgForm.enabled = c.enabled
    cfgForm.schedule_time = c.schedule_time
    cfgForm.retention_days = c.retention_days
    cfgForm.keep_last = c.keep_last
    cfgForm.auto_verify = c.auto_verify
    nextRun.value = c.next_run ?? null
    lastVerify.value = c.last_verify ?? null
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载备份调度配置失败')
  } finally {
    cfgLoading.value = false
  }
}

const saveConfig = async () => {
  cfgSaving.value = true
  try {
    const res = await updateBackupConfig({
      enabled: cfgForm.enabled,
      schedule_time: cfgForm.schedule_time,
      retention_days: cfgForm.retention_days,
      keep_last: cfgForm.keep_last,
      auto_verify: cfgForm.auto_verify,
    })
    nextRun.value = res.next_run ?? null
    ElMessage.success('已保存备份调度配置')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    cfgSaving.value = false
  }
}

const loadRuns = async () => {
  runsLoading.value = true
  try {
    runs.value = await listBackupRuns(50)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载备份运行记录失败')
  } finally {
    runsLoading.value = false
  }
}

const fmtRunTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—')
const verifyLabel = (s?: string | null) =>
  ({ passed: '通过', failed: '未通过', error: '异常', skipped: '未校验' } as Record<string, string>)[s || ''] || '—'
const verifyTagType = (s?: string | null) =>
  ({ passed: 'success', failed: 'danger', error: 'warning', skipped: 'info' } as Record<string, string>)[s || ''] || 'info'
const integrityLabel = (s?: string | null) =>
  ({ ok: '一致', mismatch: '不一致(疑似损坏)', unknown: '无指纹可比', error: '读取失败' } as Record<string, string>)[s || ''] || '—'
const integrityTagType = (s?: string | null) =>
  ({ ok: 'success', mismatch: 'danger', unknown: 'info', error: 'warning' } as Record<string, string>)[s || ''] || 'info'

onMounted(() => { load(); loadConfig(); loadRuns() })
</script>

<template>
  <div class="dbbackup-page" v-loading="loading">
    <div class="card cfg-card" v-loading="cfgLoading">
      <div class="title">备份调度配置</div>
      <p class="hint">
        应用内每日定时整库备份（pg_dump）。停用宿主机 cron 后由这里接管；
        手动「立即备份」产物标记为 <code>manual</code>，<b>永不被保留策略删除</b>，仅自动备份按下方策略清理。
      </p>
      <div class="cfg-row">
        <div class="cfg-field">
          <label>启用定时备份</label>
          <el-switch v-model="cfgForm.enabled" />
        </div>
        <div class="cfg-field">
          <label>备份后自动校验</label>
          <el-switch v-model="cfgForm.auto_verify" />
          <span class="sub-hint">每次定时备份后自动恢复到隔离库校验，失败即告警</span>
        </div>
        <div class="cfg-field">
          <label>每日备份时间</label>
          <el-time-picker v-model="cfgForm.schedule_time" format="HH:mm" value-format="HH:mm"
            placeholder="03:30" style="width: 140px" />
        </div>
        <div class="cfg-field">
          <label>保留天数</label>
          <el-input-number v-model="cfgForm.retention_days" :min="0" :max="3650" />
          <span class="sub-hint">0 = 不按天数清理</span>
        </div>
        <div class="cfg-field">
          <label>至少保留（个）</label>
          <el-input-number v-model="cfgForm.keep_last" :min="0" :max="3650" />
          <span class="sub-hint">保底最近 N 个自动备份不被删</span>
        </div>
        <div class="cfg-field">
          <label>&nbsp;</label>
          <el-button type="primary" :loading="cfgSaving" @click="saveConfig">保存配置</el-button>
        </div>
      </div>
      <p class="hint">
        下次自动备份：{{ nextRun ? new Date(nextRun).toLocaleString() : (cfgForm.enabled ? '（保存后由后端计算）' : '未启用') }}
      </p>
      <p class="hint">
        最近自动校验：
        <template v-if="lastVerify">
          <el-tag size="small" :type="lastVerify.ok ? 'success' : 'danger'">{{ lastVerify.ok ? '通过' : '未通过' }}</el-tag>
          {{ lastVerify.name }} · {{ new Date(lastVerify.at * 1000).toLocaleString() }}
          <span v-if="lastVerify.error" class="verify-err">· {{ lastVerify.error }}</span>
        </template>
        <template v-else>{{ cfgForm.auto_verify ? '暂无记录（重启后清空）' : '未开启自动校验' }}</template>
      </p>
    </div>

    <div class="card">
      <div class="head">
        <div>
          <div class="title">数据库备份</div>
          <p class="hint">
            目录：<code>{{ dir }}</code>（上方「备份调度配置」每日定时产出 + 手动「立即备份」）。
            下载后用 <code>pg_restore</code> 恢复，详见备份恢复手册。
          </p>
        </div>
        <div class="head-actions">
          <el-button type="primary" :loading="creating" @click="create">立即备份</el-button>
          <el-button :icon="Refresh" @click="load">刷新</el-button>
        </div>
      </div>

      <el-alert v-if="!exists" type="warning" :closable="false" show-icon
        title="备份目录不存在或为空"
        description="尚未有备份。可点「立即备份」手动生成一次，或在上方启用每日定时备份。" />

      <el-table v-else :data="files" style="width: 100%">
        <el-table-column prop="name" label="文件名" min-width="320" />
        <el-table-column prop="size_mb" label="大小(MB)" width="120" />
        <el-table-column label="修改时间" width="220">
          <template #default="{ row }">{{ fmtTime(row.modified_at) }}</template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.trigger === 'auto' ? 'info' : 'success'">
              {{ row.trigger === 'auto' ? '自动' : '手动' }}
            </el-tag>
          </template>
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
          <p class="hint" style="margin-top:8px">
            完整性指纹：
            <el-tag size="small" :type="integrityTagType(verifyResult.integrity?.status)">
              {{ integrityLabel(verifyResult.integrity?.status) }}
            </el-tag>
          </p>
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

    <div class="card runs-card" v-loading="runsLoading">
      <div class="head">
        <div>
          <div class="title">最近备份运行</div>
          <p class="hint">每次备份（自动/手动）与自动校验的运行台账，便于回溯对账。</p>
        </div>
        <div class="head-actions">
          <el-button :icon="Refresh" @click="loadRuns">刷新</el-button>
        </div>
      </div>
      <el-table :data="runs" style="width: 100%">
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtRunTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="触发" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.trigger === 'auto' ? 'info' : 'success'">
              {{ row.trigger === 'auto' ? '自动' : '手动' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="备份" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'success' ? 'success' : 'danger'">
              {{ row.status === 'success' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="校验" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="verifyTagType(row.verify_status)">{{ verifyLabel(row.verify_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="filename" label="文件" min-width="260" show-overflow-tooltip />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.size_bytes != null ? (row.size_bytes / 1048576).toFixed(1) + ' MB' : '—' }}</template>
        </el-table-column>
        <el-table-column label="SHA-256" width="140" show-overflow-tooltip>
          <template #default="{ row }"><code class="sha">{{ row.sha256 ? row.sha256.slice(0, 12) + '…' : '—' }}</code></template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ row.duration_ms != null ? Math.round(row.duration_ms / 1000) + 's' : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作人" width="100">
          <template #default="{ row }">{{ row.operator || '—' }}</template>
        </el-table-column>
        <el-table-column label="错误/原因" min-width="180">
          <template #default="{ row }">
            <span class="verify-err">{{ row.error || row.verify_error || '' }}</span>
          </template>
        </el-table-column>
        <template #empty>暂无备份运行记录</template>
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
.head-actions { display: flex; gap: 8px; }
.verify-err { color: var(--el-color-danger); font-size: 12px; margin: 8px 0 0; }
.title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.hint { font-size: 12px; color: var(--text-tertiary); margin-top: 6px; }
.hint code { background: var(--bg-secondary); padding: 1px 5px; border-radius: 4px; }
.cfg-card { margin-bottom: 16px; }
.runs-card { margin-top: 16px; }
.cfg-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; margin-top: 8px; }
.cfg-field { display: flex; flex-direction: column; min-width: 160px; }
.cfg-field label { font-size: 13px; color: var(--text-primary); margin-bottom: 6px; }
.cfg-field .sub-hint { font-size: 11px; color: var(--text-tertiary); margin-top: 4px; }
.sha { font-family: var(--font-mono, monospace); font-size: 12px; color: var(--text-secondary); }
</style>
