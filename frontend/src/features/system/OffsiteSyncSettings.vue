<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getOffsiteSyncConfig, updateOffsiteSyncConfig,
  testOffsiteSync, runOffsiteSync, getOffsiteSyncStatus,
} from '../../api/offsiteSync'
import type { OffsiteSyncView, OffsiteSyncPayload, OffsiteSyncResult, OffsiteSyncStatus } from '../../api/offsiteSync'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const running = ref(false)
const status = ref<OffsiteSyncStatus | null>(null)

// 表单：非敏感字段直接编辑；敏感字段单独用 local 变量（留空=不修改）
const form = reactive({
  enabled: false,
  target_type: 'rclone' as 'rclone' | 'rsync' | 'sftp',
  schedule_time: '04:00',
  source_dir: '/opt/cornerstone/db_backups',
  rclone_provider: 'minio',
  rclone_endpoint: '',
  rclone_bucket: '',
  rclone_region: '',
  rclone_prefix: 'cornerstone-db',
  rsync_host: '',
  rsync_port: 22,
  rsync_user: '',
  rsync_remote_path: '',
  sftp_host: '',
  sftp_port: 22,
  sftp_user: '',
  sftp_remote_path: '',
})

const secrets = reactive({
  rclone_access_key_id: '',
  rclone_secret_access_key: '',
  rsync_ssh_key: '',
  sftp_ssh_key: '',
})

// 已配置状态（GET 返回的 has_xxx）
const has = ref<Record<string, boolean>>({})

const load = async () => {
  loading.value = true
  try {
    const cfg: OffsiteSyncView = await getOffsiteSyncConfig()
    Object.keys(form).forEach((k) => {
      const v = (cfg as any)[k]
      if (v !== undefined && v !== null) (form as any)[k] = v
    })
    has.value = {
      rclone_access_key_id: !!cfg.has_rclone_access_key_id,
      rclone_secret_access_key: !!cfg.has_rclone_secret_access_key,
      rsync_ssh_key: !!cfg.has_rsync_ssh_key,
      sftp_ssh_key: !!cfg.has_sftp_ssh_key,
    }
    const st = await getOffsiteSyncStatus()
    status.value = st
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载配置失败')
  } finally {
    loading.value = false
  }
}

const buildPayload = (): OffsiteSyncPayload => ({
  ...form,
  // 敏感字段：留空则不传（后端 _keep 保留旧值）；有值才传
  rclone_access_key_id: secrets.rclone_access_key_id || undefined,
  rclone_secret_access_key: secrets.rclone_secret_access_key || undefined,
  rsync_ssh_key: secrets.rsync_ssh_key || undefined,
  sftp_ssh_key: secrets.sftp_ssh_key || undefined,
})

const save = async () => {
  saving.value = true
  try {
    const res = await updateOffsiteSyncConfig(buildPayload())
    ElMessage.success('已保存')
    // 刷新 has 状态并清空已提交的密钥输入
    has.value = {
      rclone_access_key_id: !!res.has_rclone_access_key_id,
      rclone_secret_access_key: !!res.has_rclone_secret_access_key,
      rsync_ssh_key: !!res.has_rsync_ssh_key,
      sftp_ssh_key: !!res.has_sftp_ssh_key,
    }
    Object.keys(secrets).forEach((k) => (secrets as any)[k] = '')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const test = async () => {
  testing.value = true
  try {
    const r: OffsiteSyncResult = await testOffsiteSync()
    if (r.ok) ElMessage.success(r.message)
    else ElMessage.error(r.message + (r.error ? `：${r.error}` : ''))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '测试失败')
  } finally {
    testing.value = false
  }
}

const run = async () => {
  running.value = true
  try {
    const r = await runOffsiteSync()
    if (r.ok) ElMessage.success('同步完成')
    else ElMessage.error(r.message + (r.error ? `：${r.error}` : ''))
    status.value = await getOffsiteSyncStatus()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '同步失败')
  } finally {
    running.value = false
  }
}

const lastSyncText = computed(() => {
  const ls = status.value?.last_sync
  if (!ls) return '暂无同步记录'
  const when = ls.at ? new Date(ls.at * 1000).toLocaleString() : ''
  return `${ls.ok ? '成功' : '失败'} · ${when} · ${ls.trigger || ''}${ls.error ? ' · ' + ls.error : ''}`
})

onMounted(load)
</script>

<template>
  <div class="offsite-page" v-loading="loading">
    <div class="card">
      <div class="card-title">异地备份同步</div>
      <p class="hint">
        将数据库备份文件（pg_dump 产物）定期同步到异地存储/主机，防宿主机损坏导致备份一起丢失。
        仅超级管理员可配置；密钥/私钥加密存储，界面不回显明文。
      </p>

      <div class="row">
        <div class="field">
          <label>启用</label>
          <el-switch v-model="form.enabled" />
        </div>
        <div class="field">
          <label>同步类型</label>
          <el-select v-model="form.target_type" style="width: 160px">
            <el-option label="对象存储 (rclone)" value="rclone" />
            <el-option label="远程主机 (rsync)" value="rsync" />
            <el-option label="SFTP/SCP" value="sftp" />
          </el-select>
        </div>
        <div class="field">
          <label>每日同步时间</label>
          <el-time-picker
            v-model="form.schedule_time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="04:00"
            style="width: 140px"
          />
        </div>
      </div>

      <div class="row">
        <div class="field full">
          <label>源目录（须在白名单内）</label>
          <el-input v-model="form.source_dir" placeholder="/opt/cornerstone/db_backups" />
          <p class="hint">默认 /opt/cornerstone/db_backups；其它目录需运维在环境变量 OFFSITE_SYNC_ALLOWED_DIRS 放行。</p>
        </div>
      </div>

      <!-- rclone -->
      <template v-if="form.target_type === 'rclone'">
        <div class="row">
          <div class="field">
            <label>Provider</label>
            <el-select v-model="form.rclone_provider" style="width: 160px">
              <el-option label="MinIO" value="minio" />
              <el-option label="AWS S3" value="s3" />
              <el-option label="阿里云 OSS" value="oss" />
              <el-option label="腾讯云 COS" value="cos" />
            </el-select>
          </div>
          <div class="field">
            <label>Endpoint</label>
            <el-input v-model="form.rclone_endpoint" placeholder="https://minio.local" />
          </div>
          <div class="field">
            <label>Region（可选）</label>
            <el-input v-model="form.rclone_region" placeholder="us-east-1" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label class="req">Bucket</label>
            <el-input v-model="form.rclone_bucket" />
          </div>
          <div class="field">
            <label>路径前缀</label>
            <el-input v-model="form.rclone_prefix" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label class="req">Access Key ID</label>
            <el-input v-model="secrets.rclone_access_key_id" type="password" show-password
              :placeholder="has.rclone_access_key_id ? '已配置，留空不修改' : '必填'" />
          </div>
          <div class="field">
            <label class="req">Secret Access Key</label>
            <el-input v-model="secrets.rclone_secret_access_key" type="password" show-password
              :placeholder="has.rclone_secret_access_key ? '已配置，留空不修改' : '必填'" />
          </div>
        </div>
      </template>

      <!-- rsync -->
      <template v-if="form.target_type === 'rsync'">
        <div class="row">
          <div class="field">
            <label class="req">主机</label>
            <el-input v-model="form.rsync_host" placeholder="backup.example.com" />
          </div>
          <div class="field">
            <label>端口</label>
            <el-input-number v-model="form.rsync_port" :min="1" :max="65535" />
          </div>
          <div class="field">
            <label class="req">用户</label>
            <el-input v-model="form.rsync_user" />
          </div>
          <div class="field">
            <label class="req">远程路径</label>
            <el-input v-model="form.rsync_remote_path" placeholder="db_backups" />
          </div>
        </div>
        <div class="row">
          <div class="field full">
            <label class="req">SSH 私钥（仅支持密钥认证）</label>
            <el-input v-model="secrets.rsync_ssh_key" type="textarea" :rows="3"
              :placeholder="has.rsync_ssh_key ? '已配置，留空不修改' : '粘贴私钥（含 BEGIN OPENSSH PRIVATE KEY）'" />
          </div>
        </div>
      </template>

      <!-- sftp -->
      <template v-if="form.target_type === 'sftp'">
        <div class="row">
          <div class="field">
            <label class="req">主机</label>
            <el-input v-model="form.sftp_host" placeholder="backup.example.com" />
          </div>
          <div class="field">
            <label>端口</label>
            <el-input-number v-model="form.sftp_port" :min="1" :max="65535" />
          </div>
          <div class="field">
            <label class="req">用户</label>
            <el-input v-model="form.sftp_user" />
          </div>
          <div class="field">
            <label class="req">远程路径</label>
            <el-input v-model="form.sftp_remote_path" placeholder="db_backups" />
          </div>
        </div>
        <div class="row">
          <div class="field full">
            <label class="req">SSH 私钥（仅支持密钥认证）</label>
            <el-input v-model="secrets.sftp_ssh_key" type="textarea" :rows="3"
              :placeholder="has.sftp_ssh_key ? '已配置，留空不修改' : '粘贴私钥'" />
          </div>
        </div>
      </template>

      <div class="actions">
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button :loading="testing" @click="test">测试连接</el-button>
        <el-button :loading="running" @click="run" :disabled="!form.enabled">立即同步</el-button>
      </div>

      <div class="status">
        <div><b>最近同步：</b>{{ lastSyncText }}</div>
        <div class="tools">
          <b>工具可用性：</b>
          <el-tag :type="status?.tools.rclone ? 'success' : 'info'" size="small">rclone {{ status?.tools.rclone ? '✓' : '✗' }}</el-tag>
          <el-tag :type="status?.tools.rsync ? 'success' : 'info'" size="small">rsync {{ status?.tools.rsync ? '✓' : '✗' }}</el-tag>
          <el-tag :type="status?.tools.scp ? 'success' : 'info'" size="small">scp {{ status?.tools.scp ? '✓' : '✗' }}</el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.offsite-page { padding: 20px; }
.card {
  background: var(--bg-primary);
  border: 1px solid var(--border-primary);
  border-radius: 8px;
  padding: 24px;
  max-width: 1080px;
}
.card-title { font-size: 18px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.hint { font-size: 12px; color: var(--text-tertiary); margin: 4px 0 16px; }
.row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
.field { display: flex; flex-direction: column; min-width: 180px; flex: 1; }
.field.full { flex: 100; }
.field label { font-size: 13px; color: var(--text-primary); margin-bottom: 6px; }
.field label.req::before { content: '*'; color: var(--el-color-danger); margin-right: 4px; }
.actions { margin-top: 16px; display: flex; gap: 12px; }
.status { margin-top: 16px; font-size: 13px; color: var(--text-secondary); }
.tools { margin-top: 8px; display: flex; align-items: center; gap: 8px; }
</style>
