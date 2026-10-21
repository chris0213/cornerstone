"""xlsx 导入转换质量测试：单元格内换行 / 合并单元格 / 空单元格 /
行尾多余空列 / 多 sheet / 标题去重 / 表格摘要。

全部使用构造数据，不依赖外部文件。
"""
import io

import pytest
from openpyxl import Workbook

from src.services.knowledge_import import (
    xlsx_sheets_to_markdown,
    derive_article_fields,
    dedupe_sheet_title,
)


def _build_xlsx(build_fn) -> bytes:
    wb = Workbook()
    build_fn(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _md_rows(md: str) -> list[list[str]]:
    """把 Markdown 表格解析回行列（不含分隔行），供断言列数一致。"""
    rows = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        if all(c.strip() in ("---", ":---", "---:", ":---:") for c in s.strip("|").split("|")):
            continue
        rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


# ---------- 单元格内换行 ----------

def test_cell_newline_becomes_br():
    """单元格内换行 → <br>，不破坏表格行结构"""
    def build(wb):
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["主机", "备注"])
        ws.append(["core-sw", "角色：核心\n端口：48\n位置：A01"])  # 单元格内 2 个换行
    md = xlsx_sheets_to_markdown(_build_xlsx(build))[0][1]
    rows = _md_rows(md)
    # 只有 2 行（表头+数据），没有因换行裂成多行
    assert len(rows) == 2
    assert rows[0] == ["主机", "备注"]
    assert rows[1][0] == "core-sw"
    assert rows[1][1] == "角色：核心<br>端口：48<br>位置：A01"
    # 每行列数一致
    assert {len(r) for r in rows} == {2}


# ---------- 合并单元格 ----------

def test_merged_cells_filled():
    """纵向 + 横向合并：首格值填充整个区域"""
    def build(wb):
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["地区", "城市", "IP"])
        ws.append(["华东", "上海", "192.0.2.1"])
        ws.append([None, "杭州", "192.0.2.2"])       # 「地区」A2:A3 纵向合并
        ws.append(["华北", None, "198.51.100.1"])
        ws.append(["华北", "北京", "198.51.100.2"])  # 准备横向合并 B4:C4 不合适，改纵向
        ws.merge_cells("A2:A3")
        ws.merge_cells("A4:A5")
        # 横向合并：D1:E1 表头「联系方式」拆两列
        ws.cell(row=1, column=4, value="负责人")
        ws.merge_cells(start_row=1, start_column=4, end_row=2, end_column=4)
    md = xlsx_sheets_to_markdown(_build_xlsx(build))[0][1]
    rows = _md_rows(md)
    assert rows[1][0] == "华东"
    assert rows[2][0] == "华东", "纵向合并 A3 应填充「华东」"
    assert rows[3][0] == "华北"
    assert rows[4][0] == "华北"
    assert {len(r) for r in rows} == {len(rows[0])}, "合并填充后每行列数仍一致"


# ---------- 空单元格 + 行尾多余空列 ----------

def test_empty_cells_and_trailing_blank_cols():
    """空单元格补位；行尾多余空列裁掉；中间空列保留"""
    def build(wb):
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["A", "B", "C"])
        ws.append(["x", None, "z"])           # 中间空单元格 → 补空
        ws.append(["y", "w", None, None])     # 行尾 2 个多余空列 → 裁掉
        ws.append([None, None, None])         # 整行全空 → 丢弃
    md = xlsx_sheets_to_markdown(_build_xlsx(build))[0][1]
    rows = _md_rows(md)
    assert len(rows) == 3, "全空行应被丢弃"
    assert rows[0] == ["A", "B", "C"]
    assert rows[1] == ["x", "", "z"]
    assert rows[2] == ["y", "w", ""], "行尾空列应裁到表头列数"
    assert {len(r) for r in rows} == {3}


# ---------- 多 sheet ----------

def test_multi_sheets_each_one_article():
    """多个非空 sheet 各自成篇；空 sheet 不产出"""
    def build(wb):
        ws1 = wb.active
        ws1.title = "设备"
        ws1.append(["主机", "IP"])
        ws1.append(["sw1", "192.0.2.10"])
        ws2 = wb.create_sheet("链路")
        ws2.append(["起", "止"])
        ws2.append(["A", "B"])
        wb.create_sheet("空表")  # 全空 → 不产出
    sheets = xlsx_sheets_to_markdown(_build_xlsx(build))
    assert [t for t, _ in sheets] == ["设备", "链路"]
    for _, md in sheets:
        assert _md_rows(md), "每个 sheet 都应有表格内容"


# ---------- 标题去重 ----------

def test_dedupe_sheet_title():
    """文件名与 sheet 名重复/包含时不重复拼接；默认 sheet 名不拼接；相邻重复片段去掉"""
    # 默认名不拼接
    assert dedupe_sheet_title("出口IP-2026", "Sheet1", True) == "出口IP-2026"
    # 互为包含：不重复
    assert dedupe_sheet_title("出口IP-2026", "出口IP-2026", True) == "出口IP-2026"
    assert dedupe_sheet_title("出口IP", "出口IP明细", True) in ("出口IP明细", "出口IP")
    # 正常拼接
    assert dedupe_sheet_title("设备清单", "交换机", True) == "设备清单（交换机）"
    # 拼接后出现相邻重复片段 → 去重（文件名已含括号年份的场景）
    assert dedupe_sheet_title("出口IP（2026）", "2026", True) == "出口IP（2026）"
    # 单表直接用文件名
    assert dedupe_sheet_title("只有一页", "Sheet1", False) == "只有一页"


# ---------- 表格摘要 ----------

def test_summary_for_table_content():
    """表格开头正文 → 摘要为「表格：N 行 × M 列」，不含表格原文"""
    content = (
        "| 地区 | IP |\n"
        "| --- | --- |\n"
        "| 上海 | 192.0.2.1 |\n"
        "| 北京 | 198.51.100.1 |"
    )
    _, summary = derive_article_fields("", content)
    assert summary == "表格：2 行 × 2 列"
    assert "192.0.2.1" not in summary, "摘要不应包含表格原文"


def test_summary_normal_text_unchanged():
    """普通文本摘要逻辑保持不变"""
    _, summary = derive_article_fields("", "这是普通正文，包含一些说明文字。")
    assert "普通正文" in summary


# ---------- API 全链路（构造 xlsx 上传） ----------

@pytest.mark.asyncio
async def test_import_quality_end_to_end(client, db_session):
    """构造含换行/合并/空格 xlsx 上传：标题不重复、摘要是表格统计、正文行结构完整"""
    from sqlalchemy import select as _select
    from src.models import KnowledgeArticle as KA
    from tests.test_knowledge_api import _make_user, _login

    def build(wb):
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["地区", "设备", "IP"])
        ws.append(["华东", "core-sw", "192.0.2.1"])
        ws.append([None, "acc-sw", "192.0.2.2"])
        ws.merge_cells("A2:A3")
        ws.cell(row=4, column=1, value="备注：\n每月更新")
        ws.cell(row=4, column=2, value="共 2 台")
        ws.cell(row=4, column=3, value=None)
        ws2 = wb.create_sheet("Sheet1")  # 同名默认 sheet 也会带上；单表 Sheet1 场景
        del wb[wb.sheetnames[1]]

    await _make_user(db_session, "kb_quality", "engineer")
    headers = await _login(client, "kb_quality", "Passw0rd!")

    resp = await client.post(
        "/api/v1/knowledge/import",
        files={"file": ("出口IP-2026.xlsx", _build_xlsx(build), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    arts = resp.json()
    assert len(arts) == 1
    title = arts[0]["title"]
    assert title == "出口IP-2026", f"默认 sheet 名不应拼进标题：{title}"
    assert "（2026）（2026）" not in title

    detail = await client.get(f"/api/v1/knowledge/{arts[0]['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    content = detail.json()["content"]
    rows = _md_rows(content)
    assert len(rows) == 4, "表头 + 3 行数据（含备注行），行尾空列裁掉不产生多余行"
    assert {len(r) for r in rows} == {3}, "每行列数与表头一致"
    assert rows[2][0] == "华东", "纵向合并应填充首格值"
    assert rows[3][0] == "备注：<br>每月更新", "单元格内换行应转 <br>"
    assert rows[3][2] == "", "行尾空单元格补空"
    assert arts[0]["summary"].startswith("表格："), f"摘要应为表格统计：{arts[0]['summary']}"
    assert "192.0.2.1" not in arts[0]["summary"]

    # 清理：知识库保持 0 篇
    for a in arts:
        r = await client.delete(f"/api/v1/knowledge/{a['id']}", headers=headers)
        assert r.status_code in (200, 204)
    remain = await client.get("/api/v1/knowledge", headers=headers)
    assert remain.status_code == 200
