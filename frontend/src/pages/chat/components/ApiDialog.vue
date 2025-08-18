<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useApiKeyStore } from '@/stores/apiKeys'
import { CheckCircle, XCircle } from 'lucide-vue-next'
import { validateApiKey, saveApiConfig } from '@/apis/apiKeyApi'

const apiKeyStore = useApiKeyStore()

// 本地表单数据
const form = ref<{
  coordinator: { apiKey: string; baseUrl: string; modelId: string };
  modeler: { apiKey: string; baseUrl: string; modelId: string };
  coder: { apiKey: string; baseUrl: string; modelId: string };
  writer: { apiKey: string; baseUrl: string; modelId: string };
}>({
  coordinator: {
    apiKey: '',
    baseUrl: '',
    modelId: ''
  },
  modeler: {
    apiKey: '',
    baseUrl: '',
    modelId: ''
  },
  coder: {
    apiKey: '',
    baseUrl: '',
    modelId: ''
  },
  writer: {
    apiKey: '',
    baseUrl: '',
    modelId: ''
  }
})

// 验证状态
const validating = ref(false)
const validationResults = ref({
  coordinator: { valid: false, message: '' },
  modeler: { valid: false, message: '' },
  coder: { valid: false, message: '' },
  writer: { valid: false, message: '' }
})

// 计算所有验证是否都通过
const allValid = computed(() => {
  return Object.values(validationResults.value).every(result => result.valid)
})

// 模型配置列表
const modelConfigs = computed(() => [
  { key: 'coordinator', label: '协调者模型配置' },
  { key: 'modeler', label: '建模手模型配置' },
  { key: 'coder', label: '代码手模型配置' },
  { key: 'writer', label: '论文手模型配置' }
])

// 从 store 加载数据到表单
const loadFromStore = () => {
  form.value.coordinator = { ...apiKeyStore.coordinatorConfig }
  form.value.modeler = { ...apiKeyStore.modelerConfig }
  form.value.coder = { ...apiKeyStore.coderConfig }
  form.value.writer = { ...apiKeyStore.writerConfig }
}

// 保存表单数据到 store
const saveToStore = async () => {
  // 先保存到前端 store
  apiKeyStore.setCoordinatorConfig(form.value.coordinator)
  apiKeyStore.setModelerConfig(form.value.modeler)
  apiKeyStore.setCoderConfig(form.value.coder)
  apiKeyStore.setWriterConfig(form.value.writer)

  // 如果验证成功，也保存到后端设置
  if (allValid.value) {
    try {
      await saveApiConfig({
        coordinator: form.value.coordinator,
        modeler: form.value.modeler,
        coder: form.value.coder,
        writer: form.value.writer
      })
    } catch (error) {
      console.error('保存配置到后端失败:', error)
    }
  }
}

// 组件挂载时加载数据
onMounted(() => {
  loadFromStore()
})

// 定义 emits
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

// 定义 props
const props = defineProps<{ open: boolean }>()

// 更新 open 状态
const updateOpen = (value: boolean) => {
  emit('update:open', value)
}

// 保存并关闭
const saveAndClose = async () => {
  await saveToStore()
  updateOpen(false)
}

// 验证大模型 API Key
const validateModelApiKey = async (config: { apiKey: string, baseUrl: string, modelId: string }) => {
  if (!config.apiKey) {
    return { valid: false, message: 'API Key 为空' }
  }

  if (!config.modelId) {
    return { valid: false, message: 'Model ID 为空' }
  }

  try {
    // 调用后端验证接口
    const result = await validateApiKey({
      api_key: config.apiKey,
      base_url: config.baseUrl || 'https://api.openai.com/v1',
      model_id: config.modelId
    })

    return {
      valid: result.data.valid,
      message: result.data.message
    }
  } catch (error) {
    return {
      valid: false,
      message: '✗ 验证失败: 无法连接到验证服务'
    }
  }
}

// 一键验证所有 API Keys
const validateAllApiKeys = async () => {
  validating.value = true

  // 只清空验证结果，保留用户输入的数据
  validationResults.value = {
    coordinator: { valid: false, message: '' },
    modeler: { valid: false, message: '' },
    coder: { valid: false, message: '' },
    writer: { valid: false, message: '' }
  }

  try {


    // 在 E2B 验证后等待 500ms
    await new Promise(resolve => setTimeout(resolve, 500))

    // 逐个验证各模型 API Keys，避免并发请求
    for (const config of modelConfigs.value) {
      const key = config.key as keyof typeof validationResults.value
      const formKey = config.key as keyof typeof form.value

      // 设置当前验证中状态
      validationResults.value[key] = { valid: false, message: '验证中...' }

      // 验证当前配置
      validationResults.value[key] = await validateModelApiKey(form.value[formKey] as { apiKey: string, baseUrl: string, modelId: string })

      // 每次验证后等待 1 秒，避免触发速率限制
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  } catch (error) {
    console.error('验证过程中发生错误:', error)
    // 显示全局错误
    for (const key of Object.keys(validationResults.value)) {
      if (!validationResults.value[key as keyof typeof validationResults.value].message) {
        validationResults.value[key as keyof typeof validationResults.value] = {
          valid: false,
          message: '验证过程中发生未知错误'
        }
      }
    }
  } finally {
    validating.value = false
  }
}

const links = {
  "DeepSeek": {
    "url": "https://platform.deepseek.com/api_keys",
    "key": "DeepSeek",
    "BaseURL": "https://api.deepseek.com",
    "ModelID": "deepseek/deepseek-chat"
  },
  "硅基流动": {
    "url": "https://cloud.siliconflow.cn/i/UIb4Enf4",
    "key": "硅基流动",
    "BaseURL": "https://api.siliconflow.cn",
    "ModelID": "openai/deepseek-ai/DeepSeek-V3"
  },
  "Sophnet": {
    "url": "https://www.sophnet.com/#?code=AZBSFG",
    "key": "Sophnet",
    "BaseURL": "https://www.sophnet.com/api/open-apis",
    "ModelID": "openai/DeepSeek-V3-Fast"
  },
  "OpenAI": {
    "url": "https://platform.openai.com/api-keys",
    "key": "OpenAI",
    "BaseURL": "https://api.openai.com",
    "ModelID": "openai/gpt-4o"
  }
}

</script>

<template>
  <Dialog :open="props.open" @update:open="updateOpen">
    <DialogContent class="max-w-xl max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>API Key 设置</DialogTitle>
        <DialogDescription>
          为每个 Agent 配置合适模型
          <br>
          <div class="">
            <div v-for="link in links" :key="link.key">
              <div class="flex flex-col gap-1">
                <a :href="link.url" target="_blank" class="text-blue-600 hover:text-blue-800 underline text-xs">
                  {{ link.key }}
                </a>
                <div class="text-xs text-muted-foreground">
                  Base URL: {{ link.BaseURL }}
                </div>
                <div class="text-xs text-muted-foreground">
                  Model ID: {{ link.ModelID }}
                </div>
              </div>
            </div>
          </div>
          <div><a href="https://docs.litellm.ai/docs/providers" target="_blank"
              class="text-blue-600 hover:text-blue-800 underline text-xs">
              more details
            </a>
          </div>
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-4 py-2">

        <!-- Models Configurations -->
        <div v-for="config in modelConfigs" :key="config.key" class="space-y-2">
          <h3 class="text-sm font-medium">{{ config.label }}</h3>
          <div class="grid grid-cols-1 gap-2">
            <div class="space-y-1">
              <Label :for="`${config.key}-api-key`" class="text-xs text-muted-foreground">API Key</Label>
              <div class="flex items-center gap-2">
                <Input :id="`${config.key}-api-key`" v-model="(form as any)[config.key].apiKey" type="password"
                  placeholder="请输入 API Key" class="h-7 text-xs flex-1" />
                <div v-if="validationResults[config.key as keyof typeof validationResults].message"
                  class="flex items-center">
                  <CheckCircle v-if="validationResults[config.key as keyof typeof validationResults].valid"
                    class="h-4 w-4 text-green-500" />
                  <XCircle v-else class="h-4 w-4 text-red-500" />
                </div>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div class="space-y-1">
                <Label :for="`${config.key}-base-url`" class="text-xs text-muted-foreground">Base URL</Label>
                <Input :id="`${config.key}-base-url`" v-model="(form as any)[config.key].baseUrl"
                  placeholder="https://api.deepseek.com" class="h-7 text-xs" />
              </div>
              <div class="space-y-1">
                <Label :for="`${config.key}-model-id`" class="text-xs text-muted-foreground">Model ID</Label>
                <Input :id="`${config.key}-model-id`" v-model="(form as any)[config.key].modelId"
                  placeholder="provider/model_id" class="h-7 text-xs" />
              </div>
            </div>
            <div v-if="validationResults[config.key as keyof typeof validationResults].message" :class="[
              'text-xs px-2 py-1 rounded text-left border',
              validationResults[config.key as keyof typeof validationResults].valid ? 'bg-green-50 text-green-700 border-green-200' : 'bg-red-50 text-red-700 border-red-200'
            ]">
              {{ validationResults[config.key as keyof typeof validationResults].message }}
            </div>
          </div>
        </div>
      </div>

      <div class="flex justify-between items-center pt-3 border-t">
        <Button @click="validateAllApiKeys" :disabled="validating" class="h-7 text-xs px-3" variant="secondary">
          {{ validating ? '验证中...' : '一键验证' }}
        </Button>
        <div class="flex space-x-2">
          <Button variant="outline" @click="updateOpen(false)" class="h-7 text-xs px-3">
            取消
          </Button>
          <Button v-if="allValid" @click="saveAndClose" class="h-7 text-xs px-3">
            保存
          </Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
