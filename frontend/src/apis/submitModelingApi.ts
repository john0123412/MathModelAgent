import request from "@/utils/request";

/**
 * 提交数学建模任务
 * @param problem 问题描述
 * @param files 上传的数据文件
 */
export function submitModelingTask(
	problem: {
		ques_all: string;
		comp_template?: string;
		format_output?: string;
		export_profile?: string;
	},
	files?: File[],
) {
	const formData = new FormData();
	// 添加问题数据
	formData.append("ques_all", problem.ques_all);
	formData.append("comp_template", problem.comp_template || "CHINA");
	formData.append("format_output", problem.format_output || "Markdown");
	formData.append("export_profile", problem.export_profile || "cumcm2026");

	if (files?.length) {
		for (const file of files) {
			formData.append("files", file);
		}
	}

	return request.post<{
		task_id: string;
		status: string;
	}>("/modeling", formData, {
		headers: {
			"Content-Type": "multipart/form-data",
		},
		timeout: 30000,
	});
}
