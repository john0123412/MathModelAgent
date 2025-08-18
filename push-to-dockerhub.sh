#!/bin/bash
# push-to-dockerhub.sh

set -e

USERNAME="sanjin66"
BACKEND_TAG="${USERNAME}/mathmodelagent-backend-github:latest"
FRONTEND_TAG="${USERNAME}/mathmodelagent-frontend-github:latest"

echo "开始构建和推送 MathModelAgent..."

# 构建并推送后端
echo "构建后端镜像..."
docker build -t ${BACKEND_TAG} ./backend
echo "推送后端镜像..."
docker push ${BACKEND_TAG}

# 构建并推送前端
echo "构建前端镜像..."
docker build -t ${FRONTEND_TAG} ./frontend
echo "推送前端镜像..."
docker push ${FRONTEND_TAG}

echo "推送完成！"