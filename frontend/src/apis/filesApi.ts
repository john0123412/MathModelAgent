import request from "@/utils/request";

export function getFiles(task_id: string) {
  return request.get<{ message: string }>("/files", {
    params: { task_id },
  });
}
