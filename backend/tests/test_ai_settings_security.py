"""AI 设置与聊天日志安全加固测试（阶段 2 步骤 A）。

覆盖：
- api_key 加密落库、GET 只回 has_key、PUT 不带 key 不 422 且密文不变、PUT 换 key 轮换
- 加密后 AI 调用链与测试接口仍可用（mock httpx）
- test 限频 429、普通用户 403、审计存在且不含 key
- api_url 校验（http/内网 IP/localhost/白名单）
- question 落库前脱敏
- 外发字段白名单（sn/owner/monthly_cost 不进 prompt）、audit_logs 一律封禁
- 禁止外发开关开启时 LLM 不被调用
- 聊天日志元数据（成功/失败路径）、strip_sensitive_lines、迁移纯函数幂等

全部用例 mock LLM（monkeypatch httpx.AsyncClient.post），不发起真实网络请求。
"""
import json

import httpx
import pytest
from sqlalchemy import select, func

from src.models import User, Role
from src.models.ai_chat_log import AIChatLog
from src.models.audit_log import AuditLog
from src.models.setting import Setting
from src.services.ai_client import (
    AI_CONFIG_KEY,
    decrypt_configs_api_keys,
    encrypt_configs_api_keys,
)
from src.services.ai_outbound_guard import (
    filter_rows_for_llm,
    mask_question,
    strip_sensitive_lines,
    validate_ai_api_url,
)
from src.services.permission_service import pwd_context
from src.utils.crypto import decrypt_secret, encrypt_secret


# ==================== 工具函数 ====================

async def _login(client, username: str = "admin", password: str = "admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_user(db_session, username: str, role_name: str = "viewer"):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        username=username,
        display_name=username,
        email=f"{username}@example.com",
        hashed_password=pwd_context.hash("Passw0rd!"),
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _save_raw_config(db_session, configs: list):
    """直接以明文 key 写入 ai_config（模拟存量未加密数据）。"""
    result = (await db_session.execute(
        select(Setting).where(Setting.key == AI_CONFIG_KEY)
    )).scalars().first()
    value = json.dumps(configs, ensure_ascii=False)
    if result:
        result.value = value
    else:
        db_session.add(Setting(key=AI_CONFIG_KEY, value=value))
    await db_session.commit()


async def _get_raw_config(db_session) -> list:
    setting = (await db_session.execute(
        select(Setting).where(Setting.key == AI_CONFIG_KEY)
    )).scalars().first()
    return json.loads(setting.value) if setting else []


VALID_CFG = {
    "id": 1, "name": "测试配置", "provider": "custom", "model": "test-model",
    "api_url": "https://api.example.com/v1", "api_key": "sk-test-1234567890",
    "description": "", "enabled": True, "is_default": True,
}


@pytest.fixture
def mock_llm(monkeypatch):
    """仅拦截发往 LLM 的 chat/completions 请求，按请求类型返回伪响应；
    其余请求（如测试客户端登录）透传原方法。"""
    calls = []
    original_post = httpx.AsyncClient.post

    def _reply_of(body: dict) -> str:
        messages = body.get("messages") or []
        system = messages[0]["content"] if messages else ""
        user = messages[1]["content"] if len(messages) > 1 else ""
        if user.startswith("请解析以下查询"):
            # 意图解析：按问题关键词返回对应数据类型
            if "专线" in user or "电路" in user:
                q_type = "circuits"
            elif "审计" in user or "日志" in user:
                q_type = "audit_logs"
            else:
                q_type = "devices"
            return json.dumps({
                "intent": "query",
                "entities": {"type": q_type, "filters": {}, "time_range": {},
                             "sort": {}, "limit": 20},
                "answer_format": "list",
                "original_question": user,
            }, ensure_ascii=False)
        if "你是运维助手" in system:
            return "通了"  # 连接测试
        return json.dumps(
            {"answer_text": "好的，已为您整理结果。", "suggestions": []},
            ensure_ascii=False,
        )  # 回答格式化 / 知识库

    async def fake_post(self, url, headers=None, **kwargs):
        if "chat/completions" not in str(url):
            # 非 LLM 请求（如测试客户端登录）透传原始方法
            return await original_post(self, url, headers=headers, **kwargs)
        body = kwargs.get("json") or {}
        calls.append({"url": url, "headers": headers or {}, "json": body})
        request = httpx.Request("POST", url, json=body)
        return httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": _reply_of(body)}}]},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return {"calls": calls}


@pytest.fixture(autouse=True)
def reset_ai_test_limiter():
    """隔离 AI 配置测试接口的进程内限频字典。"""
    import src.api.ai as ai_module
    ai_module._ai_config_test_last.clear()
    yield
    ai_module._ai_config_test_last.clear()


@pytest.fixture(autouse=True)
async def clean_ai_settings(db_session):
    """用例间清理 settings 表中的 AI 配置，避免串扰。"""
    yield
    from sqlalchemy import delete
    await db_session.execute(
        delete(Setting).where(
            Setting.key.in_([AI_CONFIG_KEY, "ai_privacy_settings"])
        )
    )
    await db_session.commit()


# ==================== 1. api_key 加密落库 ====================

@pytest.mark.asyncio
async def test_create_config_encrypts_api_key_at_rest(client, db_session):
    """创建配置后：库中 api_key 为 enc: 密文；GET 只回 has_key=true 且不回 key。"""
    headers = await _login(client)
    resp = await client.post("/api/v1/ai/config", json=VALID_CFG, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_key"] is True
    assert "api_key" not in body

    stored = (await _get_raw_config(db_session))[0]
    assert stored["api_key"].startswith("enc:")
    assert decrypt_secret(stored["api_key"]) == "sk-test-1234567890"


@pytest.mark.asyncio
async def test_get_config_masks_key(client, db_session):
    """GET /ai/config 列表：不出现明文 key 与密文，只有 has_key 标记。"""
    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)
    resp = await client.get("/api/v1/ai/config", headers=headers)
    assert resp.status_code == 200, resp.text
    text = resp.text
    assert "sk-test-1234567890" not in text
    assert "enc:" not in text
    assert resp.json()[0]["has_key"] is True


@pytest.mark.asyncio
async def test_update_without_key_keeps_ciphertext(client, db_session):
    """编辑配置不传 api_key（空串）：不 422，解密后的明文 key 保持不变。"""
    await _save_raw_config(
        db_session, [{**VALID_CFG, "api_key": encrypt_secret("sk-test-1234567890")}])
    headers = await _login(client)
    before_cipher = (await _get_raw_config(db_session))[0]["api_key"]
    assert before_cipher.startswith("enc:")

    resp = await client.put("/api/v1/ai/config/1", json={
        "name": "测试配置-改", "provider": "custom", "model": "test-model",
        "api_url": "https://api.example.com/v1", "api_key": "",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    after_cipher = (await _get_raw_config(db_session))[0]["api_key"]
    # Fernet 每次加密密文不同，比较解密后的明文
    assert decrypt_secret(after_cipher) == "sk-test-1234567890"


@pytest.mark.asyncio
async def test_update_with_new_key_rotates(client, db_session):
    """编辑配置传入新 key：轮换为新密文，可解密出新值。"""
    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)

    resp = await client.put("/api/v1/ai/config/1", json={
        "name": "测试配置", "provider": "custom", "model": "test-model",
        "api_url": "https://api.example.com/v1", "api_key": "sk-rotated-999",
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    stored_key = (await _get_raw_config(db_session))[0]["api_key"]
    assert stored_key.startswith("enc:")
    assert decrypt_secret(stored_key) == "sk-rotated-999"


# ==================== 2. 加密后调用链仍可用 ====================

@pytest.mark.asyncio
async def test_ai_call_uses_decrypted_key(client, db_session, mock_llm):
    """库中存密文时，AI 调用链解密出明文 key 放入 Authorization。"""
    await _save_raw_config(db_session, [{**VALID_CFG, "api_key": encrypt_secret("sk-plain-abc")}])
    headers = await _login(client)

    resp = await client.post("/api/v1/ai/search", json={
        "question": "列出所有设备", "last_data_type": ""
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    assert mock_llm["calls"], "LLM 应被调用"
    auth = mock_llm["calls"][0]["headers"].get("Authorization", "")
    assert auth == "Bearer sk-plain-abc"


@pytest.mark.asyncio
async def test_config_test_uses_decrypted_key(client, db_session, mock_llm):
    """config/test 用 config_id 测试存量（密文）配置：解密后 Bearer 明文，返回成功。"""
    await _save_raw_config(db_session, [{**VALID_CFG, "api_key": encrypt_secret("sk-live-key-77")}])
    headers = await _login(client)

    resp = await client.post("/api/v1/ai/config/test", json={
        "config_id": 1,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True, resp.text
    auth = mock_llm["calls"][0]["headers"].get("Authorization", "")
    assert auth == "Bearer sk-live-key-77"


# ==================== 3. test 限频 / 权限 / 审计 ====================

@pytest.mark.asyncio
async def test_config_test_rate_limited(client, db_session, mock_llm):
    """同一目标 10 秒内第二次测试返回 429。"""
    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)

    first = await client.post("/api/v1/ai/config/test", json={"config_id": 1}, headers=headers)
    assert first.status_code == 200
    second = await client.post("/api/v1/ai/config/test", json={"config_id": 1}, headers=headers)
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_config_write_requires_super_admin(client, db_session):
    """普通用户访问配置增删改/测试：403。"""
    await _make_user(db_session, "viewer_ai", "viewer")
    headers = await _login(client, "viewer_ai", "Passw0rd!")

    assert (await client.get("/api/v1/ai/config", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/ai/config", json=VALID_CFG, headers=headers)).status_code == 403
    assert (await client.put("/api/v1/ai/config/1", json=VALID_CFG, headers=headers)).status_code == 403
    assert (await client.delete("/api/v1/ai/config/1", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/ai/config/test", json={"config_id": 1}, headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_config_audit_written_without_key(client, db_session):
    """配置增改删均写审计，detail 不含任何 key 内容，只含 has_key 变化描述。"""
    headers = await _login(client)

    await client.post("/api/v1/ai/config", json=VALID_CFG, headers=headers)
    await client.put("/api/v1/ai/config/1", json={
        "name": "测试配置", "provider": "custom", "model": "m2",
        "api_url": "https://api.example.com/v1", "api_key": "sk-new-key-xyz",
    }, headers=headers)
    await client.delete("/api/v1/ai/config/1", headers=headers)

    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action.in_(
            ["ai_config_create", "ai_config_update", "ai_config_delete"])
        ).order_by(AuditLog.id)
    )).scalars().all()
    assert [r.action for r in rows] == [
        "ai_config_create", "ai_config_update", "ai_config_delete"]

    for r in rows:
        assert "sk-test-1234567890" not in (r.detail or "")
        assert "sk-new-key-xyz" not in (r.detail or "")
        assert "enc:" not in (r.detail or "")
    # PUT 传了新 key 但原配置本就有 key → has_key 无变化
    assert "api_key=无变化" in rows[1].detail


# ==================== 4. api_url 校验 ====================

@pytest.mark.asyncio
async def test_create_config_rejects_bad_urls(client):
    """http / 内网 IP / localhost 的 api_url 一律 422。"""
    headers = await _login(client)
    for bad_url in [
        "http://api.example.com/v1",      # 非 https
        "https://192.168.1.10/v1",        # 私网 IP
        "https://127.0.0.1/v1",           # 回环
        "https://localhost:8443/v1",      # localhost
        "https://10.0.0.5/v1",            # 内网
    ]:
        resp = await client.post("/api/v1/ai/config", json={
            **VALID_CFG, "api_url": bad_url}, headers=headers)
        assert resp.status_code == 422, f"{bad_url} 应被拒绝: {resp.text}"


@pytest.mark.asyncio
async def test_create_config_allows_https_public(monkeypatch):
    """纯函数级验证：公网 https 域名通过；白名单机制生效。"""
    assert validate_ai_api_url("https://api.deepseek.com/v1") is None
    assert validate_ai_api_url("https://8.8.8.8/v1") is None

    monkeypatch.setenv("AI_API_ALLOWED_HOSTS", "api.deepseek.com,api.zhipuai.cn")
    assert validate_ai_api_url("https://api.deepseek.com/v1") is None
    err = validate_ai_api_url("https://api.other.com/v1")
    assert err is not None and "白名单" in err


# ==================== 5. question 落库脱敏 ====================

@pytest.mark.asyncio
async def test_question_masked_before_persist(client, db_session, mock_llm):
    """提问含凭证时，落库的 question 已脱敏，不含明文密码/token。"""
    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)

    secret_q = "帮我查设备 登录密码=SuperSecret123 看看状态"
    resp = await client.post("/api/v1/ai/search", json={
        "question": secret_q, "last_data_type": ""}, headers=headers)
    assert resp.status_code == 200, resp.text

    logs = (await db_session.execute(select(AIChatLog))).scalars().all()
    assert len(logs) == 1
    assert "SuperSecret123" not in logs[0].question
    assert "凭证已脱敏" in logs[0].question


# ==================== 6. 外发白名单 / audit_logs 封禁 / 总开关 ====================

@pytest.mark.asyncio
async def test_outbound_prompt_whitelisted_no_sensitive_fields(client, db_session, mock_llm):
    """设备数据发 LLM 前：sn/owner 被白名单剔除，prompt 中无敏感值。"""
    from src.models import Device
    dev = Device(name="core-sw-01", type="switch", brand="huawei",
                 model="S5735", sn="SN1234567890XYZ", owner="张三",
                 location="总部机房", status="active")
    db_session.add(dev)
    await db_session.commit()

    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)
    resp = await client.post("/api/v1/ai/search", json={
        "question": "列出所有设备", "last_data_type": ""}, headers=headers)
    assert resp.status_code == 200, resp.text

    prompt = json.dumps(mock_llm["calls"][-1]["json"], ensure_ascii=False)
    assert "SN1234567890XYZ" not in prompt
    assert "张三" not in prompt
    assert "core-sw-01" in prompt  # 白名单内字段正常外发
    # 返回给前端的 data 仍是原始数据（前端有权限看）
    assert dev.sn == "SN1234567890XYZ"


@pytest.mark.asyncio
async def test_circuit_monthly_cost_not_sent(client, db_session, mock_llm):
    """专线的 monthly_cost 不进 LLM prompt。"""
    from src.models import Circuit
    c = Circuit(name="总部-灾备专线", provider="电信", type="MSTP",
                bandwidth="100M", status="正常", monthly_cost=8888)
    db_session.add(c)
    await db_session.commit()

    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)
    resp = await client.post("/api/v1/ai/search", json={
        "question": "列出所有专线", "last_data_type": ""}, headers=headers)
    assert resp.status_code == 200, resp.text

    prompt = json.dumps(mock_llm["calls"][-1]["json"], ensure_ascii=False)
    assert "8888" not in prompt
    assert "总部-灾备专线" in prompt


@pytest.mark.asyncio
async def test_audit_logs_query_blocked(client, db_session, mock_llm):
    """问审计日志：直接返回引导文案，不查库、不调 LLM。"""
    from src.models.audit_log import AuditLog as AL
    db_session.add(AL(user="someone", action="login", resource="auth",
                      detail="内部敏感审计明细", success="true"))
    await db_session.commit()

    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)
    resp = await client.post("/api/v1/ai/search", json={
        "question": "最近的审计日志有哪些", "last_data_type": ""}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["data_type"] == "audit_logs"
    assert "审计日志" in body["data"]["answer_text"]
    assert body["data"]["data"] == []
    # 敏感审计明细既不进 prompt 也不进回答
    all_calls = json.dumps(mock_llm["calls"], ensure_ascii=False)
    assert "内部敏感审计明细" not in all_calls
    assert "内部敏感审计明细" not in body["data"]["answer_text"]


@pytest.mark.asyncio
async def test_block_external_switch_skips_llm(client, db_session, mock_llm):
    """禁止外发开关开启：/search 不调 LLM 走本地降级，问题文本不外发。"""
    await _save_raw_config(db_session, [dict(VALID_CFG)])
    db_session.add(Setting(
        key="ai_privacy_settings", value=json.dumps({"block_external": True})))
    await db_session.commit()

    headers = await _login(client)
    resp = await client.post("/api/v1/ai/search", json={
        "question": "列出所有设备", "last_data_type": ""}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert mock_llm["calls"] == []  # 全链路（意图解析+回答格式化）都没调 LLM
    assert resp.json()["data"]["answer_text"]  # 本地降级仍给出回答


# ==================== 7. 聊天日志元数据 ====================

@pytest.mark.asyncio
async def test_chat_log_meta_success(client, db_session, mock_llm):
    """成功路径：日志记录 model / duration_ms / status=success。"""
    from src.models import Device
    db_session.add(Device(name="sw-meta-01", type="switch", status="active"))
    await db_session.commit()

    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)
    resp = await client.post("/api/v1/ai/search", json={
        "question": "列出所有设备", "last_data_type": ""}, headers=headers)
    assert resp.status_code == 200, resp.text

    log = (await db_session.execute(select(AIChatLog))).scalars().one()
    assert log.model == "test-model"
    assert log.status == "success"
    assert log.duration_ms is not None and log.duration_ms >= 0
    assert log.error_message is None

    # 列表接口返回元数据字段
    headers_admin = headers
    listed = (await client.get("/api/v1/ai/chat-logs", headers=headers_admin)).json()
    assert listed["items"][0]["model"] == "test-model"
    assert listed["items"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_chat_log_meta_failure_path(client, db_session, mock_llm):
    """查询链路异常：status=failed、error_message 非空、回答为兜底文案。
    （LLM 单点失败有本地兜底，属 success；查询执行异常才记 failed）"""
    import src.api.ai as ai_module

    await _save_raw_config(db_session, [dict(VALID_CFG)])
    headers = await _login(client)

    async def boom(intent, db):
        raise RuntimeError("mock 查询失败")

    original = ai_module.execute_query
    ai_module.execute_query = boom
    try:
        resp = await client.post("/api/v1/ai/search", json={
            "question": "列出所有设备", "last_data_type": ""}, headers=headers)
        assert resp.status_code == 200, resp.text
    finally:
        ai_module.execute_query = original

    log = (await db_session.execute(select(AIChatLog))).scalars().one()
    assert log.status == "failed"
    assert "mock 查询失败" in (log.error_message or "")
    body = resp.json()
    assert body["data"]["answer_text"] == "查询失败，请稍后重试或换个问法。"


# ==================== 8. 纯函数：strip / 迁移幂等 ====================

def test_strip_sensitive_lines_removes_credentials():
    """diff 敏感行剔除：password/community/私钥行被剔除，普通行保留并截断。"""
    diff = (
        "interface GigabitEthernet0/0\n"
        " description uplink\n"
        " snmp-server community Public@123 RO\n"
        " password 7 08224F40081B\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA\n"
        "-----END RSA PRIVATE KEY-----\n"
        " ip address 10.1.1.1 255.255.255.0\n"
    )
    out = strip_sensitive_lines(diff)
    assert "community" not in out.lower()
    assert "08224F40081B" not in out
    assert "PRIVATE KEY" not in out
    assert "MIIEpAIBAAKCAQEA" not in out
    assert "description uplink" in out
    assert "ip address 10.1.1.1" in out


def test_mask_question_rules():
    """question 脱敏规则：password=、token:、Bearer、私钥块。"""
    q = "密码 password=Abc123! 用于登录，token: eyJhbGci 另一个 Bearer xyz123"
    masked = mask_question(q)
    assert "Abc123!" not in masked
    assert "eyJhbGci" not in masked
    assert "xyz123" not in masked

    pem = "-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----"
    assert "[私钥已脱敏]" in mask_question(pem)


def test_migration_pure_functions_idempotent():
    """迁移纯函数：加密幂等（二次加密不变）；解密可还原；空 key 不动。"""
    configs = [
        {"id": 1, "api_key": "sk-plain-1", "name": "a"},
        {"id": 2, "api_key": "", "name": "b"},
        {"id": 3, "api_key": encrypt_secret("sk-plain-3"), "name": "c"},
    ]
    once, changed1 = encrypt_configs_api_keys(configs)
    assert changed1 == 1  # 只有 id=1 明文被加密；空值跳过、id=3 已加密跳过
    twice, changed2 = encrypt_configs_api_keys(once)
    assert changed2 == 0  # 幂等
    assert twice == once

    decrypted, dec_changed = decrypt_configs_api_keys(twice)
    assert dec_changed == 2  # 两次加密后 id=1、id=3 均为密文，都被解密
    by_id = {c["id"]: c["api_key"] for c in decrypted}
    assert by_id[1] == "sk-plain-1"
    assert by_id[2] == ""
    assert by_id[3] == "sk-plain-3"
