# MathModelAgent 启动说明

## 环境要求
- Docker Desktop
- Python 3.12 + uv
- Node.js + pnpm

## 一键启动（推荐）

双击运行:
```
D:\workspace\MathModelAgent\win_start.bat
```
脚本会自动: 启动Docker → 启动Redis → 启动后端(8003) → 启动前端(5173) → 打开浏览器

## 手动启动

### 1. 启动 Docker Desktop
双击桌面图标，等右下角变绿。

### 2. 启动 Redis
```
docker start redis-mma
```
验证:
```
docker exec redis-mma redis-cli ping
```

### 3. 启动后端 (新终端)
```
cd D:\workspace\MathModelAgent\backend
.venv\Scripts\activate
set ENV=dev
set REDIS_URL=redis://127.0.0.1:6379/0
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

### 4. 启动前端 (另一个新终端)
```
cd D:\workspace\MathModelAgent\frontend
pnpm run dev
```

### 5. 打开浏览器
访问 http://localhost:5173

## 端口说明

| 服务 | 端口 |
|------|------|
| Frontend | 5173 |
| Backend | 8003 |
| Redis | 6379 |

> **重要**：Docker 内部服务端口是 8000（见 `backend/Dockerfile` / `docker-compose.yml`），
> 本地开发 `win_start.bat` 使用 8003，两者不是同一个运行模式，不要混用。
>
> - 本地开发（双击 `win_start.bat` 或手动 `uvicorn ... --port 8003`）：后端在 8003。
> - 通过 `docker-compose up` 启动完整栈：`docker-compose.yml` 将容器内 8000 端口映射到宿主机 8000
>   （`"8000:8000"`），此时后端实际监听在宿主机 8000，而不是 8003。
> - 已知风险：`frontend/.env.development` 中的 `VITE_API_BASE_URL`/`VITE_WS_URL` 当前固定指向
>   `localhost:8003`，该文件同时被本地开发和 `docker-compose.yml`（`env_file`）复用。若通过
>   `docker-compose up` 启动完整栈（前端也在容器内运行），前端会尝试连接 `localhost:8003`，
>   但 docker-compose 只把后端映射到宿主机 8000，二者端口不一致，会导致 Docker 全栈模式下
>   前端请求后端失败。这是历史遗留的环境变量复用问题，本次未处理（不在本次收尾范围内），
>   如果需要使用 `docker-compose up` 的完整 WebUI 模式，需要单独为 Docker 场景准备一份
>   指向 8000 的前端环境变量文件后再排查。

## 常见问题

### OPENALEX_EMAIL 未配置
编辑 backend/.env.dev 添加:
```
OPENALEX_EMAIL=你的邮箱
```
重启后端生效。

### Redis 连接失败
```
docker start redis-mma
docker exec redis-mma redis-cli ping
```

### 端口被占用
```
netstat -ano | findstr ":8003"
taskkill /PID <PID> /F
```

## 停止服务
- 双击启动的: 关闭对应的 cmd 窗口
- Redis: docker stop redis-mma
