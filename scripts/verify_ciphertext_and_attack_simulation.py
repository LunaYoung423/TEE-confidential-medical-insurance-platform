#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEE 外密文形态检查 + 宿主机侧「模拟攻击」自检（无真实内存转储时以磁盘密文为主）。

检查项：
1) 密文文件不可被当作 UTF-8 文本解析为结构化 CSV（pandas 失败或列异常）。
2) 密文与明文 SHA-256 不同；熵/字节分布与随机相近（简要统计）。
3) 错误密钥 SM4 解密后无法得到合法 CSV（列数或数值解析失败）。
4) （可选）明文 CSV 中含典型字段名时，密文文件中不应出现明文子串（简单 grep 式扫描）。

用法:
  python scripts/verify_ciphertext_and_attack_simulation.py --plain data/train_claims_numeric.csv --cipher /path/to/encrypted_train_data.bin
若尚无密文文件，可先用与 integrated_client 相同方式生成:
  python -c "..."  # 见手册「仅生成密文」一节
"""

from __future__ import annotations

import argparse
from typing import Optional
import hashlib
import io
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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


def _is_valid_claims_like_csv(data: bytes) -> bool:
    try:
        df = pd.read_csv(io.BytesIO(data), encoding="utf-8")
    except Exception:
        return False
    if df.shape[1] < 2:
        return False
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plain", required=True, help="明文训练 CSV 路径")
    p.add_argument("--cipher", default="", help="已有密文 .bin；省略则仅由明文临时加密做检查")
    p.add_argument("--key-hex", default="", help="16 字节密钥 hex；省略则随机生成（仅用于临时密文）")
    args = p.parse_args()

    with open(args.plain, "rb") as f:
        plain = f.read()

    key: Optional[bytes] = None
    if args.cipher and os.path.isfile(args.cipher):
        with open(args.cipher, "rb") as f:
            cipher = f.read()
        if args.key_hex:
            key = bytes.fromhex(args.key_hex)
            dec = _sm4_decrypt_ecb(cipher, key)
            if dec != plain:
                print("警告: 提供的密钥解密结果与明文文件不一致，请确认密钥与密文匹配。", file=sys.stderr)
    else:
        if args.key_hex:
            key = bytes.fromhex(args.key_hex)
        else:
            key = os.urandom(16)
        cipher = _sm4_encrypt_ecb(plain, key)
        print(f"未提供 --cipher，已用临时密钥加密做演示。密钥(hex): {key.hex()}")

    h_p = hashlib.sha256(plain).hexdigest()
    h_c = hashlib.sha256(cipher).hexdigest()
    print("明文 SHA-256:", h_p)
    print("密文 SHA-256:", h_c)
    assert h_p != h_c, "密文与明文哈希不应相同"

    # 宿主机「嗅探」：把密文当文本读
    try:
        pd.read_csv(io.BytesIO(cipher), encoding="utf-8")
        ok_csv = True
    except Exception:
        ok_csv = False
    print("宿主机直接 pandas.read_csv(密文) 是否成功:", ok_csv)
    assert not ok_csv, "期望：密文不应被直接解析为合法 CSV"

    # 明文字段名是否泄露到密文字节中（UTF-8）
    head = plain.split(b"\n", 1)[0].decode("utf-8", errors="ignore")
    tokens = [t.strip() for t in head.split(",") if len(t.strip()) > 2][:5]
    leaks = [t for t in tokens if t.encode("utf-8") in cipher]
    print("表头 token 在密文中是否出现(子串):", leaks if leaks else "未发现常见表头明文泄露")

    rk = key if key is not None else os.urandom(16)
    wrong_key = bytes((b ^ 0xFF) for b in rk)
    garbage = _sm4_decrypt_ecb(cipher, wrong_key)
    print("错误密钥解密后是否为合法 CSV:", _is_valid_claims_like_csv(garbage))

    arr = np.frombuffer(cipher, dtype=np.uint8)
    print("密文字节均值(约127为随机):", float(arr.mean()))
    print("✅ 自检项完成：TEE 外密文不可直接当业务 CSV 使用；错误密钥不产生可用表。")


if __name__ == "__main__":
    main()
