// 对应 response.py 的结构
export type SystemMessageType = 'info' | 'warning' | 'success' | 'error';
export type AgentType = 'CoderAgent' | 'WriterAgent';

export interface BaseMessage {
  id: string;
  msg_type: 'system' | 'agent' | 'user';
  content?: string | null;
}

export interface SystemMessage extends BaseMessage {
  msg_type: 'system';
  type: SystemMessageType;
}

export interface UserMessage extends BaseMessage {
  msg_type: 'user';
}

export interface AgentMessage extends BaseMessage {
  msg_type: 'agent';
  agent_type: AgentType;
}

// 代码执行结果类型
export type ExecutionFormat = 
  | 'text'
  | 'html'
  | 'markdown'
  | 'png'
  | 'jpeg'
  | 'svg'
  | 'pdf'
  | 'latex'
  | 'json'
  | 'javascript';

export interface BaseCodeExecution {
  res_type: 'stdout' | 'stderr' | 'result' | 'error';
  msg?: string;
}

export interface StdOutExecution extends BaseCodeExecution {
  res_type: 'stdout';
}

export interface StdErrExecution extends BaseCodeExecution {
  res_type: 'stderr';
}

export interface ResultExecution extends BaseCodeExecution {
  res_type: 'result';
  format: ExecutionFormat;
}

export interface ErrorExecution extends BaseCodeExecution {
  res_type: 'error';
  name: string;
  value: string;
  traceback: string;
}

export type CodeExecutionResult = StdOutExecution | StdErrExecution | ResultExecution | ErrorExecution;

export interface CoderMessage extends AgentMessage {
  agent_type: 'CoderAgent';
  code?: string;
  code_results?: CodeExecutionResult[];
  files?: string[];
}

export interface WriterMessage extends AgentMessage {
  agent_type: 'WriterAgent';
  sub_title?: string;
}

export type Message = SystemMessage | UserMessage | CoderMessage | WriterMessage;