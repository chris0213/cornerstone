"""知识库 API（运维经验沉淀：故障处理 / 配置手册 / 操作 SOP / FAQ）

读：登录用户即可查看；写：登录用户即可创建/编辑（知识库定位为团队协作沉淀）；
删除仅限作者本人或超级管理员。写操作（增/改/删/导入）落审计日志。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import KnowledgeArticle, User
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.logger import audit_log
from .dependencies import PageParams, pagination
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
    """文章列表（按更新时间倒序；category/keyword 筛选；不含正文；返回 items + total）"""
    query = select(KnowledgeArticle)
    if category:
        query = query.where(KnowledgeArticle.category == category)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(or_(
            KnowledgeArticle.title.ilike(like),
            KnowledgeArticle.summary.ilike(like),
            KnowledgeArticle.tags.ilike(like),
            KnowledgeArticle.content.ilike(like),
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
    """分类列表及文章数（侧栏分组用）"""
    rows = (await db.execute(
        select(KnowledgeArticle.category, func.count(KnowledgeArticle.id))
        .group_by(KnowledgeArticle.category)
    )).all()
    return [{"category": r[0] or "其他", "count": r[1]} for r in rows]


@router.get("/{article_id}")
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """文章详情（阅读量 +1）"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识库文章不存在")
    article.view_count = (article.view_count or 0) + 1
    await db.commit()
    # 显式 refresh：同 session 前置用户查询 + commit 后对象属性可能未加载，
    # 直接读会触发同步 lazy load（async 下抛 MissingGreenlet）
    await db.refresh(article)
    data = _article_brief(article)
    data["content"] = article.content or ""
    return data


@router.post("")
async def create_article(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """创建文章"""
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
    """更新文章（仅作者本人或超级管理员）"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
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
    current_user: User = Depends(get_current_active_user),
):
    """导入文档为知识库文章（.md/.txt 原文、.docx 还原排版、.xlsx 每个工作表一篇独立文章）"""
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
    """删除文章（仅作者本人或超级管理员）"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识库文章不存在")
    if not current_user.is_superuser and article.author != current_user.username:
        raise HTTPException(status_code=403, detail="仅作者本人或超级管理员可删除")
    title = article.title
    await db.delete(article)
    await db.commit()
    await audit_log(
        db, current_user.id, "knowledge", article_id, "delete",
        {"title": title},
        get_client_ip_from_request(request)
    )
    return {"message": "删除成功"}
