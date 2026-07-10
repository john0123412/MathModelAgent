/** 将请求错误压缩为不包含请求体、headers 或密钥的日志文本。 */
export function getSafeErrorMessage(error: unknown): string {
	if (error && typeof error === "object" && "response" in error) {
		const response = (error as { response?: { status?: number } }).response;
		return `status=${response?.status ?? "unknown"}`;
	}
	if (error && typeof error === "object" && "request" in error) {
		return "request failed";
	}
	return error instanceof Error ? error.message : "unknown error";
}
