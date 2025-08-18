import request from "@/utils/request";

// 验证 API Key 请求参数
export interface ValidateApiKeyRequest {
  api_key: string;
  base_url?: string;
  model_id: string;
}

// 验证 API Key 响应
export interface ValidateApiKeyResponse {
  valid: boolean;
  message: string;
}

// 保存 API 配置请求参数
export interface SaveApiConfigRequest {
  coordinator: {
    apiKey: string;
    baseUrl: string;
    modelId: string;
  };
  modeler: {
    apiKey: string;
    baseUrl: string;
    modelId: string;
  };
  coder: {
    apiKey: string;
    baseUrl: string;
    modelId: string;
  };
  writer: {
    apiKey: string;
    baseUrl: string;
    modelId: string;
  };
}

// 验证 API Key
export function validateApiKey(params: ValidateApiKeyRequest) {
  return request.post<ValidateApiKeyResponse>("/validate-api-key", params);
}

// 保存 API 配置
export function saveApiConfig(params: SaveApiConfigRequest) {
  return request.post<{ success: boolean; message: string }>("/save-api-config", params);
}