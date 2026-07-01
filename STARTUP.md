# MathModelAgent 启动说明

## 环境要求
- Docker Desktop（数据存储在 `D:\AppData\DockerData\`）
- Python 3.12 + uv
- Node.js + pnpm
- Redis（Docker 容器或本地安装均可）

---

## 方案一：Docker Compose（推荐）

### 启动

```bash
cd D:\workspace\MathModelAgent
docker-compose up --build   # 首次启动 或 改了依赖/Dockerfile 后
docker-compose up           # 之后正常启动（有缓存，秒级）
docker-compose up -d        # 后台运行（-d = detach）
```

### 停止

```bash
docker-compose down         # 停止并移除容器
docker-compose stop         # 仅停止（保留容器，启动更快）
docker-compose down -v      # 停止并删除数据卷（⚠️ 清空 Redis 数据）
```

启动后访问 http://localhost:5173

### 前置条件
- `backend/.env.dev` 已存在并配置好 API Key（`docker-compose.yml` 通过 `env_file` 加载，不提交到 git）
- Docker Desktop 正在运行

### 首次构建说明
首次 `docker-compose up --build` 会下载基础镜像并安装所有依赖（约 14 分钟），之后有缓存秒级启动。只有修改了以下文件才需要重新加 `--build`：
- `backend/Dockerfile` 或 `backend/pyproject.toml` → 重建后端镜像
- `frontend/Dockerfile` 或 `frontend/package.json` → 重建前端镜像

### 架构
Docker Compose 启动 3 个容器：
- **backend**（:8000）→ 通过内部网络连接 redis 服务
- **frontend**（:5173）→ 读取 `frontend/.env.docker`，请求指向 :8000
- **redis**（内部，不暴露端口）→ 独立的 compose Redis，不与宿主机 redis-mma 冲突

---

## 方案二：本地开发

### 启动（一键）

双击运行：
```
D:\workspace\MathModelAgent\win_start.bat
```
脚本会自动: 启动 Docker → 启动 Redis → 启动后端(8003) → 启动前端(5173) → 打开浏览器

### 启动（手动）

**1. 启动 Redis**
```
docker start redis-mma
```
验证:
```
docker exec redis-mma redis-cli ping
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

### 停止

```bash
# 关闭后端和前端：关闭对应的 cmd 窗口（Ctrl+C）

# 或者通过命令行查找并杀掉进程：
netstat -ano | findstr ":8003"     # 找到后端 PID
netstat -ano | findstr ":5173"     # 找到前端 PID
taskkill /PID <PID> /F             # 杀掉进程
# 注意：Windows 下 Git Bash 中 / 会被转换为路径，需要用 Python 执行：
python -c "import subprocess; subprocess.run(['taskkill', '/PID', '<PID>', '/F'])"

# Redis 如果不再需要：
docker stop redis-mma
# Redis 下次需要时重新启动：
docker start redis-mma
```

---

## 完全停止所有服务

```bash
# 停止 docker-compose 栈
cd D:\workspace\MathModelAgent
docker-compose down

# 杀掉本地开发的后端和前端进程
python -c "
import subprocess
r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
for line in r.stdout.split('\n'):
    for port in [':8003', ':5173']:
        if port in line and 'LISTENING' in line:
            pid = line.split()[-1]
            subprocess.run(['taskkill', '/PID', pid, '/F'])
            print(f'Killed PID {pid} on {port}')
"

# 停止 Redis（如需要）
docker stop redis-mma
```

---

## 端口说明

| 服务 | 方案一（docker-compose） | 方案二（本地开发） |
|------|------------------------|-------------------|
| Frontend | 5173 | 5173 |
| Backend | 8000 | 8003 |
| Redis | 内部网络（不暴露） | 6379（宿主机 redis-mma） |

> **两种方式不能同时运行**，因为前端都映射到 5173。用哪个就停另一个。

---

## 环境变量隔离

| 文件 | 用途 | 端口 |
|------|------|------|
| `frontend/.env.development` | 本地开发（win_start.bat） | 指向 8003 |
| `frontend/.env.docker` | Docker Compose | 指向 8000 |
| `backend/.env.dev` | 两种方式共用，docker-compose 通过 environment 覆盖 REDIS_URL 和 SERVER_HOST | — |

---

## Docker 数据存储

Docker Desktop 配置了自定义 WSL 路径，数据存储在 D 盘：
```
D:\AppData\DockerData\wsl\DockerDesktopWSL\disk\docker_data.vhdx
```
不占用 C 盘空间。

---

## 常见问题

### OPENALEX_EMAIL 未配置
编辑 backend/.env.dev 添加:
```
OPENALEX_EMAIL=你的邮箱
```
重启后端生效。

### Redis 连接失败
```bash
# 本地开发
docker start redis-mma
docker exec redis-mma redis-cli ping

# Docker Compose
docker-compose logs redis
```

### 端口被占用（5173 或 8000/8003）
```bash
# 查找占用端口的进程
netstat -ano | findstr ":5173"
netstat -ano | findstr ":8003"

# 杀掉进程（注意 Windows 下需要用 Python 执行 taskkill）
python -c "
import subprocess
r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
for line in r.stdout.split('\n'):
    for port in [':8003', ':5173', ':8000']:
        if port in line and 'LISTENING' in line:
            pid = line.split()[-1]
            subprocess.run(['taskkill', '/PID', pid, '/F'])
            print(f'Killed PID {pid}')
"
```

### Docker Compose 启动报 port already allocated
compose 的 Redis 已配置为不暴露端口，不应出现此问题。如仍报错：
```bash
netstat -ano | findstr ":6379"
```
