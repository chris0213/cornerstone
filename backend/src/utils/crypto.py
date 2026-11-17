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


# 全局 Fernet 实例（get_or_generate_key 已兼容新旧两种存储格式，归一化为同一密钥）
_fernet = Fernet(get_or_generate_key())


def encrypt_password(plain_text: str) -> str:
    """加密密码，返回base64字符串"""
    if not plain_text:
        return ""
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_password(cipher_text: str) -> str:
    """解密密码，返回明文。自动兼容新旧两种密钥格式。

    如果解密失败（如密钥不一致），记录警告并返回空字符串，
    避免因密钥问题导致整个备份任务失败。

    注意：对生产设备 SSH 而言，解密失败应使用 decrypt_password_strict
    立即中止，而不是拿空密码去重试登录（可能触发设备账号锁定）。
    """
    try:
        return decrypt_password_strict(cipher_text)
    except ValueError:
        import logging
        logging.getLogger("cornerstone").warning(
            "凭证解密失败，密钥可能不一致，请检查 .env 中的 CREDENTIAL_SECRET_KEY 设置"
        )
        return ""


def decrypt_password_strict(cipher_text: str) -> str:
    """严格版解密：失败抛 ValueError，绝不静默返回空串。

    适用场景：SSH 登录生产设备前的凭证准备。空密码重试可能触发设备侧
    账号锁定 / 入侵防护，把管理账号锁死——宁可不连，不可错连。
    """
    if not cipher_text:
        return ""
    # get_or_generate_key 已把旧「二次 base64 存储格式」与新「直存格式」归一化为同一把底层密钥，
    # _fernet 即可解密全部存量密文；无需（也无法）用「当前密钥」构造旧密钥实例。
    # 原 _legacy_fernet 回退分支把 AES128Key 对象误传给 urlsafe_b64decode，必抛异常→恒失败，
    # 属永不生效的死代码（修复 #17），故删除。解密失败即密钥真不一致，直接抛错。
    try:
        return _fernet.decrypt(cipher_text.encode()).decode()
    except Exception:
        raise ValueError("凭证解密失败：密钥可能不一致，请检查 CREDENTIAL_SECRET_KEY")


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
