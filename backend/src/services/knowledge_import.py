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
- 公式单元格优先取缓存计算结果；无缓存（非 Excel 原生保存的系统导出文件
  不写公式缓存值）时解析引用兜底：纯引用取值、函数公式拼接引用值与引号
  常量、ROW() 换算行号，仍无法解析则显示公式文本
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


# 公式解析用正则：字符串常量 / 单元格引用（可带表名前缀与范围）
_TOKEN_RE = re.compile(
    r'"[^"]*"'
    r"|(?:(?P<sheet>'[^']+'|[^'!=+\-*/&(),\s]+)!)?"
    r"(?P<col>\$?[A-Z]{1,3})\$?(?P<row>\d+)"
    r"(?::\$?(?P<col2>\$?[A-Z]{1,3})\$?(?P<row2>\d+))?"
)
_ROWFN_RE = re.compile(
    r"\b(?P<fn>ROW|COLUMN)\s*\(\s*(?:(?P<sheet>'[^']+'|[^'!=+\-*/&(),\s]+)!)?"
    r"(?P<col>\$?[A-Z]{1,3})?(?P<row>\d+)?\s*\)",
    re.IGNORECASE,
)


class _XlsxResolver:
    """公式无缓存值时的引用解析（系统导出的 xlsx 常不写公式缓存）"""

    def __init__(self, val_grids: dict, frm_grids: dict):
        self.val_grids = val_grids
        self.frm_grids = frm_grids

    def cell_val(self, sheet: str, row: int, col: int, depth: int = 0):
        """取单元格值：缓存值优先，公式单元格递归解析（最多 5 层防环）"""
        vals = self.val_grids.get(sheet) or []
        v = vals[row][col] if row < len(vals) and col < len(vals[row]) else None
        if v is not None:
            return v
        frms = self.frm_grids.get(sheet) or []
        f = frms[row][col] if row < len(frms) and col < len(frms[row]) else None
        if isinstance(f, str) and f.startswith("="):
            return self.resolve_formula(f, sheet, depth + 1, cur_row=row + 1)
        return f

    def resolve_formula(self, formula: str, cur_sheet: str, depth: int = 0, cur_row: Optional[int] = None):
        """解析公式：拼接引用值与引号常量；含算术运算等无法安全解析时保留公式文本"""
        from openpyxl.utils import column_index_from_string

        if depth > 5:
            return formula
        f = formula[1:].strip() if formula.startswith("=") else formula.strip()
        orig = f  # 未替换 ROW() 的原始公式，算术路径需要（其 _rowfn 产出裸数字）

        # ROW()/COLUMN() 先换算成带引号的常量（裸数字不会被 token 收集导致拼接丢值）
        def _rowfn(m):
            fn = m.group("fn").upper()
            col = (m.group("col") or "").replace("$", "")
            row = m.group("row") or (str(cur_row) if (fn == "ROW" and cur_row) else None)
            if fn == "ROW":
                return f'"{row}"' if row else '""'
            if col:
                try:
                    return f'"{column_index_from_string(col)}"'
                except Exception:
                    return '""'
            return '""'

        f = _ROWFN_RE.sub(_rowfn, f)

        parts: list[str] = []
        pos = 0
        for m in _TOKEN_RE.finditer(f):
            # token 之间只允许 & 、逗号、函数名与括号；出现算术/比较符号则转算术路径
            if re.search(r"[+\-*/^%<>]", f[pos:m.start()]):
                return self._resolve_arithmetic(orig, cur_sheet, cur_row, depth) or formula
            if m.group(0).startswith('"'):
                parts.append(m.group(0)[1:-1])
            else:
                sheet = (m.group("sheet") or cur_sheet).strip("'")
                if m.group("col2"):  # 区域引用（A1:B2）不支持拼接，保留原文
                    parts.append(m.group(0))
                else:
                    col = (m.group("col") or "").replace("$", "")
                    try:
                        v = self.cell_val(sheet, int(m.group("row")) - 1,
                                          column_index_from_string(col) - 1, depth)
                    except Exception:
                        v = None
                    parts.append(_cell_to_text(v))
            pos = m.end()
        if re.search(r"[+\-*/^%<>]", f[pos:]):
            return self._resolve_arithmetic(orig, cur_sheet, cur_row, depth) or formula
        return "".join(parts)

    def _resolve_arithmetic(self, f: str, cur_sheet: str, cur_row, depth: int):
        """路径 B：仅数字/引用 + 四则运算的安全求值（如 =ROW()-1）；解析失败返回 None"""
        from openpyxl.utils import column_index_from_string

        def _rowfn(m):
            fn = m.group("fn").upper()
            row = m.group("row") or (str(cur_row) if (fn == "ROW" and cur_row) else None)
            if fn == "ROW":
                return row or m.group(0)
            col = (m.group("col") or "").replace("$", "")
            if col:
                try:
                    return str(column_index_from_string(col))
                except Exception:
                    return m.group(0)
            return m.group(0)

        expr = _ROWFN_RE.sub(_rowfn, f)
        # 引用替换为其数值
        parts: list[str] = []
        pos = 0
        for m in _TOKEN_RE.finditer(expr):
            if m.group(0).startswith('"'):
                return None  # 算术路径不支持字符串常量
            if m.group("col2"):
                return None
            sheet = (m.group("sheet") or cur_sheet).strip("'")
            col = (m.group("col") or "").replace("$", "")
            try:
                v = self.cell_val(sheet, int(m.group("row")) - 1,
                                  column_index_from_string(col) - 1, depth)
                num = float(v)
            except Exception:
                return None
            parts.append(expr[pos:m.start()])
            parts.append(str(num))
            pos = m.end()
        parts.append(expr[pos:])
        expr = "".join(parts)
        # 只允许数字与四则运算字符，杜绝任意代码执行
        if not re.fullmatch(r"[\d\s+\-*/().]+", expr) or not expr.strip():
            return None
        try:
            val = eval(expr, {"__builtins__": {}}, {})  # noqa: S307 已白名单限制字符集
        except Exception:
            return None
        return _cell_to_text(val)


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
    """xlsx/xlsm → Markdown：每个工作表转一个表格，多表用 `## 工作表名` 分节

    同时加载值模式与公式模式两份网格：缓存值为空的公式单元格走引用解析兜底。
    """
    from openpyxl import load_workbook

    # 不用 read_only：其读取范围依赖文件内 <dimension> 声明，WPS/系统导出的文件
    # 常把 dimension 写成 A1 导致整表只剩首格；普通模式按实际单元格解析（5MB 上限内存可控）
    wb_v = load_workbook(io.BytesIO(raw), data_only=True)
    wb_f = load_workbook(io.BytesIO(raw), data_only=False)
    try:
        val_grids = {ws.title: list(ws.iter_rows(values_only=True)) for ws in wb_v.worksheets}
        frm_grids = {ws.title: list(ws.iter_rows(values_only=True)) for ws in wb_f.worksheets}
        if not val_grids:
            return ""
        resolver = _XlsxResolver(val_grids, frm_grids)

        converted: list[tuple[str, str]] = []  # (表名, markdown)
        for title, vals in val_grids.items():
            frm = frm_grids.get(title) or []
            resolved = []
            for r, row in enumerate(vals):
                frow = frm[r] if r < len(frm) else ()
                new_row = []
                for c, v in enumerate(row):
                    if v is None and c < len(frow) and isinstance(frow[c], str) and frow[c].startswith("="):
                        new_row.append(resolver.resolve_formula(frow[c], title, cur_row=r + 1))
                    else:
                        new_row.append(v)
                resolved.append(new_row)
            md = _sheet_to_markdown(resolved)
            if md:
                converted.append((title, md))

        # 单表不加分节标题，多表用 `## 表名` 分节
        multi = len(converted) > 1
        out: list[str] = []
        for title, md in converted:
            if multi:
                if out:
                    out.append("")
                out.append(f"## {title}")
            out.append(md)
        return "\n".join(out).strip()
    finally:
        wb_v.close()
        wb_f.close()


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
