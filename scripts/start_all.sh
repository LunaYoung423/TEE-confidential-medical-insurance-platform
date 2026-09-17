#!/bin/bash

echo "启动机密计算平台..."

# 构建Docker镜像
echo "1. 构建Docker镜像..."
docker compose build

# 启动服务
echo "2. 启动所有服务..."
docker compose up -d

# 等待服务启动
echo "3. 等待服务启动..."
sleep 10

# 检查服务状态
echo "4. 检查服务状态..."
docker compose ps

echo "5. 服务启动完成！"
echo "访问地址："
echo "  环境控制器: http://localhost:8080"
echo "  证明服务: http://localhost:8081"
echo "  训练服务: 在容器内部运行，端口8000"
echo "提示: compose 服务名是 controller（容器名 cc-controller），重启请执行: docker compose restart controller"