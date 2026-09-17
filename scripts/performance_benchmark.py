#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能与一致性基准：明文训练 vs「与生产一致的 SM4 包壳 + 训练 + 模型加解密」。

用于比赛材料中的：
- 密态路径与明文路径在相同数据、相同超参下的指标一致性；
- 相对明文纯训练的耗时损耗（训练+国密加解密流水线；完整机密容器端到端请配合手册用 time/日志测量）。

用法（在项目根目录 confidential-computing-platform/ 下）:
  python scripts/performance_benchmark.py --train data/train_claims_numeric.csv --val data/val_claims_numeric.csv --runs 5
  python scripts/performance_benchmark.py --train data/train_claims_numeric.csv --json-out reports/benchmark.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

# 项目根目录
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score

from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT

from module2.algorithms import get_algorithm
from module2.utils.data_loader import load_data_from_bytes


def _sm4_encrypt_ecb(plain: bytes, key: bytes) -> bytes:
    crypt = CryptSM4()
    crypt.set_key(key, SM4_ENCRYPT)
    pad = 16 - (len(plain) % 16)
    padded = plain + bytes([pad] * pad)
    return crypt.crypt_ecb(padded)


def _sm4_decrypt_ecb(cipher: bytes, key: bytes) -> bytes:
    crypt = CryptSM4()
    crypt.set_key(key, SM4_DECRYPT)
    out = crypt.crypt_ecb(cipher)
    pl = out[-1]
    if 1 <= pl <= 16:
        return out[:-pl]
    return out


def _read_csv_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _train_time_only(algorithm: str, train_csv: str, params: dict) -> tuple[float, object]:
    df = pd.read_csv(train_csv)
    X = df.iloc[:, :-1].values
    y = df.iloc[:, -1].values
    t0 = time.perf_counter()
    algo = get_algorithm(algorithm)
    model = algo.train(X, y, params)
    elapsed = time.perf_counter() - t0
    return elapsed, model


def _crypto_pipeline_time(
    algorithm: str, train_csv: str, params: dict, key: bytes
) -> tuple[float, object]:
    plain = _read_csv_bytes(train_csv)
    t0 = time.perf_counter()
    enc = _sm4_encrypt_ecb(plain, key)
    dec = _sm4_decrypt_ecb(enc, key)
    X, y = load_data_from_bytes(dec)
    algo = get_algorithm(algorithm)
    model = algo.train(X, y, params)
    model_bytes = algo.save_model(model)
    enc_model = _sm4_encrypt_ecb(model_bytes, key)
    _ = _sm4_decrypt_ecb(enc_model, key)
    elapsed = time.perf_counter() - t0
    return elapsed, model


def _metrics(model, val_csv: str) -> dict:
    df = pd.read_csv(val_csv)
    X = df.iloc[:, :-1].values
    y = df.iloc[:, -1].values.astype(int)
    pred = model.predict(X)
    out = {"accuracy": float(accuracy_score(y, pred))}
    proba = getattr(model, "predict_proba", None)
    if proba is not None:
        pr = proba(X)
        if pr.shape[1] >= 2:
            try:
                out["auc"] = float(roc_auc_score(y, pr[:, 1]))
            except ValueError:
                out["auc"] = None
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="明文 vs 密态（SM4+训练+模型）性能与一致性基准")
    p.add_argument("--train", required=True, help="训练 CSV（最后一列为标签）")
    p.add_argument("--val", required=True, help="验证 CSV")
    p.add_argument("--algorithm", default="xgboost_classifier", help="与 module2 注册名一致")
    p.add_argument("--runs", type=int, default=5, help="每项重复次数（取中位数）")
    p.add_argument("--seed", type=int, default=42, help="用于生成 SM4 测试密钥（固定可复现）")
    p.add_argument("--json-out", default="", help="将结果写入 JSON 文件")
    args = p.parse_args()

    params = {
        "n_estimators": 50,
        "max_depth": 3,
        "random_state": 42,
        "n_jobs": 1,
    }
    if args.algorithm == "logistic_regression":
        params = {"max_iter": 1000, "random_state": 42, "solver": "lbfgs"}

    rng = np.random.RandomState(args.seed)
    key = bytes(rng.randint(0, 256, 16, dtype=np.uint8))

    plain_times: list[float] = []
    crypto_times: list[float] = []

    for _ in range(args.runs):
        t, _ = _train_time_only(args.algorithm, args.train, params)
        plain_times.append(t)
        t2, _ = _crypto_pipeline_time(args.algorithm, args.train, params, key)
        crypto_times.append(t2)

    med_plain = statistics.median(plain_times)
    med_crypto = statistics.median(crypto_times)
    overhead_pct = (med_crypto - med_plain) / med_plain * 100.0 if med_plain > 0 else 0.0

    _, m_plain = _train_time_only(args.algorithm, args.train, params)
    _, m_crypto = _crypto_pipeline_time(args.algorithm, args.train, params, key)
    met_plain = _metrics(m_plain, args.val)
    met_crypto = _metrics(m_crypto, args.val)

    acc_diff = abs(met_plain["accuracy"] - met_crypto["accuracy"])
    auc_plain = met_plain.get("auc")
    auc_crypto = met_crypto.get("auc")
    auc_diff = None
    if auc_plain is not None and auc_crypto is not None:
        auc_diff = abs(auc_plain - auc_crypto)

    report = {
        "train_csv": os.path.abspath(args.train),
        "val_csv": os.path.abspath(args.val),
        "algorithm": args.algorithm,
        "runs": args.runs,
        "median_plain_train_seconds": round(med_plain, 6),
        "median_crypto_pipeline_seconds": round(med_crypto, 6),
        "overhead_percent_vs_plain_train": round(overhead_pct, 2),
        "metrics_plain": met_plain,
        "metrics_crypto_pipeline": met_crypto,
        "accuracy_abs_diff": round(acc_diff, 8),
        "auc_abs_diff": round(auc_diff, 8) if auc_diff is not None else None,
        "note": "crypto_pipeline 含：训练数据 SM4 加解密 + 训练 + 模型 SM4 加解密；"
        "完整机密容器端到端请在 Linux/信创环境用手册中的方式测量（含容器与网络）。",
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入: {out_path.resolve()}", file=sys.stderr)

    if overhead_pct > 20.0:
        print(
            f"\n提示: 当前中位数损耗 {overhead_pct:.2f}% 超过 20%。"
            "赛题指标通常指「相同算力、优化后的密态训练」；可增大 n_estimators/数据维度"
            "使训练占比升高，或在信创 TEE 环境完成端到端实测后写入报告。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
