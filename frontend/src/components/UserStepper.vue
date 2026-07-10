<script setup lang="ts">
import { saveApiConfig } from "@/apis/apiKeyApi";
import { submitModelingTask } from "@/apis/submitModelingApi";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectLabel,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { useApiKeyStore } from "@/stores/apiKeys";
import { useTaskStore } from "@/stores/task";
import { getSafeErrorMessage } from "@/utils/safeError";
import { FileUp } from "lucide-vue-next";
import { Rocket } from "lucide-vue-next";
import { ref } from "vue";
import { useRouter } from "vue-router";
import type FileConfirmDialog from "./FileConfirmDialog.vue";

// ---- Reactive State ----

const taskStore = useTaskStore();
const { toast } = useToast();
const apiKeyStore = useApiKeyStore();
const currentStep = ref(1);
const fileConfirmDialog = ref<InstanceType<typeof FileConfirmDialog> | null>(
	null,
);
const fileUploaded = ref(true);

/** 已上传的文件列表 */
const uploadedFiles = ref<File[]>([]);

/** 题目内容 */
const question = ref("");

type SelectedOptionKey = "template" | "language" | "format" | "exportProfile";
type SelectedOptions = Record<SelectedOptionKey, string>;

/** 选项配置 */
const selectedOptions = ref<SelectedOptions>({
	template: "CHINA",
	language: "中文",
	format: "Markdown",
	exportProfile: "cumcm2026",
});

/** 选择器配置列表 */
const selectConfig: Array<{
	key: SelectedOptionKey;
	group: string;
	label: string;
	options: Array<{ label: string; value: string }>;
}> = [
	{
		key: "template",
		group: "赛事",
		label: "选择赛事",
		options: [
			{ label: "高教社杯/国赛", value: "CHINA" },
			{ label: "美赛", value: "AMERICAN" },
		],
	},
	{
		key: "language",
		group: "语言",
		label: "选择语言",
		options: [
			{ label: "中文", value: "中文" },
			{ label: "英文", value: "英文" },
		],
	},
	{
		key: "format",
		group: "格式",
		label: "选择格式",
		options: [
			{ label: "Markdown", value: "Markdown" },
			{ label: "LaTeX", value: "LaTeX" },
		],
	},
	{
		key: "exportProfile",
		group: "排版",
		label: "选择排版",
		options: [
			{ label: "高教社杯 2026", value: "cumcm2026" },
			{ label: "高教社杯 2025", value: "cumcm2025" },
			{ label: "默认", value: "default" },
		],
	},
];

/** 上传成功提示显示状态 */
const showUploadSuccess = ref(false);

/** 提交成功提示显示状态 */
const showSubmitSuccess = ref(false);

/** 任务ID */
const taskId = ref<string | null>(null);

/** 文件输入元素引用 */
const fileInput = ref<HTMLInputElement | null>(null);

// ---- Methods ----

const nextStep = () => {
	if (currentStep.value < 2) currentStep.value++;
};

const prevStep = () => {
	if (currentStep.value > 1) currentStep.value--;
};

/** 处理文件上传事件 */
const handleFileUpload = (event: Event) => {
	const input = event.target as HTMLInputElement;
	if (input.files && input.files.length > 0) {
		uploadedFiles.value = Array.from(input.files);
		fileUploaded.value = true;
		showUploadSuccess.value = true; // 显示提示
		setTimeout(() => {
			showUploadSuccess.value = false; // 3秒后自动隐藏
		}, 1000);
	}
};

const router = useRouter();

/** 提交建模任务 */
const handleSubmit = async () => {
	try {
		// 应用 API Key 到当前后端进程。若字段为空，后端会保留 .env.dev
		// 中已加载的默认配置，不会被空值覆盖；接口不会写回 .env.dev。
		await saveApiConfig({
			coordinator: apiKeyStore.coordinatorConfig,
			modeler: apiKeyStore.modelerConfig,
			coder: apiKeyStore.coderConfig,
			writer: apiKeyStore.writerConfig,
			openalex_email: apiKeyStore.openalexEmail,
		});

		if (uploadedFiles.value.length === 0) {
			if (!fileConfirmDialog.value) return;

			const shouldContinue = await fileConfirmDialog.value.openConfirmDialog();

			if (!shouldContinue) {
				toast({
					title: "请先上传文件",
					description: "请先上传文件",
					variant: "destructive",
				});
				return;
			}
		}
		console.log(selectedOptions.value);
		console.log(question.value);
		console.log(uploadedFiles.value);
		const response = await submitModelingTask(
			{
				ques_all: question.value,
				comp_template: selectedOptions.value.template,
				format_output: selectedOptions.value.format,
				export_profile: selectedOptions.value.exportProfile,
			},
			uploadedFiles.value,
		);

		taskId.value = response?.data?.task_id ?? null;
		taskStore.addUserMessage(question.value);

		showSubmitSuccess.value = true;
		setTimeout(() => {
			showSubmitSuccess.value = false; // 3秒后自动隐藏
		}, 3000);
		router.push(`/task/${taskId.value}`);
		toast({
			title: "任务提交成功",
			description: `任务提交成功，编号为：${taskId.value}`,
		});
	} catch (error) {
		console.error("任务提交失败:", getSafeErrorMessage(error));
		toast({
			title: "任务提交失败",
			description: "请检查 API Key 是否正确",
			variant: "destructive",
		});
	}
};
</script>

<template>
  <div class="w-full max-w-xl mx-auto relative">
    <!-- 使用 Alert 组件 -->
    <Transition name="fade">
      <div v-if="showUploadSuccess" class="fixed top-4 right-4 z-50">
        <Alert>
          <Rocket class="h-4 w-4" />
          <AlertTitle>文件上传成功！</AlertTitle>
          <AlertDescription>
            已成功上传 {{ uploadedFiles.length }} 个文件，请继续下一步操作。
          </AlertDescription>
        </Alert>
      </div>
    </Transition>

    <Transition name="fade">
      <div v-if="showSubmitSuccess" class="fixed top-4 right-4 z-50">
        <Alert>
          <Rocket class="h-4 w-4" />
          <AlertTitle>任务提交成功！</AlertTitle>
          <AlertDescription>
            任务提交成功，编号为：{{ taskId }}。
          </AlertDescription>
        </Alert>
      </div>
    </Transition>

    <div class="border rounded-lg shadow-sm">
      <!-- Step 1: File Upload -->
      <div v-if="currentStep === 1" class="p-6">
        <div
          class="border-2 border-dashed rounded-lg p-8 text-center hover:border-primary/50 transition-colors cursor-pointer"
          @click="() => fileInput?.click()">
          <input type="file" ref="fileInput" class="hidden" @change="handleFileUpload" multiple>
          <div class="mx-auto w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
            <FileUp class="w-6 h-6 text-primary" />
          </div>
          <div>
            <p class="text-lg font-medium">拖拽数据集到此处或点击上传</p>
            <p class="text-sm text-muted-foreground mt-1">
              支持题面、数据、图片和压缩包等附件（可多选）
            </p>
            <div v-if="uploadedFiles.length > 0" class="text-sm text-green-600 mt-1">
              已上传文件:
              <ul>
                <li v-for="(file, index) in uploadedFiles" :key="index">
                  {{ file.name }}
                </li>
              </ul>
            </div>
          </div>
        </div>
        <div class="mt-4 flex justify-end">
          <Button :disabled="!fileUploaded" @click="nextStep" size="sm">
            下一步
          </Button>
        </div>
      </div>

      <!-- Step 2: Question Input -->
      <div v-if="currentStep === 2" class="p-6">
        <div class="space-y-4">
          <div class="space-y-1">
            <h4 class="text-sm font-medium mb-2">粘贴完整题目</h4>
            <Textarea v-model="question" placeholder="PDF 中完整题目背景和多个小问" class="min-h-[120px]" />
          </div>

          <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div v-for="item in selectConfig" :key="item.key">
              <Select v-model="selectedOptions[item.key]" :defaultValue="item.options[0].value">
                <SelectTrigger class="h-9">
                  <SelectValue :placeholder="item.label" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>{{ item.group }}</SelectLabel>
                    <SelectItem v-for="option in item.options" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <div class="mt-4 flex justify-between">
          <Button variant="outline" @click="prevStep" size="sm">
            上一步
          </Button>
          <Button @click="handleSubmit" size="sm">
            开始分析
          </Button>
        </div>
      </div>
    </div>
  </div>
  <FileConfirmDialog ref="fileConfirmDialog" />
</template>
