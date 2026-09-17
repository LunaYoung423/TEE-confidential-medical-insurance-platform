#!/bin/bash
set -e

echo "🔧 设置配置文件..."

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd $PROJECT_DIR

# 1. 构建机密容器镜像（如果未构建）
echo "🚀 构建训练服务镜像 csv-training-service:latest ..."
docker build -t csv-training-service:latest -f docker/Dockerfile .

# 2. 获取镜像哈希
IMAGE_HASH=$(docker images --no-trunc -q csv-training-service:latest | sed 's/sha256://')
if [ -z "$IMAGE_HASH" ]; then
    echo "❌ 无法获取镜像哈希，请确保镜像 csv-training-service:latest 已构建"
    exit 1
fi
echo "✅ 镜像哈希: $IMAGE_HASH"

# 3. 创建可信镜像配置文件，写入真实哈希
mkdir -p config
cat > config/trusted_images.json << EOF
{
  "trusted_hashes": [
    "$IMAGE_HASH"
  ],
  "notes": "自动生成的镜像哈希，请勿手动修改"
}
EOF
echo "✅ config/trusted_images.json 已更新"

# 4. 更新 attestation_agent.py 中的 CSV 工具路径（保持原有逻辑）
if [ -f "module1/attestation_agent.py" ]; then
    echo "更新 attestation_agent.py 配置..."
    # 确保使用容器内路径 /app/csv-attestation.py
    sed -i "s|self.csv_tool = '.*'|self.csv_tool = '/app/csv-attestation.py'|g" module1/attestation_agent.py
    echo "✅ attestation_agent.py 更新完成"
fi

# 5. 创建环境变量文件
cat > .env << EOF
# 机密计算平台环境变量
ATTESTATION_SERVER=http://attestation-service:8081
CONTROLLER_URL=http://controller:8080
DATA_PATH=/app/data
TRAINING_SERVICE_PORT=8000
ATTESTATION_AGENT_PORT=8006
LOG_LEVEL=INFO
EOF

echo "✅ 配置文件设置完成"
echo "现在可以使用 docker-compose up -d 启动服务了。"