FROM node:24-alpine

WORKDIR /app

# 复制依赖文件
COPY package.json pnpm-lock.yaml ./

# 安装 pnpm：钉住与 package.json packageManager 一致的版本。
# 浮动 latest 会因新版 pnpm 的自托管二进制校验在 --frozen-lockfile 下失败
RUN npm install -g pnpm@10.6.3

# 清理 npm 缓存并安装依赖
RUN pnpm install --frozen-lockfile

# 复制源代码
COPY . .

EXPOSE 5173

# 运行开发服务器
CMD ["pnpm", "run", "dev", "--host"]
