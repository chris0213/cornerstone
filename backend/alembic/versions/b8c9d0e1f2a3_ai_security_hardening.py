"""ai security hardening: encrypt stored api_keys, add ai_chat_logs metadata columns

Revision ID: b8c9d0e1f2a3
Revises: f2a3b4c5d6e7
Create Date: 2026-10-26 10:00:00.000000

升级安全说明：
- ai_config（settings 表 JSON）中的存量明文 api_key 统一加密为 enc:<Fernet密文>，
  复用 CREDENTIAL_SECRET_KEY，与凭据加密同一密钥体系；已带 enc: 前缀的跳过（幂等）。
- ai_chat_logs 新增 model / duration_ms / status / error_message 四个可空列，
  旧代码不读写时行为不变。
- downgrade 完全可逆：解密还原明文 key（幂等）+ 删除四列。
- 加密/解密纯函数来自 src.services.ai_client，迁移与业务共用同一实现。
"""

from typing import Sequence, Union
import json
import logging

from alembic import op
import sqlalchemy as sa

from src.services.ai_client import AI_CONFIG_KEY, encrypt_configs_api_keys, decrypt_configs_api_keys

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load_ai_configs(bind) -> list:
    """读取 settings 表 ai_config JSON（列表格式），不存在或格式不符返回空列表。

    注意：列名 key 不加反引号——PostgreSQL 不支持 ` 反引号引用（key 为非保留字，
    裸写跨 SQLite/PG 兼容）；反引号是 MySQL 专用语法，曾导致生产 PG 迁移崩溃。
    """
    row = bind.execute(
        sa.text("SELECT value FROM settings WHERE key = :k"),
        {"k": AI_CONFIG_KEY},
    ).first()
    if not row or not row[0]:
        return []
    try:
        cfg = json.loads(row[0])
    except json.JSONDecodeError:
        logger.warning("ai_config 不是合法 JSON，跳过 api_key 迁移")
        return []
    return cfg if isinstance(cfg, list) else []


def _save_ai_configs(bind, configs: list) -> None:
    bind.execute(
        sa.text("UPDATE settings SET value = :v WHERE key = :k"),
        {"v": json.dumps(configs, ensure_ascii=False), "k": AI_CONFIG_KEY},
    )


def upgrade() -> None:
    # 1) 存量明文 api_key 加密（幂等：已是 enc: 前缀的跳过）
    bind = op.get_bind()
    configs = _load_ai_configs(bind)
    if configs:
        new_configs, changed = encrypt_configs_api_keys(configs)
        if changed:
            _save_ai_configs(bind, new_configs)
        logger.info(f"ai_config api_key 加密完成，共处理 {changed} 条")

    # 2) ai_chat_logs 增加调用元数据列（均可空，兼容历史数据）
    with op.batch_alter_table('ai_chat_logs') as batch_op:
        batch_op.add_column(sa.Column('model', sa.String(length=100), nullable=True,
                                      comment='AI 模型名'))
        batch_op.add_column(sa.Column('duration_ms', sa.Integer(), nullable=True,
                                      comment='调用耗时（毫秒）'))
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=True,
                                      comment='结果状态：success/failed'))
        batch_op.add_column(sa.Column('error_message', sa.Text(), nullable=True,
                                      comment='失败原因（截断存储）'))


def downgrade() -> None:
    # 1) ai_chat_logs 删除元数据列
    with op.batch_alter_table('ai_chat_logs') as batch_op:
        batch_op.drop_column('error_message')
        batch_op.drop_column('status')
        batch_op.drop_column('duration_ms')
        batch_op.drop_column('model')

    # 2) enc: 前缀 api_key 解密还原明文（幂等：无前缀的跳过）
    bind = op.get_bind()
    configs = _load_ai_configs(bind)
    if configs:
        new_configs, changed = decrypt_configs_api_keys(configs)
        if changed:
            _save_ai_configs(bind, new_configs)
        logger.info(f"ai_config api_key 解密还原完成，共处理 {changed} 条")
