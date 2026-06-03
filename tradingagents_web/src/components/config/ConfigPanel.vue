<template>
  <div class="config-wrapper">
    <div class="config-card">
      <h1 class="title">TradingAgents</h1>
      <p class="subtitle">多智能体金融分析系统</p>

      <div class="form">
        <div class="field">
          <label>股票代码</label>
          <input
            v-model="ticker"
            type="text"
            placeholder="例如 AAPL, 0700.HK, BTC-USD"
            class="input"
            @keyup.enter="tryStart"
          />
        </div>

        <div class="field">
          <label>分析日期</label>
          <input v-model="analysisDate" type="date" class="input" />
        </div>

        <div class="field">
          <label>资产类型</label>
          <div class="toggle-group">
            <button
              :class="['toggle-btn', { active: assetType === 'stock' }]"
              @click="assetType = 'stock'"
            >股票</button>
            <button
              :class="['toggle-btn', { active: assetType === 'crypto' }]"
              @click="assetType = 'crypto'"
            >加密货币</button>
          </div>
        </div>

        <div class="field">
          <label>数据供应商</label>
          <select v-model="dataVendorPreset" class="input">
            <option value="preset_us">美国市场（标准）</option>
            <option value="preset_china">中国 A 股</option>
            <option value="preset_hk">港股</option>
            <option value="custom">自定义</option>
          </select>
        </div>

        <div class="field">
          <label>分析师</label>
          <div class="checkbox-group">
            <label v-for="a in analystOptions" :key="a.id" class="checkbox-label">
              <input v-model="selectedAnalysts" type="checkbox" :value="a.id" />
              {{ a.name }}
            </label>
          </div>
        </div>

        <div class="field">
          <label>LLM 供应商</label>
          <select v-model="llmProvider" class="input" :disabled="loadingConfig">
            <option v-if="loadingConfig" value="">加载中...</option>
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>

        <div class="field" v-if="modelOptions.quick.length > 0">
          <label>快速思考模型</label>
          <select v-model="shallowThinker" class="input">
            <option v-for="m in modelOptions.quick" :key="m[1]" :value="m[1]">{{ m[0] }}</option>
          </select>
        </div>

        <div class="field" v-if="modelOptions.deep.length > 0">
          <label>深度思考模型</label>
          <select v-model="deepThinker" class="input">
            <option v-for="m in modelOptions.deep" :key="m[1]" :value="m[1]">{{ m[0] }}</option>
          </select>
        </div>

        <div class="field">
          <label>分析模式</label>
          <div class="toggle-group research-depth">
            <button
              v-for="opt in depthOptions"
              :key="opt.value"
              :class="['toggle-btn', { active: researchDepth === opt.value }]"
              @click="researchDepth = opt.value"
            >{{ opt.label }}</button>
          </div>
        </div>

        <div class="field">
          <label>输出语言</label>
          <select v-model="outputLanguage" class="input">
            <option value="English">English</option>
            <option value="Chinese">中文</option>
          </select>
        </div>

        <div class="field position-section">
          <div class="position-header" @click="showPosition = !showPosition">
            <span class="position-toggle">{{ showPosition ? '▾' : '▸' }}</span>
            <label>当前持仓 <span class="optional-badge">可选</span></label>
          </div>
          <div v-if="showPosition" class="position-body">
            <label class="checkbox-label">
              <input v-model="holdsStock" type="checkbox" />
              持有该股票
            </label>
            <div v-if="holdsStock" class="position-fields">
              <input
                v-model.number="positionQuantity"
                type="number"
                placeholder="持有数量（股）"
                class="input"
                min="0"
              />
              <input
                v-model.number="positionAvgCost"
                type="number"
                placeholder="平均成本价（可选）"
                class="input"
                min="0"
                step="0.01"
              />
            </div>
          </div>
        </div>

        <div v-if="store.errorMessage" class="error-msg">{{ store.errorMessage }}</div>
        <div v-else-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

        <button
          class="start-btn"
          :disabled="!canStart"
          @click="tryStart"
        >
          {{ connecting ? '连接中...' : '开始分析' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, inject, onMounted, watch } from 'vue'
import { useAnalysisStore } from '../../stores/analysis'

interface WsApi {
  startAnalysis: (config: any) => void
  connect: (url?: string) => void
}

const ws = inject<WsApi>('ws')!
const store = useAnalysisStore()

const ticker = ref('')
const analysisDate = ref('')
const assetType = ref('stock')
const selectedAnalysts = ref<string[]>(['market', 'social', 'news', 'fundamentals'])
const llmProvider = ref('openai')
const outputLanguage = ref('Chinese')
const researchDepth = ref(1)
const dataVendorPreset = ref('preset_us')
const shallowThinker = ref('')
const deepThinker = ref('')
const showPosition = ref(false)
const holdsStock = ref(false)
const positionQuantity = ref<number | null>(null)
const positionAvgCost = ref<number | null>(null)
const modelOptions = ref<{ quick: string[]; deep: string[] }>({ quick: [], deep: [] })
const errorMsg = ref('')
const connecting = ref(false)

const depthOptions = [
  { value: 1, label: '快速' },
  { value: 3, label: '标准' },
  { value: 5, label: '深度' },
]

interface ProviderItem {
  id: string
  name: string
}

// Keys must match backend: AnalystType enum & ANALYST_MAPPING
const analystOptions = [
  { id: 'market', name: '市场分析师' },
  { id: 'social', name: '情绪分析师' },
  { id: 'news', name: '新闻分析师' },
  { id: 'fundamentals', name: '基本面分析师' },
]

const providers = ref<ProviderItem[]>([])
const loadingConfig = ref(true)

const canStart = computed(() => {
  return ticker.value.trim() && selectedAnalysts.value.length > 0 && store.connected
})

async function fetchProviders() {
  try {
    const res = await fetch(`http://${location.hostname}:8000/api/config/providers`)
    if (res.ok) {
      const data = await res.json()
      providers.value = data.providers
    }
  } catch {
    // Fallback to hardcoded defaults if backend unreachable
    providers.value = [
      { id: 'openai', name: 'OpenAI' },
      { id: 'anthropic', name: 'Anthropic' },
      { id: 'google', name: 'Google Gemini' },
      { id: 'xai', name: 'xAI (Grok)' },
      { id: 'deepseek', name: 'DeepSeek' },
      { id: 'qwen', name: 'Qwen (Global)' },
      { id: 'glm', name: 'GLM (Z.AI)' },
      { id: 'ollama', name: 'Ollama (Local)' },
    ]
  }
}

async function fetchModels(provider: string) {
  try {
    const res = await fetch(`http://${location.hostname}:8000/api/config/models?provider=${provider}`)
    if (res.ok) {
      const data = await res.json()
      modelOptions.value = {
        quick: data.models?.quick || [],
        deep: data.models?.deep || [],
      }
      // Set defaults to first available model id if current is empty
      if (!shallowThinker.value && modelOptions.value.quick.length > 0) {
        shallowThinker.value = modelOptions.value.quick[0][1]
      }
      if (!deepThinker.value && modelOptions.value.deep.length > 0) {
        deepThinker.value = modelOptions.value.deep[0][1]
      }
    }
  } catch {
    // Backend unreachable — leave defaults empty
  }
}

function resolveDataVendors(): Record<string, string> {
  const presets: Record<string, Record<string, string>> = {
    preset_us: {},
    preset_china: {
      core_stock_apis: 'akshare',
      fundamental_data: 'akshare',
      news_data: 'eastmoney',
      social_sentiment: 'all',
    },
    preset_hk: {
      news_data: 'sina_finance',
      social_sentiment: 'all',
    },
  }
  return presets[dataVendorPreset.value] || {}
}

onMounted(async () => {
  const d = new Date()
  analysisDate.value = d.toISOString().slice(0, 10)
  await fetchProviders()
  await fetchModels(llmProvider.value)
  loadingConfig.value = false
})

watch(llmProvider, (val) => {
  shallowThinker.value = ''
  deepThinker.value = ''
  fetchModels(val)
})

function tryStart() {
  errorMsg.value = ''

  if (!ticker.value.trim()) {
    errorMsg.value = '请输入股票代码'
    return
  }
  if (selectedAnalysts.value.length === 0) {
    errorMsg.value = '请至少选择一个分析师'
    return
  }
  if (!store.connected) {
    connecting.value = true
    ws.connect()
    setTimeout(() => {
      connecting.value = false
      if (!store.connected) {
        errorMsg.value = '无法连接到服务器，请确认后端已启动'
      }
    }, 3000)
    return
  }

  ws.startAnalysis({
    ticker: ticker.value.trim().toUpperCase(),
    analysis_date: analysisDate.value,
    analysts: selectedAnalysts.value,
    research_depth: researchDepth.value,
    llm_provider: llmProvider.value,
    backend_url: null,
    shallow_thinker: shallowThinker.value,
    deep_thinker: deepThinker.value,
    google_thinking_level: null,
    openai_reasoning_effort: null,
    anthropic_effort: null,
    output_language: outputLanguage.value,
    data_vendors: resolveDataVendors(),
    asset_type: assetType.value,
    checkpoint_enabled: false,
    api_keys: {},
    holds_stock: holdsStock.value,
    position_quantity: positionQuantity.value,
    position_avg_cost: positionAvgCost.value,
  })
}
</script>

<style scoped>
.config-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--bg-primary);
}

.config-card {
  width: 420px;
  max-width: 90vw;
  padding: 40px 36px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.title {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-green);
  text-align: center;
  margin: 0 0 4px;
}

.subtitle {
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
  margin: 0 0 28px;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.input {
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 14px;
  background: var(--bg-input);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s;
}

.input:focus {
  border-color: var(--color-blue);
}

select.input {
  cursor: pointer;
}

.toggle-group {
  display: flex;
  gap: 8px;
}

.toggle-btn {
  flex: 1;
  padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg-input);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.toggle-btn.active {
  background: rgba(66, 165, 245, 0.15);
  border-color: var(--color-blue);
  color: var(--color-blue);
}

.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  padding: 4px 0;
}

.checkbox-label input {
  accent-color: var(--color-blue);
}

.error-msg {
  color: var(--color-red);
  font-size: 13px;
  text-align: center;
  padding: 4px 0;
}

.start-btn {
  padding: 10px 24px;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  margin-top: 4px;
  background: var(--color-green);
  color: #fff;
}

.start-btn:hover:not(:disabled) {
  filter: brightness(1.15);
}

.start-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.position-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}

.position-toggle {
  font-size: 11px;
  color: var(--text-dim);
  width: 12px;
}

.optional-badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
  text-transform: none;
  letter-spacing: normal;
}

.position-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 0 4px;
}

.position-body .checkbox-label {
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  text-transform: none;
  letter-spacing: normal;
}

.position-body .checkbox-label input {
  accent-color: var(--color-blue);
}

.position-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
