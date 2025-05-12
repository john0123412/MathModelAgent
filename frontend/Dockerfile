# 构建阶段
FROM node:20 AS build

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm
RUN pnpm install
COPY . .

# 应用将运行的端口 (Vite 开发环境通常是 5173)
EXPOSE 5173

# 运行开发服务器的命令
# --host 确保可以从容器外部访问
CMD ["pnpm", "run", "dev", "--host"]