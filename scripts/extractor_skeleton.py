# -*- coding: utf-8 -*-
"""表格型 PDF → 结构化 JSON 的抽取器骨架。

内建了实战中最容易翻车的四类防御（骨架中已实现，改版式时勿删）：
  A. 合并单元格县名/分组名向后继承
  B. 表头向上/向下收集时跳过碎片行（≤2字、无数字、非关键字的行，如竖排"单位"拆字）
  C. 匿名价格列塌缩防线：area 为 None 的价格列不许用 section 默认地区兜底
  D. 同 (blk,ln) 两词粘连的双价拆分（group1 必须"整数+两位小数"完整形态，防贪婪错拆）

用法：
  python extractor_skeleton.py <pdf> --out out.json [--start-page N]

按自己的版式改：MARKER 段落都标了「按版式定制」。
"""
import argparse, io, json, re, sys
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---------------- 按版式定制 ----------------
NUM_RE = re.compile(r"^[\d,]+(\.\d+)?$")
PRICE_KW = ("含税", "除税")                  # 价格列关键字
NAME_KW = ("名称",)                          # 名称列关键字
SPEC_KW = ("型号", "规格", "强度等级")
REGION_TITLE_RE = re.compile(r"([\u4e00-\u9fa5]{2,6}?)地区")   # 表题地区
COUNTY_FIX = {}                              # 原件印刷县名错误修正，如 {"天骏": "天峻"}


def norm_area(t):
    """列名归一化：剥括注（海晏县(含西海镇)→海晏县）+ 印刷错误修正。"""
    t = (t or "").strip()
    base = re.sub(r"[（(][^）)]*[）)]?", "", t).strip()
    if not base:
        return t
    return COUNTY_FIX.get(base, base)


def clean(t):
    return re.sub(r"\s+", "", t or "")


# ---------------- 双价拆分（防御 D）----------------
SPLIT2_RE = re.compile(r"^(\d[\d,]*\.\d{2})(\d+[(（][^)）]*[)）])$")


def split_glued_price(text):
    """'350.00350(茶卡398)' → ('350.00', '350')；'60.00（茶卡）'（括注无价）不拆。
    group1 限定「整数+恰好两位小数」完整形态，避免贪婪回溯错拆成 '350.0035'/'0'。"""
    m = SPLIT2_RE.match(text)
    if not m:
        return None
    m2 = re.match(r"^[\d,.]+", m.group(2))
    return m.group(1), m2.group(0)


def is_fragile_fragment(text):
    """防御 B：表头碎片行。竖排"单位"被 OCR/字体拆出的「单」字等。
    判据：≤2 字、无数字、不含任何表头关键字。"""
    t = (text or "").strip()
    if not t or len(t) > 2 or re.search(r"\d", t):
        return False
    return not any(k in t for k in PRICE_KW + NAME_KW + SPEC_KW)


def build_line_groups(page, tb):
    """把页面 words 按 (block,line) 聚成印刷行；返回 [(y, x0, text)]。
    注意：同一印刷行的多个词会粘连（'350.00' + '350(茶卡398)'），
    价格列处理时要用 split_glued_price 兜底。"""
    words = page.get_text("words")
    ys_all = [c[1] for c in tb.cells] + [c[3] for c in tb.cells]
    top, bot = min(ys_all), max(ys_all)
    groups = defaultdict(list)
    for x0, y0, x1, y1, txt, blk, ln, _wno in words:
        if y1 < top - 2 or y0 > bot + 2:
            continue
        groups[(blk, ln)].append((x0, y0, x1, y1, txt))
    lines = []
    for ws in groups.values():
        ws.sort(key=lambda t: t[0])
        y = sum(t[1] + t[3] for t in ws) / (2 * len(ws))
        lines.append((y, ws[0][0], " ".join(t[4] for t in ws)))
    return sorted(lines)


def col_segments(tb, n_cols):
    """从表格 cell 边界求列边界 segs；cell 不全时均匀切分兜底。"""
    xs = []
    for (x0, _y0, x1, _y1) in tb.cells:
        xs.extend([x0, x1])
    xs.sort()
    segs = []
    for x in xs:
        if not segs or x - segs[-1] > 3:
            segs.append(x)
    if len(segs) < n_cols + 1:
        x0 = min(c[0] for c in tb.cells)
        x1 = max(c[2] for c in tb.cells)
        step = (x1 - x0) / n_cols
        segs = [x0 + i * step for i in range(n_cols + 1)]
        segs[-1] = x1 + 1
    segs[-1] += 5
    return segs


def classify_cols(header_texts):
    """按表头文本给列定角色：price/name/spec/unit/idx/note/None。"""
    roles = []
    for h in header_texts:
        if any(k in h for k in PRICE_KW):
            roles.append("price")
        elif "序号" in h:
            roles.append("idx")
        elif any(k in h for k in NAME_KW):
            roles.append("name")
        elif any(k in h for k in SPEC_KW):
            roles.append("spec")
        elif "单位" in h:
            roles.append("unit")
        elif "备注" in h:
            roles.append("note")
        else:
            roles.append("area_or_price")   # 单价格层：列头即地区/县名
    return roles


def parse_page(page):
    """解析单页全部表格 → 行 dict 列表。按自己的版式改这里。

    局限（诚实声明）：本骨架按「单层表头：列头即县名/地区」的通用形态实现。
    若源 PDF 是多层表头（如：县名行 + 含税/除税行 双层，或 标题行+表头+地区名行），
    需要把 classify_cols 之前的部分改为「表头块收集」：自首个数值行向上收集
    2~3 行表头（跳碎片行），逐列合并出 (area, incl/excl) 列定义——
    完整实现与坑位对照见 references/case-qinghai.md Bug⑦/⑨。"""
    rows_out = []
    for tb in page.find_tables().tables:
        data = tb.extract()
        if not data or len(data) < 2:
            continue
        n_cols = len(data[0])
        segs = col_segments(tb, n_cols)
        lines = build_line_groups(page, tb)

        col_lines = [[] for _ in range(n_cols)]
        for y, x, text in lines:
            for i in range(n_cols):
                if segs[i] - 2 <= x < segs[i + 1]:
                    t = clean(text)
                    if t:
                        col_lines[i].append((y, t))
                    break

        # 防御 D：列内双价拆分（右列该 y 已有数字则不拆）
        for i in range(n_cols - 1):
            out, extra, hit = [], [], False
            for y, t in col_lines[i]:
                sp = split_glued_price(t)
                if sp and not any(NUM_RE.match(rt) for ry, rt in col_lines[i + 1]
                                  if abs(ry - y) < 3):
                    hit = True
                    out.append((y, sp[0]))
                    extra.append((y, sp[1]))
                else:
                    out.append((y, t))
            if hit:
                col_lines[i] = out
                col_lines[i + 1].extend(extra)
                col_lines[i + 1].sort()

        # 表头判定：取每列首个数值行之上的文本（跳碎片行=防御 B）
        headers, body_start = [], []
        for i in range(n_cols):
            ys = [(y, t) for y, t in col_lines[i] if NUM_RE.match(t)]
            cut = ys[0][0] if ys else max((y for y, _ in col_lines[i]), default=0) + 1
            hdr = ""
            for y, t in sorted(col_lines[i]):
                if y >= cut:
                    break
                if is_fragile_fragment(t):
                    continue
                hdr += t
            headers.append(hdr)
            body_start.append(cut)

        roles = classify_cols(headers)
        cur_area = ""
        for i in range(n_cols):
            if roles[i] == "area_or_price":
                a = norm_area(headers[i])
                if a:
                    cur_area = a                # 防御 A：县名合并单元格向后继承
                roles[i] = "price"
                headers[i] = headers[i] or cur_area

        # 防御 C：匿名价格列≥2 且全部无 area → 拒绝（多为文件附表等假表格）
        price_idx = [i for i, r in enumerate(roles) if r == "price"]
        if len(price_idx) >= 2 and not any(headers[i] for i in price_idx):
            print(f"  [拒绝] 无列名价格列≥2，疑似附表/版式不符")
            continue

        # 行带：以 name 列数值外的行序为准，逐行取各列该 y 带内的文本
        name_col = next((i for i, r in enumerate(roles) if r == "name"), 0)
        bands = sorted({y for y, _ in col_lines[name_col] if y >= body_start[name_col]})
        for by in bands:
            row = {"name": "", "spec": "", "unit": "", "prices": []}
            for i in range(n_cols):
                cell = "".join(t for y, t in col_lines[i]
                               if y >= body_start[i] and abs(y - by) < 6)
                if roles[i] == "name":
                    row["name"] = cell
                elif roles[i] == "spec":
                    row["spec"] = cell
                elif roles[i] == "unit":
                    row["unit"] = cell
                elif roles[i] == "price" and NUM_RE.match(cell or ""):
                    p = {"area": headers[i], "incl": {"num": float(cell.replace(",", ""))}}
                    row["prices"].append(p)
            if row["name"] or row["prices"]:
                rows_out.append(row)
    return rows_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default="out.json")
    ap.add_argument("--start-page", type=int, default=1)
    args = ap.parse_args()

    import pymupdf
    doc = pymupdf.open(args.pdf)
    all_rows = []
    for pno in range(args.start_page, len(doc) + 1):
        page = doc[pno - 1]
        if len(page.get_text("text").strip()) < 20:
            continue                      # 无文本层页交给 OCR 兜底流程
        rs = parse_page(page)
        if rs:
            all_rows.extend(rs)
            print(f"p{pno}: {len(rs)} 行")
    Path(args.out).write_text(json.dumps(
        {"source": Path(args.pdf).name, "rows": all_rows},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成：{len(all_rows)} 行 → {args.out}")


if __name__ == "__main__":
    main()
