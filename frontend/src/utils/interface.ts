import type { CodeExecutionResult } from './response'

// 代码单元格类型
export interface CodeCell {
  type: 'code'
  content: string
}

// 结果单元格类型
export interface ResultCell {
  type: 'result'
  code_results: CodeExecutionResult[]
}

// 笔记本单元格类型（代码或结果）
export type NoteCell = CodeCell | ResultCell