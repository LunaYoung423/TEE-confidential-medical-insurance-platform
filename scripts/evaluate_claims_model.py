#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对解密后的分类模型（integrated_client 保存的 model_*.pkl）在验证集上评估。
验证集须与训练使用同一套 prepare_medical_claims_csv 列结构。

用法:
  python scripts/evaluate_claims_model.py --model model_xxx.pkl --val data/val_claims_numeric.csv
"""
import argparse
import pickle

import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, help="解密后的 .pkl 路径")
    p.add_argument("--val", required=True, help="val_claims_numeric.csv")
    args = p.parse_args()

    with open(args.model, "rb") as f:
        model = pickle.load(f)

    df = pd.read_csv(args.val)
    X = df.iloc[:, :-1].values
    y = df.iloc[:, -1].values.astype(int)

    proba = getattr(model, "predict_proba", None)
    y_pred = model.predict(X)
    print("准确率:", accuracy_score(y, y_pred))
    if proba is not None:
        pr = proba(X)
        if pr.shape[1] >= 2:
            print("AUC:", roc_auc_score(y, pr[:, 1]))
    print("\n分类报告:\n", classification_report(y, y_pred, digits=4))


if __name__ == "__main__":
    main()
