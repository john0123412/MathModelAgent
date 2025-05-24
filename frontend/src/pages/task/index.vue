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
import CoderEditor from '@/components/AgentEditor/CoderEditor.vue'
import WriterEditor from '@/components/AgentEditor/WriterEditor.vue'
import ModelerEditor from '@/components/AgentEditor/ModelerEditor.vue'
import ChatArea from '@/components/ChatArea.vue'
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useTaskStore } from '@/stores/task'
import { getWriterSeque } from '@/apis/commonApi';
import { Button } from '@/components/ui/button';
import { openFolderAPI } from '@/apis/commonApi';
import { useToast } from '@/components/ui/toast/use-toast'
import { Folder } from 'lucide-vue-next'
const { toast } = useToast()


const props = defineProps<{ task_id: string }>()
const taskStore = useTaskStore()

const writerSequence = ref<string[]>([]);

console.log('Task ID:', props.task_id)

onMounted(async () => {
  taskStore.connectWebSocket(props.task_id)
  const res = await getWriterSeque();
  writerSequence.value = Array.isArray(res.data) ? res.data : [];
})

const openFolder = async () => {
  const res = await openFolderAPI(props.task_id);
  console.log(res);
  toast({
    title: '打开工作目录成功',
    description: res.data.message,
  })
}


onBeforeUnmount(() => {
  taskStore.closeWebSocket()
})

</script>

<template>
  <div class="fixed inset-0">
    <ResizablePanelGroup direction="horizontal" class="h-full rounded-lg border">
      <ResizablePanel :default-size="40" class="h-full">
        <ChatArea :messages="taskStore.chatMessages" />
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel :default-size="60" class="h-full min-w-0">
        <div class="flex h-full flex-col min-w-0">
          <Tabs default-value="coder" class="w-full h-full flex flex-col">
            <div class="border-b px-4 py-1 flex justify-between">
              <TabsList class="">
                <TabsTrigger value="modeler" class="text-sm">
                  ModelerAgent
                </TabsTrigger>
                <TabsTrigger value="coder" class="text-sm">
                  CoderAgent
                </TabsTrigger>
                <TabsTrigger value="writer" class="text-sm">
                  WriterAgent
                </TabsTrigger>
              </TabsList>
              <!--  TODO: 其他选项 -->

              <div class="flex justify-end gap-2">
                <Button @click="taskStore.downloadMessages" class="flex justify-end">
                  下载消息
                </Button>

                <Button @click="openFolder" class="flex">
                  <Folder class="w-5 h-5" /> workspace
                </Button>
              </div>

            </div>

            <TabsContent value="modeler" class="h-full p-1 flex-1 overflow-auto">
              <Card class="h-full m-2">
                <CardContent class="h-full p-1">
                  <ModelerEditor />
                </CardContent>
              </Card>
            </TabsContent>

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

<style scoped></style>