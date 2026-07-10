import axios from "axios";
import { getSafeErrorMessage } from "@/utils/safeError";

/** 创建 axios 实例 */
const service = axios.create({
	baseURL: import.meta.env.VITE_API_BASE_URL,
	timeout: 10000,
});

/** 请求拦截器 */
service.interceptors.request.use(
	(config) => {
		return config;
	},
	(error) => {
		console.warn("请求配置失败:", getSafeErrorMessage(error));
		return Promise.reject(error);
	},
);

/** 响应拦截器 */
service.interceptors.response.use(
	(response) => {
		return response;
	},
	(error) => {
		return Promise.reject(error);
	},
);

export default service;
