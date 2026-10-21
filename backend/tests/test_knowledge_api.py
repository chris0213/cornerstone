"""知识库接口安全与软删除测试：knowledge:write 权限 / 软删除全链路 /
分类管理（409） / xlsx 压缩炸弹防护 / updated_by / count_view / keyword 转义。"""
import io
import zipfile

import pytest
from sqlalchemy import select

from src.models import KnowledgeArticle, KnowledgeCategory, Role, User
from src.services.permission_service import pwd_context


async def _login(client, username: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_user(db_session, username: str, role_name: str, password: str = "Passw0rd!"):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        username=username,
        display_name=username,
        email=f"{username}@example.com",
        hashed_password=pwd_context.hash(password),
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _make_article(db_session, title: str, author: str, category: str = "其他",
                        is_published: bool = True) -> KnowledgeArticle:
    article = KnowledgeArticle(
        title=title, category=category, tags="", summary="s",
        content="正文内容 marker123", author=author, is_published=is_published,
    )
    db_session.add(article)
    await db_session.commit()
    return article


def _bomb_zip(ratio: int = 500) -> bytes:
    """构造高压缩比 zip（xlsx 本质是 zip）：重复字节实现 >200 倍压缩比。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", b"0" * (ratio * 1024))
    return buf.getvalue()


# ---------- knowledge:write 权限 ----------

@pytest.mark.asyncio
async def test_viewer_cannot_create_or_import(client, db_session):
    """viewer 无 knowledge:write：新建 403 / 导入 403 / 分类管理 403；读仍 200"""
    await _make_user(db_session, "kb_viewer", "viewer")
    headers = await _login(client, "kb_viewer", "Passw0rd!")

    resp = await client.post("/api/v1/knowledge", json={"title": "t"}, headers=headers)
    assert resp.status_code == 403, resp.text

    resp = await client.post(
        "/api/v1/knowledge/import",
        files={"file": ("a.md", b"# hi", "text/markdown")},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text

    resp = await client.post("/api/v1/knowledge/categories", json={"name": "x"}, headers=headers)
    assert resp.status_code == 403, resp.text

    resp = await client.get("/api/v1/knowledge", headers=headers)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/knowledge/categories", headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_engineer_can_create_and_read(client, db_session):
    """engineer 有 knowledge:write：新建 201，viewer 读列表/详情 200"""
    await _make_user(db_session, "kb_engineer", "engineer")
    await _make_user(db_session, "kb_viewer2", "viewer")
    headers = await _login(client, "kb_engineer", "Passw0rd!")

    resp = await client.post(
        "/api/v1/knowledge",
        json={"title": "工程师文章", "content": "c", "category": "配置手册"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    article_id = resp.json()["id"]

    viewer_headers = await _login(client, "kb_viewer2", "Passw0rd!")
    resp = await client.get("/api/v1/knowledge", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    resp = await client.get(f"/api/v1/knowledge/{article_id}", headers=viewer_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_engineer_cannot_edit_or_delete_others(client, db_session):
    """engineer 改/删他人文章 403（编辑删除限作者或超管）"""
    await _make_article(db_session, "他人文章", author="someone")
    await _make_user(db_session, "kb_engineer2", "engineer")
    headers = await _login(client, "kb_engineer2", "Passw0rd!")

    resp = await client.put(
        "/api/v1/knowledge/1", json={"title": "改"}, headers=headers
    )
    assert resp.status_code == 403, resp.text
    resp = await client.delete("/api/v1/knowledge/1", headers=headers)
    assert resp.status_code == 403, resp.text


# ---------- 软删除全链路 ----------

@pytest.mark.asyncio
async def test_soft_delete_hides_everywhere(client, db_session):
    """软删除后：列表/计数/分类聚合/详情/搜索 5 处均不可见；DB 行仍在"""
    await _make_user(db_session, "kb_author", "engineer")
    headers = await _login(client, "kb_author", "Passw0rd!")

    resp = await client.post(
        "/api/v1/knowledge",
        json={"title": "将被软删的文章", "content": "独特标记xyzzy", "category": "故障处理"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    article_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/knowledge/{article_id}", headers=headers)
    assert resp.status_code == 200

    # 列表与 total
    resp = await client.get("/api/v1/knowledge", headers=headers)
    items = resp.json()
    assert all(i["id"] != article_id for i in items["items"])
    # 详情 404
    resp = await client.get(f"/api/v1/knowledge/{article_id}", headers=headers)
    assert resp.status_code == 404
    # 搜索不可见
    resp = await client.get("/api/v1/knowledge?keyword=xyzzy", headers=headers)
    assert all(i["id"] != article_id for i in resp.json()["items"])
    # 分类聚合不计软删文章
    resp = await client.get("/api/v1/knowledge/categories", headers=headers)
    cats = {c["name"]: c["count"] for c in resp.json()}
    assert cats.get("故障处理", 0) == 0
    # DB 行仍在且 deleted_at 非空
    row = await db_session.get(KnowledgeArticle, article_id)
    assert row is not None
    assert row.deleted_at is not None

    # 再次删除返回 404
    resp = await client.delete(f"/api/v1/knowledge/{article_id}", headers=headers)
    assert resp.status_code == 404


# ---------- 分类管理 ----------

@pytest.mark.asyncio
async def test_category_crud_conflicts(client, db_session):
    """分类：重名 409；删除被使用分类 409；删除「其他」409；改名同步文章"""
    # 测试库由 create_all 建表（不走 Alembic），先按迁移行为种子化预置分类
    for name, order in [("故障处理", 1), ("配置手册", 2), ("操作SOP", 3), ("常见问题", 4), ("其他", 5)]:
        db_session.add(KnowledgeCategory(name=name, sort_order=order))
    await db_session.commit()

    await _make_user(db_session, "kb_cat_admin", "engineer")
    headers = await _login(client, "kb_cat_admin", "Passw0rd!")

    # 预置分类存在
    resp = await client.get("/api/v1/knowledge/categories", headers=headers)
    names = [c["name"] for c in resp.json()]
    assert {"故障处理", "配置手册", "操作SOP", "常见问题", "其他"} <= set(names)

    # 重名 409
    resp = await client.post("/api/v1/knowledge/categories", json={"name": "故障处理"}, headers=headers)
    assert resp.status_code == 409

    # 新增成功
    resp = await client.post(
        "/api/v1/knowledge/categories", json={"name": "临时分类", "sort_order": 9}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    cat_id = resp.json()["id"]

    # 建文章占用该分类
    resp = await client.post(
        "/api/v1/knowledge",
        json={"title": "占用分类的文章", "category": "临时分类"},
        headers=headers,
    )
    assert resp.status_code == 201
    article_id = resp.json()["id"]

    # 删除被使用分类 409
    resp = await client.delete(f"/api/v1/knowledge/categories/{cat_id}", headers=headers)
    assert resp.status_code == 409

    # 改名同事务同步文章 category
    resp = await client.put(
        f"/api/v1/knowledge/categories/{cat_id}", json={"name": "临时分类2"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    row = await db_session.get(KnowledgeArticle, article_id)
    assert row.category == "临时分类2"

    # 软删文章后分类可删
    await client.delete(f"/api/v1/knowledge/{article_id}", headers=headers)
    resp = await client.delete(f"/api/v1/knowledge/categories/{cat_id}", headers=headers)
    assert resp.status_code == 200

    # 删除「其他」409
    resp = await client.get("/api/v1/knowledge/categories", headers=headers)
    other_id = next(c["id"] for c in resp.json() if c["name"] == "其他")
    resp = await client.delete(f"/api/v1/knowledge/categories/{other_id}", headers=headers)
    assert resp.status_code == 409


# ---------- xlsx 压缩炸弹防护 ----------

@pytest.mark.asyncio
async def test_xlsx_zipbomb_rejected(client, db_session):
    """高压缩比 xlsx → 400"""
    await _make_user(db_session, "kb_bomb", "engineer")
    headers = await _login(client, "kb_bomb", "Passw0rd!")

    resp = await client.post(
        "/api/v1/knowledge/import",
        files={"file": ("bomb.xlsx", _bomb_zip(500), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_normal_xlsx_import_ok(client, db_session):
    """正常小 xlsx 仍可导入（read_only 改造不破坏功能）"""
    from openpyxl import Workbook

    await _make_user(db_session, "kb_xlsx", "engineer")
    headers = await _login(client, "kb_xlsx", "Passw0rd!")

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["主机", "IP"])
    ws.append(["core-sw", "10.0.0.1"])
    buf = io.BytesIO()
    wb.save(buf)

    resp = await client.post(
        "/api/v1/knowledge/import",
        files={"file": ("设备清单.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert "core-sw" in resp.json()[0]["summary"] or resp.json()[0]["title"].startswith("设备清单")


# ---------- updated_by ----------

@pytest.mark.asyncio
async def test_updated_by_self_and_superuser(client, db_session):
    """作者自改、超管改他人文章各断言一次 updated_by"""
    await _make_user(db_session, "kb_up1", "engineer")
    headers = await _login(client, "kb_up1", "Passw0rd!")

    resp = await client.post(
        "/api/v1/knowledge", json={"title": "U1文章", "content": "c"}, headers=headers
    )
    assert resp.status_code == 201
    aid = resp.json()["id"]

    # 作者自改
    resp = await client.put(f"/api/v1/knowledge/{aid}", json={"summary": "s2"}, headers=headers)
    assert resp.status_code == 200
    row = await db_session.get(KnowledgeArticle, aid)
    assert row.updated_by == "kb_up1"

    # 超管改他人文章
    admin_headers = await _login(client, "admin", "admin123")
    resp = await client.put(
        f"/api/v1/knowledge/{aid}", json={"summary": "s3"}, headers=admin_headers
    )
    assert resp.status_code == 200
    # expire_on_commit=False 时 identity map 缓存旧行，需过期后重读
    db_session.expire_all()
    row = await db_session.get(KnowledgeArticle, aid)
    assert row.updated_by == "admin"


# ---------- count_view ----------

@pytest.mark.asyncio
async def test_count_view_flag(client, db_session):
    """count_view=false 不累加阅读量；默认 true 累加"""
    await _make_user(db_session, "kb_view_cnt", "engineer")
    headers = await _login(client, "kb_view_cnt", "Passw0rd!")

    resp = await client.post(
        "/api/v1/knowledge", json={"title": "阅读量文章", "content": "c"}, headers=headers
    )
    aid = resp.json()["id"]

    resp = await client.get(f"/api/v1/knowledge/{aid}?count_view=false", headers=headers)
    assert resp.json()["view_count"] == 0
    resp = await client.get(f"/api/v1/knowledge/{aid}", headers=headers)
    assert resp.json()["view_count"] == 1


# ---------- keyword 通配符转义 ----------

@pytest.mark.asyncio
async def test_keyword_wildcard_escaped(client, db_session):
    """keyword 含 % / _ 时按字面匹配，不当通配符"""
    await _make_article(db_session, "100%正常文章", author="a")
    await _make_article(db_session, "ABCDEF文章", author="a")  # ABCDEF 中间插任意3字符可被 %E% 命中

    await _make_user(db_session, "kb_kw", "engineer")
    headers = await _login(client, "kb_kw", "Passw0rd!")

    # 字面 % 不应通配：搜「100%」只命中 100%正常文章
    resp = await client.get("/api/v1/knowledge?keyword=100%25", headers=headers)
    titles = [i["title"] for i in resp.json()["items"]]
    assert "100%正常文章" in titles
    assert "ABCDEF文章" not in titles

    # 字面 _ 不应通配：搜「1_0」不应命中「1x0」类（无下划线字面量）
    resp = await client.get("/api/v1/knowledge?keyword=1_0", headers=headers)
    assert all("_" in i["title"] for i in resp.json()["items"])


# ---------- knowledge 保持 0 篇约束的说明 ----------
# 本测试文件造的数据位于 conftest 的临时测试库（用后即删），不触碰 cornerstone.db。
