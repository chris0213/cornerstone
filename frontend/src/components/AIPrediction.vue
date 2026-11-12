<template>
  <div class="ai-prediction-container">
    <!-- AI功能卡片 -->
    <div class="ai-features">
      <div class="feature-card" @click="handleFeatureClick('summary')">
        <div class="feature-icon summary-icon">
          <el-icon><InfoFilled /></el-icon>
        </div>
        <h3>{{ t('aiPrediction.features.summary') }}</h3>
        <p>{{ t('aiPrediction.features.summaryDesc') }}</p>
      </div>

      <div class="feature-card" @click="handleFeatureClick('trend')">
        <div class="feature-icon trend-icon">
          <el-icon><DataBoard /></el-icon>
        </div>
        <h3>{{ t('aiPrediction.features.trend') }}</h3>
        <p>{{ t('aiPrediction.features.trendDesc') }}</p>
      </div>

      <div class="feature-card" @click="handleFeatureClick('root_cause')">
        <div class="feature-icon root-cause-icon">
          <el-icon><Search /></el-icon>
        </div>
        <h3>{{ t('aiPrediction.features.rootCause') }}</h3>
        <p>{{ t('aiPrediction.features.rootCauseDesc') }}</p>
      </div>

      <div class="feature-card" @click="handleFeatureClick('query')">
        <div class="feature-icon query-icon">
          <el-icon><InfoFilled /></el-icon>
        </div>
        <h3>{{ t('aiPrediction.features.query') }}</h3>
        <p>{{ t('aiPrediction.features.queryDesc') }}</p>
      </div>
    </div>

    <!-- 问答输入区 -->
    <div v-if="activeFeature === 'query'" class="query-input-section">
      <div class="query-input-wrapper">
        <el-icon class="query-icon"><MessageSquare /></el-icon>
        <input
          v-model="queryInput"
          type="text"
          placeholder="输入您的问题..."
          class="query-input"
          @keyup.enter="submitQuery"
        />
        <button class="submit-btn" @click="submitQuery" :disabled="loading || !queryInput.trim()">
          <el-icon :class="{ spinning: loading }">
            <component :is="loading ? Loading : Check" />
          </el-icon>
        </button>
      </div>
    </div>

    <!-- 预测结果展示 -->
    <div v-if="prediction" class="prediction-result">
      <div class="result-header">
        <div class="result-title">
          <el-icon><component :is="getResultIcon(prediction.type)" /></el-icon>
          <h2>{{ prediction.title }}</h2>
        </div>
        <div class="result-meta">
          <span class="confidence">
            置信度: {{ (prediction.confidence * 100).toFixed(0) }}%
          </span>
          <span class="timestamp">{{ prediction.timestamp }}</span>
          <button class="close-btn" @click="clearPrediction">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>

      <div class="result-content">
        <div class="content-body">
          <pre>{{ prediction.content }}</pre>
        </div>

        <div class="suggestion-card">
          <el-icon class="suggestion-icon"><HelpFilled /></el-icon>
          <div class="suggestion-content">
            <h4>AI建议</h4>
            <p>{{ prediction.suggestion }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-overlay">
      <el-icon class="loading-icon"><Loading /></el-icon>
      <p>AI正在分析，请稍候...</p>
    </div>

    <!-- 错误提示 -->
    <div v-if="error" class="error-message">
      <el-icon><Warning /></el-icon>
      <span>{{ error }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { 
  Search, 
  Loading, 
  Close, 
  Warning,
  DataBoard,
  HelpFilled,
  InfoFilled,
  Check
} from '@element-plus/icons-vue';
import { useAIPrediction } from '@/lib/ai';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();
const { loading, prediction, error, analyzeRootCause, predictTrend, generateSummary, queryAI, clearPrediction } = useAIPrediction();

const activeFeature = ref<string | null>(null);
const queryInput = ref('');

function getResultIcon(type: string) {
  const iconsMap: Record<string, typeof InfoFilled> = {
    root_cause: Search,
    trend: DataBoard,
    summary: InfoFilled,
    query: InfoFilled
  };
  return iconsMap[type] || InfoFilled;
}

async function handleFeatureClick(feature: string) {
  activeFeature.value = feature;
  
  if (feature === 'query') {
    return;
  }
  
  const input = '系统预警数据';
  
  switch (feature) {
    case 'summary':
      await generateSummary(input);
      break;
    case 'trend':
      await predictTrend(input);
      break;
    case 'root_cause':
      await analyzeRootCause(input);
      break;
  }
}

async function submitQuery() {
  if (!queryInput.value.trim() || loading.value) return;
  await queryAI(queryInput.value);
  queryInput.value = '';
}
</script>

<style scoped>
.ai-prediction-container {
  background: linear-gradient(135deg, #0f172a 0%, var(--color-text-1) 100%);
  border-radius: 16px;
  padding: 24px;
  min-height: 420px;
  border: 1px solid rgba(99, 102, 241, 0.2);
  box-shadow: 0 4px 24px rgba(99, 102, 241, 0.1);
}

.ai-service-selector {
  margin-bottom: 20px;
}

.service-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.service-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 14px;
}

.service-tab:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(99, 102, 241, 0.5);
}

.service-tab.active {
  background: rgba(99, 102, 241, 0.2);
  border-color: rgba(99, 102, 241, 0.8);
  color: #fff;
}

.service-tab .el-icon {
  width: 18px;
  height: 18px;
}

.ai-features {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 1200px) {
  .ai-features {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .ai-features {
    grid-template-columns: 1fr;
  }
}

.feature-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.feature-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.5), transparent);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.feature-card:hover::before {
  opacity: 1;
}

.feature-card:hover {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.4);
  transform: translateY(-4px);
  box-shadow: 0 8px 32px rgba(99, 102, 241, 0.15);
}

.feature-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}

.feature-icon .el-icon {
  font-size: 26px;
}

.summary-icon {
  background: linear-gradient(135deg, var(--color-accent), var(--color-accent));
}

.trend-icon {
  background: linear-gradient(135deg, var(--color-warning), var(--color-danger));
}

.root-cause-icon {
  background: linear-gradient(135deg, var(--color-accent), var(--color-accent));
}

.query-icon {
  background: linear-gradient(135deg, var(--color-success), var(--color-accent));
}

.feature-card h3 {
  color: #fff;
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 8px 0;
}

.feature-card p {
  color: rgba(255, 255, 255, 0.55);
  font-size: 13px;
  margin: 0;
  line-height: 1.6;
}

.query-input-section {
  margin-bottom: 20px;
}

.query-input-wrapper {
  display: flex;
  gap: 8px;
  align-items: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 8px;
}

.query-icon {
  color: rgba(255, 255, 255, 0.5);
  width: 24px;
  height: 24px;
  margin-left: 8px;
}

.query-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #fff;
  font-size: 14px;
  padding: 8px;
}

.query-input::placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.submit-btn {
  background: rgba(99, 102, 241, 0.6);
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  color: #fff;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.submit-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.8);
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.submit-btn .el-icon {
  width: 20px;
  height: 20px;
}

.submit-btn .el-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.prediction-result {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 12px;
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: rgba(99, 102, 241, 0.1);
  border-bottom: 1px solid rgba(99, 102, 241, 0.2);
}

.result-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-title .el-icon {
  width: 24px;
  height: 24px;
  color: var(--color-accent);
}

.result-title h2 {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12px;
}

.confidence {
  color: var(--color-success);
  padding: 4px 8px;
  background: rgba(31, 138, 91, 0.1);
  border-radius: 4px;
}

.timestamp {
  color: rgba(255, 255, 255, 0.5);
}

.close-btn {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.result-content {
  padding: 20px;
}

.content-body {
  background: rgba(255, 255, 255, 0.02);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.content-body pre {
  color: rgba(255, 255, 255, 0.9);
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  margin: 0;
}

.suggestion-card {
  display: flex;
  gap: 12px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(180, 35, 24, 0.05));
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 8px;
  padding: 16px;
}

.suggestion-icon {
  width: 32px;
  height: 32px;
  color: var(--color-warning);
  flex-shrink: 0;
}

.suggestion-content h4 {
  color: var(--color-warning);
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px 0;
}

.suggestion-content p {
  color: rgba(255, 255, 255, 0.8);
  font-size: 13px;
  margin: 0;
  line-height: 1.6;
}

.loading-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 16px;
}

.loading-icon {
  width: 48px;
  height: 48px;
  color: var(--color-accent);
  animation: spin 1s linear infinite;
}

.loading-overlay p {
  color: rgba(255, 255, 255, 0.6);
  font-size: 14px;
}

.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-danger);
  background: rgba(180, 35, 24, 0.1);
  border: 1px solid rgba(180, 35, 24, 0.3);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 14px;
}

.error-message .el-icon {
  width: 20px;
  height: 20px;
}
</style>
