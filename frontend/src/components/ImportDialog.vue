<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload, Download } from '@element-plus/icons-vue'
import api from '../api/axios'

interface Props {
  title: string
  importUrl: string
  templateUrl: string
  accept?: string
}

const props = withDefaults(defineProps<Props>(), {
  accept: '.xlsx,.xls,.csv'
})

const emit = defineEmits(['success'])

const visible = defineModel<boolean>()
const fileList = ref<any[]>([])
const uploading = ref(false)
const result = ref<any>(null)

async function handleImport() {
  if (fileList.value.length === 0) {
    ElMessage.warning('请选择要导入的文件')
    return
  }

  uploading.value = true
  result.value = null

  try {
    const formData = new FormData()
    formData.append('file', fileList.value[0].raw)

    const response = await api.post(props.importUrl, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    result.value = response.data

    if (response.data.success_count > 0) {
      ElMessage.success(`成功导入 ${response.data.success_count} 条数据`)
      emit('success')
    }

    if (response.data.failed_count > 0) {
      ElMessage.warning(`${response.data.failed_count} 条数据导入失败`)
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '导入失败')
  } finally {
    uploading.value = false
  }
}

function handleDownloadTemplate() {
  window.open(props.templateUrl, '_blank')
}

function handleFileChange(_file: any, list: any[]) {
  fileList.value = list.slice(-1) // 只保留最后一个文件
}

function handleClose() {
  visible.value = false
  fileList.value = []
  result.value = null
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="600px"
    @close="handleClose"
  >
    <div class="import-content">
      <!-- 说明 -->
      <el-alert
        title="导入说明"
        type="info"
        :closable="false"
        style="margin-bottom: 20px;"
      >
        <template #default>
          <p>1. 请先下载导入模板，按照模板格式填写数据</p>
          <p>2. 支持Excel (.xlsx, .xls) 和 CSV 格式</p>
          <p>3. 必填字段不能为空，否则该行数据将导入失败</p>
        </template>
      </el-alert>

      <!-- 下载模板按钮 -->
      <div class="template-section">
        <el-button
          type="primary"
          plain
          :icon="Download"
          @click="handleDownloadTemplate"
        >
          下载导入模板
        </el-button>
      </div>

      <!-- 文件上传 -->
      <el-upload
        class="upload-section"
        drag
        :auto-upload="false"
        :limit="1"
        :accept="accept"
        :on-change="handleFileChange"
        :file-list="fileList"
      >
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">
          将文件拖到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            只能上传 xlsx/xls/csv 文件
          </div>
        </template>
      </el-upload>

      <!-- 导入结果 -->
      <div v-if="result" class="result-section">
        <el-divider />
        <h4>导入结果</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="成功数量">
            <el-tag type="success">{{ result.success_count }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="失败数量">
            <el-tag type="danger">{{ result.failed_count }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="result.errors && result.errors.length > 0" style="margin-top: 16px;">
          <h5>错误详情：</h5>
          <el-alert
            v-for="(error, index) in result.errors"
            :key="index"
            :title="error"
            type="error"
            :closable="false"
            style="margin-bottom: 8px;"
          />
          <p v-if="result.errors.length >= 10" style="color: #999; font-size: 12px;">
            仅显示前10条错误
          </p>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button
        type="primary"
        :loading="uploading"
        :disabled="fileList.length === 0"
        @click="handleImport"
      >
        开始导入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-content {
  padding: 10px 0;
}

.template-section {
  margin-bottom: 20px;
}

.upload-section {
  margin-bottom: 20px;
}

.result-section {
  margin-top: 20px;
}

.result-section h4 {
  margin-bottom: 16px;
  color: var(--color-text-1);
}

.result-section h5 {
  margin-bottom: 12px;
  color: var(--color-text-2);
}
</style>
