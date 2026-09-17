#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将医保理赔场景原始 CSV（new_data.csv / medical_insurance_claims.csv）转为密态训练可用的「纯数值 CSV」：
- 逗号分隔，UTF-8，最后一列为标签 claim_flag（0/1）
- 与 module2.utils.data_loader 兼容（除最后一列外均为数值）

用法（在项目根目录）:
  python scripts/prepare_medical_claims_csv.py \\
    --input data/new_data.csv \\
    --train-out data/train_claims_numeric.csv \\
    --val-out data/val_claims_numeric.csv \\
    --train-size 2000

若全量仅 2001 条等，可把 --train-size 调小，但需满足 module2.config.Config.MIN_SAMPLES（默认 2000）。
"""

import argparse
import os

import pandas as pd


def _read_claims_csv(path: str) -> pd.DataFrame:
    """自动识别制表符或逗号分隔。"""
    for sep in ("\t", ",", ";"):
        try:
            df = pd.read_csv(path, sep=sep, encoding="utf-8")
            if len(df.columns) >= 5:
                return df
        except Exception:
            continue
    return pd.read_csv(path, encoding="utf-8")


def transform(df: pd.DataFrame) -> pd.DataFrame:
    required = [
        "age",
        "gender",
        "visit_date",
        "diagnosis_code",
        "drug_cost",
        "test_cost",
        "total_cost",
        "claim_flag",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少列: {missing}，当前列: {list(df.columns)}")

    out = pd.DataFrame()
    out["age"] = pd.to_numeric(df["age"], errors="coerce")

    g = df["gender"].astype(str).str.strip()
    out["gender"] = g.map({"男": 1, "女": 0, "1": 1, "0": 0}).fillna(0).astype(int)

    dt = pd.to_datetime(df["visit_date"], errors="coerce")
    out["visit_month"] = dt.dt.month.fillna(1).astype(int)
    out["visit_day"] = dt.dt.day.fillna(1).astype(int)

    # ICD-10 编码 -> 整数类别（训练/测试需同一套映射时，应使用同一文件一起 factorize）
    diag = df["diagnosis_code"].astype(str).str.strip().replace("", "_MISSING_")
    out["diagnosis_code"] = pd.Categorical(diag).codes.astype("int64")

    out["drug_cost"] = pd.to_numeric(df["drug_cost"], errors="coerce").fillna(0.0)
    out["test_cost"] = pd.to_numeric(df["test_cost"], errors="coerce").fillna(0.0)
    out["total_cost"] = pd.to_numeric(df["total_cost"], errors="coerce").fillna(0.0)
    out["claim_flag"] = pd.to_numeric(df["claim_flag"], errors="coerce").fillna(0).astype(int)

    out = out.dropna(subset=["age"])
    return out


def main():
    parser = argparse.ArgumentParser(description="医保理赔 CSV -> 数值训练集/验证集")
    parser.add_argument("--input", required=True, help="原始 new_data.csv 路径")
    parser.add_argument("--train-out", required=True, help="输出训练集 CSV")
    parser.add_argument("--val-out", required=True, help="输出验证集 CSV")
    parser.add_argument("--train-size", type=int, default=2000, help="训练集行数，其余进验证集")
    args = parser.parse_args()

    df = transform(_read_claims_csv(args.input))
    n = len(df)
    if n < args.train_size:
        raise SystemExit(
            f"数据仅 {n} 行，小于 --train-size={args.train_size}。"
            "请减小 train-size 或合并更多数据；并注意 MIN_SAMPLES=2000 限制。"
        )

    train = df.iloc[: args.train_size].copy()
    val = df.iloc[args.train_size :].copy()

    for p in (args.train_out, args.val_out):
        d = os.path.dirname(os.path.abspath(p))
        if d:
            os.makedirs(d, exist_ok=True)

    train.to_csv(args.train_out, index=False, encoding="utf-8")
    val.to_csv(args.val_out, index=False, encoding="utf-8")

    print(f"✅ 训练集: {len(train)} 行 -> {args.train_out}")
    print(f"✅ 验证集: {len(val)} 行 -> {args.val_out}")
    print("列顺序（最后一列为标签）:", list(train.columns))


if __name__ == "__main__":
    main()
