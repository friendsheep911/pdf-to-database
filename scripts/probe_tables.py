# -*- coding: utf-8 -*-
"""PDF 侦察 + 表格探针：动手写抽取器之前必跑的第一步。

用途：
  1. 判断 PDF 有没有文本层（文本层为空 → 转曲/扫描件 → 需要 OCR 兜底）
  2. 用 find_tables 摸清每页表格形态（列数/行数/表头首行），按列数分组
     归纳出版式种类，指导"逐版式写解析器"
  3. 采样页 dump 表格首行原始文本，肉眼确认表头关键词

用法：
  python probe_tables.py <pdf路径> [--pages 1-40] [--sample 8] [--full]

依赖：pip install pymupdf（建议装到项目 vendor/ 目录随项目走）
"""
import argparse, io, sys
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def page_text_chars(page):
    return len(page.get_text("text").strip())


def describe_tables(page):
    out = []
    try:
        tables = page.find_tables().tables
    except Exception as e:                       # find_tables 偶发崩溃要兜住
        return [f"<find_tables异常:{e}>"]
    for ti, tb in enumerate(tables):
        data = tb.extract()
        if not data or len(data) < 2:
            out.append(f"#{ti}:空/单行")
            continue
        ncol = len(data[0])
        head = " | ".join(str(c)[:6] for c in data[0] if c) or "(首行全空)"
        out.append(f"#{ti}:{len(data)}行x{ncol}列 表头[{head}]")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", default="", help="如 1-40 或 5,9,12；默认全册")
    ap.add_argument("--sample", type=int, default=0,
                    help="每 N 页采样 1 页（默认 0=全扫）")
    ap.add_argument("--full", action="store_true", help="每页打印全部表格详情")
    args = ap.parse_args()

    import pymupdf
    doc = pymupdf.open(args.pdf)
    pages = list(range(1, len(doc) + 1))
    if args.pages:
        pages = []
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-")
                pages.extend(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))

    n_ocr = 0                    # 无文本层页计数
    layout_groups = defaultdict(list)   # (表格列数) -> 页号列表
    for pno in pages:
        if args.sample and pno % args.sample != 1:
            continue
        page = doc[pno - 1]
        chars = page_text_chars(page)
        if chars < 20:
            n_ocr += 1
            print(f"p{pno}: [无文本层/转曲?] chars={chars} → 需 OCR 兜底")
            continue
        tbs = describe_tables(page)
        for t in tbs:
            if "行x" in t:
                ncol = int(t.split("行x")[1].split("列")[0])
                layout_groups[ncol].append(pno)
        if args.full:
            print(f"p{pno}: chars={chars}")
            for t in tbs:
                print(f"    {t}")

    print("\n===== 版式概览 =====")
    print(f"总页数 {len(pages)}，无文本层页 {n_ocr}（>0 则准备 OCR 方案）")
    for ncol, plist in sorted(layout_groups.items(), key=lambda kv: -len(kv[1])):
        head = f"  {ncol}列版式: {len(plist)}页"
        if len(plist) <= 30:
            head += f" {plist}"
        else:
            head += f" 首几页{plist[:8]}…"
        print(head)
    print("\n下一步：按列数分组逐版式抽 2~3 页人工比对原件，写/改解析器后再全量跑。")


if __name__ == "__main__":
    main()
