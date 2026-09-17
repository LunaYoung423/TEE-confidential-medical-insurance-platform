import os
from typing import Tuple, Union

from gmssl import sm2, func

from module3.audit.pysmx_SM3 import digest as sm3_digest


def _normalize_hash_hex(data: Union[str, bytes]) -> str:
    if isinstance(data, str) and len(data) == 64 and all(
        c in "0123456789abcdefABCDEF" for c in data
    ):
        return data.lower()
    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data
    return sm3_digest(data_bytes).hex()


def _public_key_from_private(private_key_hex: str) -> str:
    """gmssl 3.x 无 src/sm2.pk；用 d*G 推导公钥坐标（128 hex，无 04 前缀，与 CryptSM2 内部一致）。"""
    crypt = sm2.CryptSM2(private_key_hex, "")
    return crypt._kg(int(private_key_hex, 16), crypt.ecc_table["g"])


class SM2Signature:
    """审计日志 SM2 签名。兼容 PyPI「gmssl」3.x（CryptSM2），不再依赖已移除的 sm2.pk。"""

    def __init__(self, private_key=None, public_key=None):
        self.private_key = private_key or os.environ.get("AUDIT_SM2_PRIVATE_KEY")
        self.public_key = public_key or os.environ.get("AUDIT_SM2_PUBLIC_KEY")

        if not self.private_key:
            self._generate_keys()
        elif not self.public_key:
            self.public_key = _public_key_from_private(self.private_key)

    def _generate_keys(self):
        self.private_key = func.random_hex(64)
        self.public_key = _public_key_from_private(self.private_key)

    def sign(self, data: str) -> str:
        hash_hex = _normalize_hash_hex(data)
        crypt = sm2.CryptSM2(self.private_key, self.public_key)
        k = func.random_hex(crypt.para_len)
        sig = crypt.sign(bytes.fromhex(hash_hex), k)
        if not sig:
            raise RuntimeError("SM2 签名失败（请重试或检查 gmssl 与随机数 k）")
        return sig

    def verify(self, data: str, signature: str) -> bool:
        hash_hex = _normalize_hash_hex(data)
        hash_bytes = bytes.fromhex(hash_hex)
        try:
            dummy_priv = "0" * 64
            crypt = sm2.CryptSM2(dummy_priv, self.public_key)
            return bool(crypt.verify(signature, hash_bytes))
        except Exception:
            return False

    def get_public_key(self) -> str:
        return self.public_key

    def get_keys(self) -> Tuple[str, str]:
        return self.private_key, self.public_key
