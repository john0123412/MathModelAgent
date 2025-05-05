<script setup lang="ts">
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import {
  Card,
  CardContent,
} from '@/components/ui/card'
import CoderEditor from '@/components/CoderEditor.vue'
import WriterEditor from '@/components/WriterEditor.vue'
import ChatArea from '@/components/ChatArea.vue'
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useTaskStore } from '@/stores/task'
import { ScrollArea } from '@/components/ui/scroll-area'
import { getWriterSeque } from '@/apis/commonApi';
import { Button } from '@/components/ui/button';

const props = defineProps<{ task_id: string }>()
const taskStore = useTaskStore()

const writerSequence = ref<string[]>([]);

console.log('Task ID:', props.task_id)

onMounted(async () => {
  taskStore.connectWebSocket(props.task_id)
  const res = await getWriterSeque();
  writerSequence.value = Array.isArray(res.data) ? res.data : [];
})


onBeforeUnmount(() => {
  taskStore.closeWebSocket()
})

</script>

<template>
  <div class="fixed inset-0">
    <ResizablePanelGroup direction="horizontal" class="h-full rounded-lg border">
      <ResizablePanel :default-size="30" class="h-full">
        <ChatArea :messages="taskStore.chatMessages" />
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel :default-size="70" class="h-full min-w-0">
        <div class="flex h-full flex-col min-w-0">
          <Tabs default-value="coder" class="w-full h-full flex flex-col">
            <div class="border-b px-4 py-1 flex justify-between">
              <TabsList class="">
                <TabsTrigger value="coder" class="text-sm">
                  CoderAgent
                </TabsTrigger>
                <TabsTrigger value="writer" class="text-sm">
                  WriterAgent
                </TabsTrigger>
              </TabsList>
              <!--  TODO: 其他选项 -->
              <Button @click="taskStore.downloadMessages" class="flex justify-end">
                下载消息
              </Button>
            </div>

            <TabsContent value="coder" class="h-full p-1 flex-1 overflow-auto">
              <Card class="h-full m-2">
                <CardContent class="h-full p-1">
                  <CoderEditor />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="writer" class="flex-1 p-1 min-w-0 h-full overflow-auto">
              <Card class="min-w-0 rounded-lg">
                <CardContent class="p-2 h-full min-w-0 overflow-auto">
                  <WriterEditor :messages="taskStore.writerMessages" :writerSequence="writerSequence" />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>

  </div>
</template>

<style scoped>
:deep(body),
:deep(html) {
  overflow: hidden;
  height: 100%;
  margin: 0;
  padding: 0;
}
</style>