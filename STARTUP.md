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

> 注意：`backend/Dockerfile` 内的容器端口仍为 8000（Docker 构建镜像时使用），
> 与本地开发（win_start.bat / uvicorn 手动启动）使用的 8003 不是同一个口径。
> 本地开发请以 8003 为准；如果通过 Dockerfile 构建镜像运行，请自行确认端口映射。

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
