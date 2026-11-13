"""挂租户的模型基类。

新增表只要继承 `TenantMixin`，就会自动获得：
- `tenant_id` 列（NOT NULL，外键到 tenants.id，带单列索引）；
- `do_orm_execute` 的统一行级过滤；
- `before_flush` 的写入兜底与跨租户写入拦截。

`default=1` 仅为兼容本阶段尚未改造的写入路径（原生 insert / 历史代码），
P2 全量改造后应移除默认值，改为强制从上下文取值。
"""
from sqlalchemy import Column, Integer


class TenantMixin:
    # 不建数据库外键：本阶段只做行级隔离，跨租户引用由写入校验拦截；
    # 复合/单列 FK 在 P2 全量改造时统一补（见方案 Q6 取舍）。
    tenant_id = Column(
        Integer,
        nullable=False,
        index=True,
        default=1,
        server_default="1",
    )
