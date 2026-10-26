from cryptography.fernet import Fernet
import os
import base64

def _find_existing_key(env_path: str) -> str | None:
    """从 .env 文件中查找现有的密钥（返回原始字符串，不做解码）"""
    if not os.path.exists(env_path):
        return None

    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('CREDENTIAL_SECRET_KEY='):
                return line.split('=', 1)[1]

    return None


def get_or_generate_key() -> bytes:
    """获取或生成 Fernet 加密密钥，兼容新旧两种密钥格式。

    - 新格式（当前代码）：Fernet.generate_key() 直接存储（44 字符 urlsafe base64）
    - 旧格式（遗留）：二次 base64 编码后存储（~60 字符），需解码一次
    返回 bytes 供 Fernet() 直接使用。
    """
    secret_key = os.environ.get("CREDENTIAL_SECRET_KEY")
    if not secret_key:
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        secret_key = _find_existing_key(env_path)

    if secret_key:
        key_str = secret_key.strip()
        # 旧格式检测：二次 base64 编码的密钥长度 > 50 字符
        if len(key_str) > 50:
            return base64.urlsafe_b64decode(key_str + '==')
        # 新格式：直接使用
        return key_str.encode()

    # 生成新密钥（正确格式：不二次编码）
    key = Fernet.generate_key()
    env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
    with open(env_path, 'a') as f:
        f.write(f"\nCREDENTIAL_SECRET_KEY={key.decode()}\n")
    return key


# 全局 Fernet 实例（新格式）
_fernet = Fernet(get_or_generate_key())
# 懒加载：旧格式 Fernet 实例（用于解密已加密的旧数据，向上兼容）
_legacy_fernet = None


def encrypt_password(plain_text: str) -> str:
    """加密密码，返回base64字符串"""
    if not plain_text:
        return ""
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_password(cipher_text: str) -> str:
    """解密密码，返回明文。自动兼容新旧两种密钥格式。
    
    如果解密失败（如密钥不一致），记录警告并返回空字符串，
    避免因密钥问题导致整个备份任务失败。
    """
    if not cipher_text:
        return ""
    try:
        return _fernet.decrypt(cipher_text.encode()).decode()
    except Exception as e:
        # 尝试旧格式密钥（向上兼容已加密的数据）
        global _legacy_fernet
        if _legacy_fernet is None:
            try:
                from cryptography.fernet import Fernet as _Fernet
                key_bytes = _fernet._encryption_key if hasattr(_fernet, '_encryption_key') else None
                if key_bytes:
                    _legacy_fernet = _Fernet(base64.urlsafe_b64decode(key_bytes))
            except Exception:
                _legacy_fernet = False
        if _legacy_fernet:
            try:
                return _legacy_fernet.decrypt(cipher_text.encode()).decode()
            except Exception:
                pass
        # 记录警告但不抛出异常，避免因密钥问题导致整个备份任务失败
        import logging
        logger = logging.getLogger("cornerstone")
        logger.warning(f"凭证解密失败，密钥可能不一致，请检查 .env 中的 CREDENTIAL_SECRET_KEY 设置")
        return ""


# ==================== 通用敏感串加解密（AI api_key 等） ====================

SECRET_ENC_PREFIX = "enc:"


def encrypt_secret(plain_text: str) -> str:
    """加密敏感字符串（如 AI api_key），带 enc: 前缀便于识别。幂等：已加密返回原值。"""
    if not plain_text:
        return ""
    if plain_text.startswith(SECRET_ENC_PREFIX):
        return plain_text
    return SECRET_ENC_PREFIX + _fernet.encrypt(plain_text.encode()).decode()


def decrypt_secret(value: str) -> str:
    """解密 encrypt_secret 的结果。无前缀（存量明文）原样返回；解密失败返回空串。"""
    if not value:
        return ""
    if not value.startswith(SECRET_ENC_PREFIX):
        return value
    try:
        return _fernet.decrypt(value[len(SECRET_ENC_PREFIX):].encode()).decode()
    except Exception:
        import logging
        logging.getLogger("cornerstone").warning(
            "敏感串解密失败（enc: 前缀），密钥可能不一致，返回空串"
        )
        return ""
