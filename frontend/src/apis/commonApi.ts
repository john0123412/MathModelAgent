import request from "@/utils/request";

export function getHelloWorld() {
	return request.get<{ message: string }>("/");
}

// 获取论文顺序
export function getWriterSeque() {
	return request.get<{ writer_seque: string[] }>("/writer_seque");
}
