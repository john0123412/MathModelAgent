import request from "@/utils/request";
import type { Message } from "@/utils/response";

/** 健康检查 */
export function getHelloWorld() {
	return request.get<{ message: string }>("/");
}

/** 获取论文写作顺序 */
export function getWriterSeque() {
	return request.get<{ writer_seque: string[] }>("/writer_seque");
}

/**
 * 获取任务的历史消息
 * @param task_id 任务ID
 */
export function getTaskMessages(task_id: string) {
	return request.get<Message[]>("/messages", {
		params: {
			task_id,
		},
	});
}

/**
 * 提交样例任务
 * @param example_id 样例ID
 * @param source 来源
 */
export function exampleAPI(example_id: string, source: string) {
	return request.post<{
		task_id: string;
		status: string;
	}>("/example", {
		example_id,
		source,
	});
}

/** 获取后端和 Redis 服务状态 */
export function getServiceStatus() {
	return request.get<{
		backend: { status: string; message: string };
		redis: { status: string; message: string };
	}>("/status");
}

/**
 * 取消正在运行的任务
 * @param task_id 任务ID
 */
export function cancelTask(task_id: string) {
	return request.post<{ success: boolean; message: string }>(
		`/modeling/${task_id}/cancel`,
	);
}

/**
 * 从检查点续传一个中断的任务
 * @param task_id 任务ID
 */
export function resumeTask(task_id: string) {
	return request.post<{ task_id: string; status: string }>(
		`/modeling/${task_id}/resume`,
	);
}

/**
 * 确认建模方案并从检查点继续任务
 * @param task_id 任务ID
 * @param comment 审批备注
 */
export function approveModeling(task_id: string, comment = "") {
	return request.post<{ task_id: string; status: string }>(
		`/modeling/${task_id}/approve-modeling`,
		{ comment },
	);
}

/** 任务信息 */
export interface TaskInfo {
	task_id: string;
	title: string;
	status:
		| "completed"
		| "pending"
		| "running"
		| "interrupted"
		| "waiting_review"
		| "resuming"
		| "failed"
		| "cancelled"
		| "unknown";
	created_at: string;
	has_result: boolean;
	has_pdf: boolean;
	has_manifest: boolean;
	has_checkpoint: boolean;
	files: {
		res_md: boolean;
		res_json: boolean;
		res_docx: boolean;
		res_pdf: boolean;
		candidate_manifest: boolean;
		checkpoint: boolean;
	};
}

/** 获取所有历史任务列表 */
export function listTasks() {
	return request.get<TaskInfo[]>("/tasks");
}
