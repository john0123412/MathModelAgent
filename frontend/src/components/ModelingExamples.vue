<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { useRouter } from 'vue-router'

// 定义样例类型
interface ModelingExample {
  id: number
  title: string
  source: string
  description: string
  tags: string[]
  problemText: string
}

const router = useRouter()
const examples = ref<ModelingExample[]>([
  {
    id: 1,
    title: "基于改进随机森林算法的农作物产量预测",
    source: "2023年高教社杯全国大学生数学建模竞赛",
    description: "通过历史气象和产量数据，建立农作物产量预测模型。",
    tags: ["随机森林", "数据分析", "气象预测"],
    problemText: "给定历年中国主要粮食作物产量数据及气象数据，建立一个预测模型，预测未来五年的粮食产量，并分析气候变化对粮食产量的影响。"
  },
  {
    id: 2,
    title: "共享单车潮汐调度优化研究",
    source: "2022年美国大学生数学建模竞赛",
    description: "针对城市高峰期共享单车分布不均问题，构建调度优化模型。",
    tags: ["图论", "线性规划", "智能调度"],
    problemText: "针对共享单车系统在早晚高峰期出现的车辆分布不均问题，构建一个优化调度模型，最小化调度成本同时满足用户需求。"
  },
  {
    id: 3,
    title: "新冠疫情传播模型与干预策略评估",
    source: "2021年高教社杯全国大学生数学建模竞赛",
    description: "基于SEIR模型改进的传染病传播预测与防控策略分析。",
    tags: ["微分方程", "蒙特卡洛", "策略评估"],
    problemText: "基于已有的疫情数据，构建传染病传播模型，模拟不同干预措施对疫情发展的影响，为防控决策提供科学依据。"
  }
])

// 选择样例并跳转到任务创建步骤
const selectExample = (example: ModelingExample) => {
  // 这里可以存储选中的样例数据到 localStorage 或 pinia store
  localStorage.setItem('selectedExample', JSON.stringify(example))
  // 跳转到任务创建流程
  router.push('/task/create')
}


</script>

<template>
  <div class="mt-8 mb-12">
    <h2 class="text-xl font-medium mb-4">样例解析</h2>
    <p class="text-sm text-muted-foreground mb-6">浏览历年数模竞赛优秀案例，快速开始你的建模任务</p>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="example in examples" :key="example.id"
        class="border rounded-lg overflow-hidden hover:shadow-md transition-shadow">
        <div class="p-4 border-b bg-muted/30">
          <h3 class="font-medium line-clamp-2">{{ example.title }}</h3>
          <p class="text-xs text-muted-foreground mt-1">{{ example.source }}</p>
        </div>
        <div class="p-4">
          <p class="text-sm text-muted-foreground mb-3">{{ example.description }}</p>
          <div class="flex flex-wrap gap-2 mt-2 mb-3">
            <span v-for="tag in example.tags" :key="tag"
              class="px-2 py-0.5 bg-primary/10 text-primary rounded-full text-xs">
              {{ tag }}
            </span>
          </div>
          <div class="flex gap-2 mt-4">

            <Button variant="default" size="sm" class="flex-1" @click="selectExample(example)">
              基于此开始
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>