# MathModelAgent 启动说明

## 环境要求
- Docker Desktop
- Python 3.12 + uv
- Node.js + pnpm

---

## 方案一：Docker Compose（推荐）

### 启动

```powershell
cd D:\workspace\MathModelAgent
docker-compose up --build   # 首次启动 或 改了依赖/Dockerfile 后
docker-compose up           # 之后正常启动（有缓存）
docker-compose up -d        # 后台运行
```

### 停止

```powershell
docker-compose down         # 停止并移除容器
docker-compose stop         # 仅停止（保留容器）
docker-compose down -v      # 停止并删除数据卷（⚠️ 清空 Redis 数据）
```

启动后访问 http://localhost:5173

### 前置条件
- `backend/.env.dev` 已配置好 API Key
- Docker Desktop 正在运行

### 架构
- **backend**（:8000）→ 支持 checkpoint/resume
- **frontend**（:5173）→ 连接 :8000
- **redis**（内部网络）

### Restart 策略
所有容器配置了 `restart: unless-stopped`：
- Docker Desktop 重启 → 容器自动恢复
- 系统重启 → 容器自动恢复
- 手动 `docker stop` → 不会自动恢复

---

## 方案二：本地开发

### 一键启动
```
D:\workspace\MathModelAgent\win_start.bat
```

### 手动启动

**1. 启动 Redis**
```
docker start redis-mma
```

**2. 启动后端（新终端）**
```
cd D:\workspace\MathModelAgent\backend
.venv\Scripts\activate
set ENV=dev
set REDIS_URL=redis://127.0.0.1:6379/0
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

**3. 启动前端（另一个新终端）**
```
cd D:\workspace\MathModelAgent\frontend
pnpm run dev
```

**4. 打开浏览器** 访问 http://localhost:5173

---

## 端口说明

| 服务 | Docker Compose | 本地开发 |
|------|----------------|----------|
| Frontend | 5173 | 5173 |
| Backend | 8000 | 8003 |
| Redis | 内部网络 | 6379 |

---

## 功能说明

### 断点续传（Checkpoint/Resume）

**原理**：
1. 任务在每个阶段（eda/ques1/ques2...）完成后自动保存检查点到 `checkpoint.json`
2. 中断后重启，通过 `GET /tasks` 检测到 `status: "interrupted"`
3. 点击"继续任务"，调用 `POST /modeling/{task_id}/resume`
4. 系统从检查点恢复，跳过已完成阶段，通过重放 notebook 单元格重建内核变量状态

**重建计算环境机制**：
- 读取 `notebook.ipynb` 中所有代码单元格
- 跳过包含 error 输出的单元格（失败/反思重试留下的痕迹）
- 按顺序重新执行成功的单元格
- 每 10 个单元格发送进度消息
- 重建完成后继续执行未完成阶段

### 实时消息干预

**原理**：
1. WebSocket 双向通信：前端发送 → 后端接收 → 推入队列
2. Agent 在每次 LLM 调用前检查队列
3. 用户消息作为额外上下文注入到 `chat_history`
4. 前端实时回显用户输入

---

## 功能测试

### 测试 A：断点续传

1. 打开 http://localhost:5173
2. 提交一个任务（选择"使用该案例"）
3. 等待任务运行（观察聊天区出现代码执行日志）
4. 模拟崩溃：停止后端
   ```powershell
   docker-compose stop backend
   ```
5. 重启后端
   ```powershell
   docker-compose up -d
   ```
6. 刷新浏览器，任务应显示 `interrupted` 状态
7. 点击"继续任务"按钮
8. 观察进度消息和最终产物

### 测试 B：实时消息干预

1. 提交一个任务
2. 等待 CoderAgent 开始运行（聊天区出现代码执行日志）
3. 在输入框发送干预消息：
   ```
   请在代码中添加更详细的注释，并输出中间变量的值
   ```
4. 观察：
   - 前端回显消息
   - 后端日志显示收到用户输入
   - Agent 行为是否有变化

---

## 常见问题

### OPENALEX_EMAIL 未配置
编辑 backend/.env.dev 添加:
```
OPENALEX_EMAIL=你的邮箱
```
重启后端生效。

### Redis 连接失败
```powershell
# 本地开发
docker start redis-mma

# Docker Compose
docker-compose logs redis
```

### 端口被占用
```powershell
netstat -ano | findstr ":8000"
netstat -ano | findstr ":5173"
taskkill /PID <PID> /F
```

### 任务状态不显示 "interrupted"
检查 checkpoint.json 是否存在：
```powershell
ls D:\workspace\MathModelAgent\backend\project\work_dir\<task_id>\checkpoint.json
```
