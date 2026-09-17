#!/usr/bin/env python3
import subprocess
import requests
import json
import sys
import time

def run_cmd(cmd, capture=True):
    """兼容Python 3.6的命令执行函数"""
    if capture:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    else:
        return subprocess.run(cmd)

def auto_register():
    print("=" * 60)
    print("🚀 自动构建注册脚本")
    print("=" * 60)
    
    # 1. 构建镜像
    print("\n1. 🔨 构建镜像...")
    run_cmd([
        "docker", "build", "-t", "csv-training-service:latest", 
        "-f", "docker/Dockerfile", "."
    ], capture=False)
    
    # 2. 获取哈希
    print("\n2. 🔍 获取镜像哈希...")
    result = run_cmd(
        ["docker", "images", "--no-trunc", "-q", "csv-training-service:latest"]
    )
    image_hash = result.stdout.strip().replace('sha256:', '')
    full_hash = f"sha256:{image_hash}"
    print(f"   ✅ 哈希: {full_hash}")
    
    # 3. 注册到证明服务
    print("\n3. 📝 注册到证明服务...")
    try:
        response = requests.post(
            "http://localhost:8081/api/v1/trusted-images",
            json={"image_hash": full_hash},
            timeout=10
        )
        result = response.json()
        if result['code'] == 0:
            print(f"   ✅ 注册成功: {result['message']}")
            print(f"   📊 当前可信镜像数: {result.get('total', '未知')}")
        else:
            print(f"   ❌ 注册失败: {result.get('message', '未知错误')}")
            return False
    except Exception as e:
        print(f"   ❌ 注册异常: {e}")
        return False
    
    # 4. 更新 docker-compose.yml
    print("\n4. ⚙️ 更新配置...")
    run_cmd([
        "sed", "-i", 
        f"s/CONTAINER_IMAGE_HASH=.*/CONTAINER_IMAGE_HASH={full_hash}/g", 
        "docker-compose.yml"
    ], capture=False)
    print("   ✅ 配置更新完成")
    
    # 5. 重启服务
    print("\n5. 🔄 重启服务...")
    run_cmd(["docker", "compose", "down"], capture=False)
    run_cmd(["docker", "compose", "up", "-d"], capture=False)
    print("   ⏳ 等待服务启动...")
    time.sleep(30)
    
    # 6. 验证注册
    print("\n6. ✅ 验证注册...")
    try:
        response = requests.get("http://localhost:8081/api/v1/trusted-images", timeout=5)
        trusted = response.json()['data']['trusted_hashes']
        print(f"   📋 当前白名单:")
        for h in trusted:
            print(f"     - {h[:20]}...")
        if full_hash in trusted:
            print("   ✅ 验证通过")
        else:
            print("   ❌ 验证失败，哈希不在白名单")
            return False
    except Exception as e:
        print(f"   ❌ 验证异常: {e}")
        return False
    
    # 7. 运行测试
    print("\n7. 🧪 运行测试...")
    try:
        result = run_cmd(["python3", "scripts/integrated_client.py"])
        if "✅ 机密计算训练工作流完成" in result.stdout:
            print("   ✅ 测试成功！")
        else:
            print("   ⚠️ 测试可能失败，查看详细日志：")
            print(result.stdout[-500:])
    except Exception as e:
        print(f"   ⚠️ 测试异常: {e}")
    
    print("\n" + "=" * 60)
    print("🎉 自动构建注册流程完成！")
    print("=" * 60)
    return True

if __name__ == "__main__":
    auto_register()
