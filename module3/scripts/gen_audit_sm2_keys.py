#!/usr/bin/env python3
"""生成供全平台共用的审计 SM2 密钥对（hex），写入 compose / 环境变量。各容器须使用同一对密钥验链才能通过。"""
from gmssl import sm2, func


def main():
    private_key = func.random_hex(64)
    crypt = sm2.CryptSM2(private_key, "")
    public_key = crypt._kg(int(private_key, 16), crypt.ecc_table["g"])
    print("export AUDIT_SM2_PRIVATE_KEY='%s'" % private_key)
    print("export AUDIT_SM2_PUBLIC_KEY='%s'" % public_key)
    print()
    print("# 或在项目根目录 .env 中增加：")
    print("AUDIT_SM2_PRIVATE_KEY=%s" % private_key)
    print("AUDIT_SM2_PUBLIC_KEY=%s" % public_key)


if __name__ == "__main__":
    main()
