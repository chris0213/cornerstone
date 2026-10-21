"""知识库 API（运维经验沉淀：故障处理 / 配置手册 / 操作 SOP / FAQ）

读：登录用户即可查看；新建/导入/分类管理需 knowledge:write 权限；
编辑/删除仅限作者本人或超级管理员。删除为软删除（deleted_at）。
写操作（增/改/删/导入/分类增改删）落审计日志。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import KnowledgeArticle, KnowledgeCategory, User
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.logger import audit_log
from .dependencies import PageParams, pagination, require_permission
from .auth import get_current_active_user

router = APIRouter()


def stem_of(filename: str, exts: tuple) -> str:
    """文件名去掉扩展名（用于生成文章标题）"""
    stem = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for ext in exts:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    return stem


def _escape_like(keyword: str) -> str:
    """转义 LIKE 通配符，避免用户输入 %/_ 被当作模式"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _alive(query):
    """过滤软删除文章"""
    return query.where(KnowledgeArticle.deleted_at.is_(None))


def _article_brief(a: KnowledgeArticle) -> dict:
    """列表用精简结构（不含正文）"""
    return {
        "id": a.id,
        "title": a.title,
        "category": a.category or "其他",
        "tags": a.tags or "",
        "summary": a.summary or "",
        "author": a.author or "",
        "is_published": a.is_published,
        "view_count": a.view_count or 0,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


@router.get("")
async def list_articles(
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """文章列表（按更新时间倒序；category/keyword 筛选；不含正文；返回 items + total；不含软删除）"""
    query = _alive(select(KnowledgeArticle))
    if category:
        query = query.where(KnowledgeArticle.category == category)
    if keyword:
        like = f"%{_escape_like(keyword)}%"
        query = query.where(or_(
            KnowledgeArticle.title.ilike(like, escape="\\"),
            KnowledgeArticle.summary.ilike(like, escape="\\"),
            KnowledgeArticle.tags.ilike(like, escape="\\"),
            KnowledgeArticle.content.ilike(like, escape="\\"),
        ))
    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0
    query = query.order_by(KnowledgeArticle.updated_at.desc()).offset(page.skip).limit(page.limit)
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_article_brief(a) for a in rows], "total": total}


@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """分类列表及文章数（侧栏分组用；按 sort_order 排序；含 0 篇分类；不含软删除）"""
    counts = dict((await db.execute(
        select(KnowledgeArticle.category, func.count(KnowledgeArticle.id))
        .where(KnowledgeArticle.deleted_at.is_(None))
        .group_by(KnowledgeArticle.category)
    )).all())
    rows = (await db.execute(
        select(KnowledgeCategory).order_by(KnowledgeCategory.sort_order, KnowledgeCategory.id)
    )).scalars().all()
    return [
        {"id": c.id, "name": c.name, "description": c.description or "",
         "sort_order": c.sort_order, "count": counts.get(c.name, 0)}
        for c in rows
    ]


def _category_brief(c: KnowledgeCategory) -> dict:
    return {
        "id": c.id, "name": c.name, "description": c.description or "",
        "sort_order": c.sort_order, "created_at": c.created_at,
    }


async def _category_name_taken(db: AsyncSession, name: str, exclude_id: Optional[int] = None) -> bool:
    query = select(KnowledgeCategory).where(KnowledgeCategory.name == name)
    if exclude_id is not None:
        query = query.where(KnowledgeCategory.id != exclude_id)
    return (await db.execute(query)).scalars().first() is not None


@router.post("/categories")
async def create_category(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:write")),
):
    """新增分类（需 knowledge:write；name 查重 409）"""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="分类名最长 50 字")
    if await _category_name_taken(db, name):
        raise HTTPException(status_code=409, detail="分类名已存在")
    category = KnowledgeCategory(
        name=name,
        description=str(payload.get("description") or "").strip()[:200],
        sort_order=int(payload.get("sort_order") or 0),
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    await audit_log(
        db, current_user.id, "knowledge_category", category.id, "create",
        {"name": category.name},
        get_client_ip_from_request(request)
    )
    return _category_brief(category)


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:write")),
):
    """编辑分类（需 knowledge:write；改名查重 409；「其他」不可改名；同事务同步文章 category）"""
    category = await db.get(KnowledgeCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    if category.name == "其他":
        raise HTTPException(status_code=409, detail="默认分类「其他」不可修改")

    new_name = str(payload.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(new_name) > 50:
        raise HTTPException(status_code=400, detail="分类名最长 50 字")
    if new_name != category.name and await _category_name_taken(db, new_name, exclude_id=category_id):
        raise HTTPException(status_code=409, detail="分类名已存在")

    old_name = category.name
    if "description" in payload:
        category.description = str(payload.get("description") or "").strip()[:200]
    if new_name != old_name:
        category.name = new_name
        # 同一事务内同步存量文章的分类名，不丢值
        articles = (await db.execute(
            select(KnowledgeArticle).where(KnowledgeArticle.category == old_name)
        )).scalars().all()
        for a in articles:
            a.category = new_name
    await db.commit()
    await db.refresh(category)
    await audit_log(
        db, current_user.id, "knowledge_category", category.id, "update",
        {"name": category.name, "old_name": old_name},
        get_client_ip_from_request(request)
    )
    return _category_brief(category)


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:write")),
):
    """删除分类（需 knowledge:write；「其他」与仍有文章的分类返回 409）"""
    category = await db.get(KnowledgeCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    if category.name == "其他":
        raise HTTPException(status_code=409, detail="默认分类「其他」不可删除")
    in_use = (await db.execute(
        select(func.count(KnowledgeArticle.id)).where(
            KnowledgeArticle.category == category.name,
            KnowledgeArticle.deleted_at.is_(None),
        )
    )).scalar() or 0
    if in_use:
        raise HTTPException(status_code=409, detail=f"该分类下仍有 {in_use} 篇文章，无法删除")
    name = category.name
    await db.delete(category)
    await db.commit()
    await audit_log(
        db, current_user.id, "knowledge_category", category_id, "delete",
        {"name": name},
        get_client_ip_from_request(request)
    )
    return {"message": "删除成功"}


@router.get("/{article_id}")
async def get_article(
    article_id: int,
    count_view: bool = Query(True, description="是否累加阅读量（编辑回读传 false）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """文章详情（默认阅读量 +1；count_view=false 跳过；软删除返回 404）"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article or article.deleted_at is not None:
        raise HTTPException(status_code=404, detail="知识库文章不存在")
    if count_view:
        article.view_count = (article.view_count or 0) + 1
        await db.commit()
        # 显式 refresh：同 session 前置用户查询 + commit 后对象属性可能未加载，
        # 直接读会触发同步 lazy load（async 下抛 MissingGreenlet）
        await db.refresh(article)
    data = _article_brief(article)
    data["content"] = article.content or ""
    return data


@router.post("", status_code=201)
async def create_article(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:write")),
):
    """创建文章（需 knowledge:write）"""
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="标题最长 200 字")

    article = KnowledgeArticle(
        title=title,
        category=str(payload.get("category") or "其他").strip(),
        tags=str(payload.get("tags") or "").strip(),
        summary=str(payload.get("summary") or "").strip()[:500],
        content=str(payload.get("content") or ""),
        author=current_user.username,
        is_published=bool(payload.get("is_published", True)),
    )
    db.add(article)
    await db.commit()
    await db.refresh(article)
    await audit_log(
        db, current_user.id, "knowledge", article.id, "create",
        {"title": article.title, "category": article.category},
        get_client_ip_from_request(request)
    )
    return _article_brief(article)


@router.put("/{article_id}")
async def update_article(
    article_id: int,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """更新文章（仅作者本人或超级管理员；记录最后修改人）"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article or article.deleted_at is not None:
        raise HTTPException(status_code=404, detail="知识库文章不存在")
    if not current_user.is_superuser and article.author != current_user.username:
        raise HTTPException(status_code=403, detail="仅作者本人或超级管理员可编辑")

    changed = []
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="标题不能为空")
        if len(title) > 200:
            raise HTTPException(status_code=400, detail="标题最长 200 字")
        article.title = title
        changed.append("title")
    if "category" in payload:
        article.category = str(payload.get("category") or "其他").strip()
        changed.append("category")
    if "tags" in payload:
        article.tags = str(payload.get("tags") or "").strip()
        changed.append("tags")
    if "summary" in payload:
        article.summary = str(payload.get("summary") or "").strip()[:500]
        changed.append("summary")
    if "content" in payload:
        article.content = str(payload.get("content") or "")
        changed.append("content")
    if "is_published" in payload:
        article.is_published = bool(payload.get("is_published"))
        changed.append("is_published")

    if changed:
        article.updated_by = current_user.username

    await db.commit()
    await db.refresh(article)
    await audit_log(
        db, current_user.id, "knowledge", article.id, "update",
        {"title": article.title, "fields": changed},
        get_client_ip_from_request(request)
    )
    return _article_brief(article)


MAX_IMPORT_SIZE = 5 * 1024 * 1024  # 导入文件上限 5MB
ALLOWED_IMPORT_EXT = (".md", ".markdown", ".txt", ".docx", ".xlsx", ".xlsm")


@router.post("/import")
async def import_article(
    request: Request,
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("knowledge:write")),
):
    """导入文档为知识库文章（需 knowledge:write；.md/.txt 原文、.docx 还原排版、.xlsx 每个工作表一篇独立文章）"""
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_IMPORT_EXT):
        raise HTTPException(status_code=400, detail=f"仅支持 {', '.join(ALLOWED_IMPORT_EXT)} 格式")
    raw = await file.read()
    if len(raw) > MAX_IMPORT_SIZE:
        raise HTTPException(status_code=400, detail="文件不能超过 5MB")

    stem = stem_of(filename, ALLOWED_IMPORT_EXT)
    from src.services.knowledge_import import import_text_to_markdown, derive_article_fields, xlsx_sheets_to_markdown
    try:
        if filename.lower().endswith((".xlsx", ".xlsm")):
            # 每个工作表独立成篇，避免多表拼一篇文章排版混乱
            sheets = xlsx_sheets_to_markdown(raw)
            multi = len(sheets) > 1
            # 单表直接用文件名（Sheet1 等默认表名无意义）；多表标题加表名后缀便于区分
            contents = [(f"{stem}（{sheet_name}）" if multi else stem, md) for sheet_name, md in sheets]
        else:
            contents = [(stem, import_text_to_markdown(filename, raw))]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文档解析失败：{e}")
    if not any(md.strip() for _, md in contents):
        raise HTTPException(status_code=400, detail="文档内容为空")

    articles = []
    for sheet_title, content in contents:
        if not content.strip():
            continue
        _, summary = derive_article_fields("", content)
        article = KnowledgeArticle(
            title=(sheet_title or stem)[:200] or "未命名导入",
            category=str(category or "其他").strip(),
            tags="",
            summary=summary[:500],
            content=content,
            author=current_user.username,
            is_published=False,  # 导入默认草稿，人工确认后再发布
        )
        db.add(article)
        articles.append(article)
    await db.commit()
    results = []
    for article in articles:
        await db.refresh(article)
        await audit_log(
            db, current_user.id, "knowledge", article.id, "import",
            {"title": article.title, "category": article.category},
            get_client_ip_from_request(request)
        )
        results.append(_article_brief(article))
    return results


@router.delete("/{article_id}")
async def delete_article(
    article_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """删除文章（软删除；仅作者本人或超级管理员）"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article or article.deleted_at is not None:
        raise HTTPException(status_code=404, detail="知识库文章不存在")
    if not current_user.is_superuser and article.author != current_user.username:
        raise HTTPException(status_code=403, detail="仅作者本人或超级管理员可删除")
    title = article.title
    article.deleted_at = func.now()
    await db.commit()
    await audit_log(
        db, current_user.id, "knowledge", article_id, "delete",
        {"title": title},
        get_client_ip_from_request(request)
    )
    return {"message": "删除成功"}
