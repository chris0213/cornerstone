"""知识库 API（运维经验沉淀：故障处理 / 配置手册 / 操作 SOP / FAQ）

读：登录用户即可查看；写：登录用户即可创建/编辑（知识库定位为团队协作沉淀）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import KnowledgeArticle, User
from .auth import get_current_active_user
from .dependencies import PageParams, pagination

router = APIRouter()


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
    """文章列表（按更新时间倒序；category/keyword 筛选；不含正文）"""
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
    query = query.order_by(KnowledgeArticle.updated_at.desc()).offset(page.skip).limit(page.limit)
    rows = (await db.execute(query)).scalars().all()
    return [_article_brief(a) for a in rows]


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
    return _article_brief(article)


@router.put("/{article_id}")
async def update_article(
    article_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """更新文章"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识库文章不存在")

    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="标题不能为空")
        if len(title) > 200:
            raise HTTPException(status_code=400, detail="标题最长 200 字")
        article.title = title
    if "category" in payload:
        article.category = str(payload.get("category") or "其他").strip()
    if "tags" in payload:
        article.tags = str(payload.get("tags") or "").strip()
    if "summary" in payload:
        article.summary = str(payload.get("summary") or "").strip()[:500]
    if "content" in payload:
        article.content = str(payload.get("content") or "")
    if "is_published" in payload:
        article.is_published = bool(payload.get("is_published"))

    await db.commit()
    await db.refresh(article)
    return _article_brief(article)


@router.delete("/{article_id}")
async def delete_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """删除文章"""
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识库文章不存在")
    await db.delete(article)
    await db.commit()
    return {"message": "删除成功"}
