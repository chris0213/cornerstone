/**
 * Markdown 表格 ↔ 二维数组互转工具
 *
 * 约定：
 *   - 以 `|` 开头结尾的连续行构成表格块（支持空行分隔、跳过 --- 分隔行）
 *   - 首个非空行为表头，其行列数决定整个表格的 shape
 *   - 单元格内容中的 `|` 需要反转义（split 前），序列化时再次转义
 *   - 正文中可含标题/段落/列表/代码块，表格外的内容原样保留
 */

// -------- 识别 --------

/** 判断一行是否属于 Markdown 表格块（以 | 包裹） */
export function isMdTableRow(line: string): boolean {
  return /^\s*\|.*\|\s*$/.test(line)
}

/** 判断一行是否是表格的 --- 分隔行（跳过） */
export function isMdTableSep(line: string): boolean {
  return /^\s*\|[\s\-:|]+\|\s*$/.test(line)
}

/** 从正文中提取第一个 Markdown 表格块的范围（[start, end] 行索引，闭区间），无则 null */
export function findFirstTableBlock(lines: string[]): { start: number; end: number } | null {
  let start = -1
  let end = -1
  for (let i = 0; i < lines.length; i++) {
    if (isMdTableRow(lines[i])) {
      if (start === -1) start = i
      end = i
    } else if (start !== -1) {
      break
    }
  }
  return start === -1 ? null : { start, end }
}

// -------- 解析 → 数组 --------

/** 把一行 Markdown 表格拆成单元格数组（反转义 `\|`） */
export function splitMdRow(line: string): string[] {
  // 先把 \| 换成占位，split 后再换回来
  const ESC = '\x00PIPE\x00'
  const escaped = line.trim().replace(/^[|]\s*/, '').replace(/\s*[|]$/, '').replace(/\\\|/g, ESC)
  return escaped.split('|').map(c => c.trim().replace(new RegExp(ESC, 'g'), '\\|'))
}

/** 从正文解析第一个 Markdown 表格为 [header[], body[][]]；无表格时返回 null */
export function parseFirstMdTable(content: string): { header: string[]; body: string[][] } | null {
  const lines = content.split('\n')
  const block = findFirstTableBlock(lines)
  if (!block) return null
  const raw = lines.slice(block.start, block.end + 1)
  const rows = raw.filter(l => !isMdTableSep(l)).map(splitMdRow)
  if (rows.length === 0) return null

  // 对齐列宽：以表头列数为准
  const width = rows[0].length
  const pad = (r: string[]) => (r.length < width ? r.concat(new Array(width - r.length).fill('')) : r.slice(0, width))
  const [header, ...body] = rows.map(pad)
  return { header, body }
}

/** 从正文解析**所有** Markdown 表格，返回 [{header, body, startLine, endLine}] */
export function parseAllMdTables(content: string): Array<{
  header: string[]
  body: string[][]
  startLine: number
  endLine: number
}> {
  const lines = content.split('\n')
  const out: Array<{ header: string[]; body: string[][]; startLine: number; endLine: number }> = []
  let cursor = 0
  while (cursor < lines.length) {
    const block = findFirstTableBlock(lines.slice(cursor))
    if (!block) break
    const absStart = cursor + block.start
    const absEnd = cursor + block.end
    const raw = lines.slice(absStart, absEnd + 1)
    const rows = raw.filter(l => !isMdTableSep(l)).map(splitMdRow)
    if (rows.length) {
      const width = rows[0].length
      const pad = (r: string[]) => (r.length < width ? r.concat(new Array(width - r.length).fill('')) : r.slice(0, width))
      const [header, ...body] = rows.map(pad)
      out.push({ header, body, startLine: absStart, endLine: absEnd })
    }
    cursor = absEnd + 1
  }
  return out
}

// -------- 数组 → 序列化 --------

/** 把二维数组序列化为 Markdown 表格字符串（含换行；单元格中 | 自动转义） */
export function arrayToMdTable(header: string[], body: string[][]): string {
  const esc = (s: string) => String(s ?? '').replace(/\|/g, '\\|').trim()
  const width = header.length
  const rowLine = (cells: string[]) => '| ' + cells.concat(new Array(width - cells.length).fill('')).slice(0, width).map(esc).join(' | ') + ' |'
  const sepLine = '| ' + new Array(width).fill('---').join(' | ') + ' |'
  const lines = [rowLine(header), sepLine, ...body.map(r => rowLine(r))]
  return lines.join('\n')
}

/** 用新的 header/body 替换正文中第 index 个表格（0-based）；不存在则追加到末尾 */
export function replaceMdTable(
  content: string,
  index: number,
  header: string[],
  body: string[][],
): string {
  const tables = parseAllMdTables(content)
  if (index >= tables.length) {
    // 没有表格，直接追加
    const sep = content.trim().length && !content.endsWith('\n\n') ? '\n\n' : ''
    return content.trimEnd() + sep + arrayToMdTable(header, body) + '\n'
  }
  const t = tables[index]
  const lines = content.split('\n')
  const replacement = arrayToMdTable(header, body).split('\n')
  const newLines = [...lines.slice(0, t.startLine), ...replacement, ...lines.slice(t.endLine + 1)]
  return newLines.join('\n')
}
