"""知识库导入：文档 → Markdown 转换

支持 .md/.markdown（原文）、.txt（原文）、.docx（python-docx 解析并还原排版）、
.xlsx/.xlsm（openpyxl 解析，每个工作表转一个 Markdown 表格）。
docx 排版还原规则：
- Heading 1-6 → # ~ ######
- List Bullet / List Number → - / 1.（多级缩进保留）
- 表格 → Markdown 表格（首行作为表头）
- 连续等宽字体段落（Courier/Consolas/等宽）→ ``` 代码块
- 粗体/斜体 run → **加粗** / *斜体*
- 内嵌图片 → [图片] 占位符（正文无法承载图片）
xlsx 还原规则：
- 首个非空行作为表头，全空行/全空列剔除
- 多个工作表 → 每个表前加 `## 工作表名` 分节
- 日期单元格无时分秒时只显示日期
"""
import io
import re
from datetime import date, datetime
from typing import Optional

MONO_FONTS = {"courier new", "consolas", "menlo", "monaco", "sf mono", "source code pro", "lucida console"}


def import_text_to_markdown(filename: str, raw: bytes) -> str:
    """按扩展名选择解析器，返回 Markdown 正文"""
    name = (filename or "").lower()
    if name.endswith(".docx"):
        return docx_to_markdown(raw)
    if name.endswith((".xlsx", ".xlsm")):
        return xlsx_to_markdown(raw)
    # md / txt / 其他：按 UTF-8 解码（容忍 BOM 与轻微乱码）
    return raw.decode("utf-8-sig", errors="replace").strip()


def _run_text(run) -> str:
    """单个 run → Markdown 内联标记（粗体/斜体/等宽），图片替换占位"""
    text = run.text or ""
    if not text.strip():
        # 纯图片/空白 run：若含图片则给占位
        if getattr(run, "_element", None) is not None and run._element.findall(
                ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
            return " [图片] "
        return text

    is_code = bool(run.font.name) and run.font.name.strip().lower() in MONO_FONTS
    if run.bold and run.italic:
        return f"***{text}***"
    if run.bold:
        return f"**{text}**"
    if run.italic:
        return f"*{text}*"
    if is_code:
        return f"`{text}`"
    return text


def _paragraph_text(p) -> str:
    """段落内 inline 拼接"""
    parts = []
    for run in p.runs:
        parts.append(_run_text(run))
    # 无 runs 但含图片的情况
    body_xml = p._element.xml if hasattr(p._element, "xml") else ""
    text = "".join(parts)
    if not text.strip() and "blip" in body_xml:
        return "[图片]"
    return text


def _list_level(p) -> int:
    """列表缩进层级（style 名或 left_indent 推断），0 起"""
    style = (p.style.name if p.style is not None else "") or ""
    m = re.search(r"(?:Bullet|Number|List)\s*(\d+)$", style)
    if m:
        return int(m.group(1)) - 1
    if p.paragraph_format.left_indent:
        return max(0, int(p.paragraph_format.left_indent.pt // 18))
    return 0


def _is_mono_paragraph(p) -> bool:
    """整段等宽字体 → 代码块候选"""
    runs = [r for r in p.runs if (r.text or "").strip()]
    if not runs:
        return False
    return all(
        r.font.name and r.font.name.strip().lower() in MONO_FONTS
        for r in runs
    )


def _table_to_markdown(table) -> str:
    """docx 表格 → Markdown 表格（单元格内换行压成空格）"""
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cell_text = " / ".join(
                _paragraph_text(p).strip() for p in cell.paragraphs if _paragraph_text(p).strip()
            )
            cells.append(cell_text.replace("|", "\\|"))
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header, body_rows = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body_rows]
    return "\n".join(lines)


def docx_to_markdown(raw: bytes) -> str:
    """docx → Markdown（按 body 顺序遍历段落与表格，还原标题/列表/表格/代码块）"""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(raw))
    out: list[str] = []
    mono_buffer: list[str] = []  # 连续等宽段落 → 代码块

    def flush_mono():
        if mono_buffer:
            out.append("```\n" + "\n".join(mono_buffer) + "\n```")
            mono_buffer.clear()

    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            p = Paragraph(child, document)
            text = _paragraph_text(p).strip()

            if _is_mono_paragraph(p):
                # 代码块用纯文本，不叠加 inline 反引号
                mono_buffer.append(p.text.rstrip())
                continue
            flush_mono()

            if not text:
                if out and out[-1] != "":
                    out.append("")
                continue

            style = (p.style.name if p.style is not None else "") or ""
            heading = re.match(r"Heading\s*(\d)", style, re.IGNORECASE)
            if heading:
                level = min(int(heading.group(1)), 6)
                out.append("#" * level + " " + text)
            elif "List Bullet" in style or style.startswith("List Bullet"):
                out.append("  " * _list_level(p) + "- " + text)
            elif "List Number" in style or style.startswith("List Number"):
                out.append("  " * _list_level(p) + "1. " + text)
            elif "Quote" in style or "Intense Quote" in style:
                out.append("> " + text)
            else:
                out.append(text)
        elif child.tag.endswith("}tbl"):
            flush_mono()
            table = Table(child, document)
            md = _table_to_markdown(table)
            if md:
                out.append(md)

    flush_mono()
    # 压缩连续空行，收尾去空白
    result: list[str] = []
    for line in out:
        if line == "" and (not result or result[-1] == ""):
            continue
        result.append(line)
    return "\n".join(result).strip()


def _cell_to_text(value) -> str:
    """xlsx 单元格值 → 文本（日期只显示到日；None/公式缓存缺失给空串）"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M") if (value.hour or value.minute or value.second) else value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sheet_to_markdown(rows: list[list]) -> str:
    """工作表二维数据 → Markdown 表格（剔除全空行列，首个非空行作表头）"""
    grid = [[_cell_to_text(v) for v in row] for row in rows]
    # 剔除全空行
    grid = [r for r in grid if any(c.strip() for c in r)]
    if not grid:
        return ""
    # 剔除全空列
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    keep = [j for j in range(width) if any(r[j].strip() for r in grid)]
    grid = [[r[j] for j in keep] for r in grid]
    if not grid:
        return ""
    width = len(grid[0])

    header, body = grid[0], grid[1:]
    lines = [
        "| " + " | ".join(c.replace("|", "\\|") for c in header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in body]
    return "\n".join(lines)


def xlsx_to_markdown(raw: bytes) -> str:
    """xlsx/xlsm → Markdown：每个工作表转一个表格，多表用 `## 工作表名` 分节"""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        sheets = [ws for ws in wb.worksheets if ws.max_row]  # 跳过无数据工作表
        if not sheets:
            return ""
        # 单表且无意义表名（Sheet1 等）：不加分节标题
        multi = len(sheets) > 1
        out: list[str] = []
        for ws in sheets:
            md = _sheet_to_markdown(list(ws.iter_rows(values_only=True)))
            if not md:
                continue
            if multi:
                if out:
                    out.append("")
                out.append(f"## {ws.title}")
            out.append(md)
        return "\n".join(out).strip()
    finally:
        wb.close()


def derive_article_fields(title: str, content: str) -> tuple[str, str]:
    """从正文推导标题/摘要（导入时未显式提供时使用）"""
    final_title = (title or "").strip()
    body = content or ""
    if not final_title:
        # 首个 H1 作为标题
        for line in body.splitlines():
            if line.startswith("# "):
                final_title = line[2:].strip()
                body = "\n".join(body.splitlines()[1:]).strip()
                break
    summary = re.sub(r"[#*`>\[\]|-]", "", body)[:200].strip().replace("\n", " ")
    return final_title, summary
