import requests
import time
import pickle
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score
import os

# ==================== 配置项 ====================
BASE_URL = "http://127.0.0.1:8000"                # 你的服务地址
TRAIN_DATA_PATH = "/root/confidential-computing-platform/data/train_data.csv"   # 训练集路径（用于提交任务）
TEST_DATA_PATH = "/root/confidential-computing-platform/data/test_data.csv"     # 测试集路径（用于评估）
ALGORITHM = "xgboost"                             # 可选：xgboost 或 linear_regression
TRAIN_PARAMS = {
    "n_estimators": 50,
    "max_depth": 3,
    "random_state": 42
}  # XGBoost 参数；若用线性回归可改为 {"fit_intercept": True}
# ====================================================================

def check_files():
    """检查训练集和测试集是否存在"""
    if not os.path.exists(TRAIN_DATA_PATH):
        print(f"❌ 训练集文件不存在：{TRAIN_DATA_PATH}")
        return False
    if not os.path.exists(TEST_DATA_PATH):
        print(f"❌ 测试集文件不存在：{TEST_DATA_PATH}")
        return False
    print("✅ 数据文件存在")
    return True

def create_task():
    """创建训练任务（适配你的 FastAPI 接口）"""
    url = f"{BASE_URL}/v1/tasks"
    # 构造 file:// 绝对路径（Windows 需转换反斜杠）
    abs_path = os.path.abspath(TRAIN_DATA_PATH)
    file_uri = f"file:///{abs_path.replace(os.sep, '/')}"
    
    # 接口要求：algorithm 和 data_uri 作为查询参数，params 作为 JSON body
    params = {"algorithm": ALGORITHM, "data_uri": file_uri}
    json_data = {"params": TRAIN_PARAMS}
    
    try:
        print(f"🚀 创建任务，算法：{ALGORITHM}，数据：{file_uri}")
        resp = requests.post(url, params=params, json=json_data)
        resp.raise_for_status()
        result = resp.json()
        task_id = result["task_id"]
        print(f"✅ 任务创建成功，task_id: {task_id}")
        return task_id
    except Exception as e:
        print(f"❌ 创建任务失败：{e}")
        if 'resp' in locals():
            print(resp.text)
        return None

def wait_for_completion(task_id, timeout=300, interval=3):
    """轮询任务状态直到完成或失败"""
    url = f"{BASE_URL}/v1/tasks/{task_id}/status"
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            status = resp.json()
            print(f"⏳ 状态：{status['status']}，已等待 {int(time.time()-start)} 秒")
            if status["status"] == "completed":
                print("✅ 任务完成")
                return True
            elif status["status"] == "failed":
                print(f"❌ 任务失败：{status.get('error', '未知错误')}")
                return False
            time.sleep(interval)
        except Exception as e:
            print(f"⚠️ 查询状态异常：{e}")
            time.sleep(interval)
    print("❌ 任务超时")
    return False

def download_model(task_id):
    """下载加密模型（返回二进制内容）"""
    url = f"{BASE_URL}/v1/tasks/{task_id}/result"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        model_hex = data["model"]
        model_bytes = bytes.fromhex(model_hex)
        print("✅ 模型下载成功")
        return model_bytes
    except Exception as e:
        print(f"❌ 下载模型失败：{e}")
        if 'resp' in locals():
            print(resp.text)
        return None

def load_model(model_bytes):
    """反序列化模型（pickle）"""
    try:
        model = pickle.loads(model_bytes)
        print("✅ 模型加载成功")
        return model
    except Exception as e:
        print(f"❌ 模型加载失败：{e}")
        return None

def evaluate_model(model):
    """使用测试集评估回归模型"""
    # 读取测试集（假设最后一列为标签 actual_payout）
    df_test = pd.read_csv(TEST_DATA_PATH)
    X_test = df_test.iloc[:, :-1].values
    y_test = df_test.iloc[:, -1].values

    try:
        y_pred = model.predict(X_test)
    except Exception as e:
        print(f"❌ 模型预测失败：{e}")
        return False

    # 计算评估指标
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    print("\n📊 测试集评估结果：")
    print(f"   平均绝对误差 (MAE)：{mae:.2f}")
    print(f"   决定系数 (R²)：{r2:.4f}")
    return True

def main():
    print("=" * 50)
    print("    密态训练服务回归测试脚本")
    print("=" * 50)
    
    if not check_files():
        return

    # 1. 创建任务
    task_id = create_task()
    if not task_id:
        return

    # 2. 等待训练完成
    if not wait_for_completion(task_id):
        return

    # 3. 下载模型
    model_bytes = download_model(task_id)
    if not model_bytes:
        return

    # 4. 加载模型
    model = load_model(model_bytes)
    if not model:
        return

    # 5. 评估
    evaluate_model(model)

    print("\n✅ 测试流程结束，服务运行正常！")

if __name__ == "__main__":
    main()