<script setup lang="ts">
import { computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import NotebookCell from '@/components/NotebookCell.vue'
import type { NoteCell, CodeCell, ResultCell } from '@/utils/interface'

// 使用任务存储
const taskStore = useTaskStore()

// 将代码消息转换为Notebook单元格
const cells = computed<NoteCell[]>(() => {
  const notebookCells: NoteCell[] = []

  // 筛选出CoderAgent消息
  for (const msg of taskStore.coderMessages) {
    console.log('Coder message:', msg)
    // 处理代码和执行结果
    if (msg.code) {
      // 添加代码单元格
      const codeCell: CodeCell = {
        type: 'code',
        content: msg.code
      }
      notebookCells.push(codeCell)
  
    }

    // 如果有执行结果，添加结果单元格
    if (msg.code_results && msg.code_results.length > 0) {
      const resultCell: ResultCell = {
        type: 'result',
        code_results: msg.code_results
      }
      notebookCells.push(resultCell)
    }
  }

  return notebookCells
})
</script>

<template>
  <div class="flex-1 px-1 pt-1 pb-4 h-full overflow-y-auto">
    <!-- 遍历所有单元格 -->
    <div v-for="(cell, index) in cells" :key="index" 
         :class="[
           'transform transition-all duration-200 hover:shadow-lg', 
           cell.type === 'code' ? 'pt-2' : 'pt-0'
         ]">
      <NotebookCell :cell="cell" />
    </div>
    
    <!-- 无内容时的提示 -->
    <div v-if="cells.length === 0" class="flex items-center justify-center h-full">
      <div class="text-gray-400 text-center p-8">
        <div class="text-4xl mb-2">📝</div>
        <div class="text-lg font-medium">暂无代码执行结果</div>
        <div class="text-sm">执行代码后将在此显示结果</div>
      </div>
    </div>
    <!-- 添加底部空间 -->
    <div class="h-4"></div>
  </div>
</template>

<style>
/* 自定义滚动条 */
::-webkit-scrollbar {
  width: 0.375rem;
  height: 0.375rem;
}

::-webkit-scrollbar-track {
  background-color: rgb(243 244 246);
  border-radius: 9999px;
}

::-webkit-scrollbar-thumb {
  background-color: rgb(209 213 219);
  border-radius: 9999px;
}

::-webkit-scrollbar-thumb:hover {
  background-color: rgb(156 163 175);
  transition-property: background-color;
  transition-duration: 200ms;
}

/* 代码高亮样式 */
.hljs {
  background-color: rgb(249 250 251);
  padding: 1rem;
  border-radius: 0.5rem;
  margin-top: 0.5rem;
  margin-bottom: 0.5rem;
}

/* 数学公式样式 */
.katex-display {
  margin-top: 1rem;
  margin-bottom: 1rem;
  overflow-x: auto;
}

.katex {
  font-size: 1rem;
}
</style>
