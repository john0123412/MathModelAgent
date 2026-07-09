<script setup lang="ts">
import {
	approveModeling,
	getWriterSeque,
	listTasks,
	resumeTask,
	type TaskInfo,
} from "@/apis/commonApi";
import CoderEditor from "@/components/AgentEditor/CoderEditor.vue";
import ModelerEditor from "@/components/AgentEditor/ModelerEditor.vue";
import WriterEditor from "@/components/AgentEditor/WriterEditor.vue";
import ChatArea from "@/components/ChatArea.vue";
import { Button } from "@/components/ui/button";
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import FilesSheet from "@/pages/task/components/FileSheet.vue";
import { useTaskStore } from "@/stores/task";
import { onBeforeUnmount, onMounted, ref } from "vue";

// ---- Props ----

const props = defineProps<{ task_id: string }>();

// ---- Reactive State ----

const taskStore = useTaskStore();

/** 论文写作顺序 */
const writerSequence = ref<string[]>([]);

/** 运行时长相关状态 */
const startTime = ref<number>(Date.now());
const currentTime = ref<number>(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;

/** 格式化运行时长为可读字符串 */
const formatDuration = (ms: number): string => {
	const seconds = Math.floor(ms / 1000);
	const hours = Math.floor(seconds / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const remainingSeconds = seconds % 60;

	if (hours > 0) {
		return `${hours}h ${minutes}m ${remainingSeconds}s`;
	}
	if (minutes > 0) {
		return `${minutes}m ${remainingSeconds}s`;
	}
	return `${remainingSeconds}s`;
};

/** 运行时长显示值 */
const runningDuration = ref<string>("0s");

/** 是否正在请求停止 */
const isStopping = ref(false);

/** 任务是否处于可续传的中断状态 */
const isInterrupted = ref(false);

/** 任务是否正在等待人工确认建模方案 */
const isWaitingModelingReview = ref(false);

/** 是否正在请求续传 */
const isResuming = ref(false);

/** 是否正在请求审批建模方案 */
const isApprovingModeling = ref(false);

/** 更新运行时长 */
const updateDuration = () => {
	currentTime.value = Date.now();
	runningDuration.value = formatDuration(currentTime.value - startTime.value);
};

const getSafeErrorMessage = (error: unknown) => {
	if (error && typeof error === "object" && "response" in error) {
		const response = (error as { response?: { status?: number } }).response;
		return `status=${response?.status ?? "unknown"}`;
	}
	return error instanceof Error ? error.message : "unknown error";
};

/** 处理停止运行 */
async function handleStop() {
	isStopping.value = true;
	await taskStore.stopTask(props.task_id);
	isStopping.value = false;
}

const applyTaskStatus = (task: TaskInfo | undefined) => {
	isInterrupted.value = task?.status === "interrupted";
	isWaitingModelingReview.value = task?.status === "waiting_review";
};

/** 检查当前任务状态，用于展示续传/审批按钮 */
async function refreshTaskStatus() {
	try {
		const res = await listTasks();
		const task = res.data.find((t) => t.task_id === props.task_id);
		applyTaskStatus(task);
	} catch (error) {
		console.error("获取任务状态失败:", getSafeErrorMessage(error));
	}
}

/** 处理继续任务：调用 resume 接口，成功后重新连接 WebSocket 并刷新状态 */
async function handleResume() {
	isResuming.value = true;
	try {
		await resumeTask(props.task_id);
		await refreshTaskStatus();
		await taskStore.loadTaskMessages(props.task_id);
		taskStore.connectWebSocket(props.task_id);
	} catch (error) {
		console.error("续传任务失败:", getSafeErrorMessage(error));
	} finally {
		isResuming.value = false;
	}
}

/** 确认建模方案：调用 approve-modeling 接口后从 Coder 阶段继续 */
async function handleApproveModeling() {
	isApprovingModeling.value = true;
	try {
		await approveModeling(props.task_id);
		isWaitingModelingReview.value = false;
		await taskStore.loadTaskMessages(props.task_id);
		taskStore.connectWebSocket(props.task_id);
		await refreshTaskStatus();
	} catch (error) {
		console.error("确认建模方案失败:", getSafeErrorMessage(error));
	} finally {
		isApprovingModeling.value = false;
	}
}

// ---- Lifecycle Hooks ----

onMounted(async () => {
	await taskStore.loadTaskMessages(props.task_id);
	taskStore.connectWebSocket(props.task_id);
	const res = await getWriterSeque();
	writerSequence.value = Array.isArray(res.data) ? res.data : [];
	await refreshTaskStatus();

	// 开始计时
	timer = setInterval(updateDuration, 1000);
	updateDuration(); // 立即更新一次
});

onBeforeUnmount(() => {
	taskStore.closeWebSocket();
	// 清理计时器
	if (timer) {
		clearInterval(timer);
		timer = null;
	}
});
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
          <Tabs default-value="modeler" class="w-full h-full flex flex-col">
            <!-- TODO: Agent 的状态 -->
            <div class="border-b px-4 py-1 flex justify-between">
              <div class="flex items-center gap-4">
                <div class="text-sm text-gray-600">
                  运行时长: <span class="font-mono text-blue-600">{{ runningDuration }}</span>
                </div>
                <div class="flex items-center gap-1.5 text-sm">
                  <span
                    class="inline-block h-2 w-2 rounded-full"
                    :class="{
                      'bg-green-500': taskStore.wsStatus === 'connected',
                      'bg-yellow-500 animate-pulse': taskStore.wsStatus === 'connecting' || taskStore.wsStatus === 'reconnecting',
                      'bg-red-500': taskStore.wsStatus === 'disconnected',
                    }"
                  />
                  <span class="text-gray-500">
                    {{
                      taskStore.wsStatus === 'connected' ? '已连接'
                      : taskStore.wsStatus === 'connecting' ? '连接中'
                      : taskStore.wsStatus === 'reconnecting' ? '重连中'
                      : '未连接'
                    }}
                  </span>
                </div>
                <TabsList>
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
              </div>
              <!--  TODO: 其他选项 -->

              <div class="flex justify-end gap-2 items-center">
                <span
                  v-if="isWaitingModelingReview"
                  class="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1"
                >
                  建模方案待确认
                </span>
                <Button
                  v-if="isWaitingModelingReview"
                  variant="default"
                  :disabled="isApprovingModeling"
                  @click="handleApproveModeling"
                >
                  {{ isApprovingModeling ? "确认中..." : "确认建模方案并继续" }}
                </Button>
                <Button
                  v-if="isInterrupted"
                  variant="default"
                  :disabled="isResuming"
                  @click="handleResume"
                >
                  {{ isResuming ? "续传中..." : "继续任务" }}
                </Button>
                <Button
                  v-if="taskStore.isRunning && !isWaitingModelingReview"
                  variant="destructive"
                  :disabled="isStopping"
                  @click="handleStop"
                >
                  {{ isStopping ? "停止中..." : "停止运行" }}
                </Button>
                <Button @click="taskStore.downloadMessages" class="flex justify-end">
                  下载消息
                </Button>

                <FilesSheet />

              </div>

            </div>

            <TabsContent value="modeler" class="flex-1 p-1 min-w-0 h-full overflow-hidden">
              <ModelerEditor />
            </TabsContent>

            <TabsContent value="coder" class="flex-1 p-1 min-w-0 h-full overflow-hidden">
              <CoderEditor />
            </TabsContent>

            <TabsContent value="writer" class="flex-1 p-1 min-w-0 h-full overflow-hidden">
              <WriterEditor :messages="taskStore.writerMessages" :writerSequence="writerSequence" />
            </TabsContent>
          </Tabs>
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>

  </div>
</template>

<style scoped></style>
