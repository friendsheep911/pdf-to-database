# -*- coding: utf-8 -*-
"""抽取结果体检模板：全量跑完后、宣布交付之前必跑。

四类检查（按需增删字段）：
  A. 伪列共现：地区级列与县级列在同一 section 共存 = 塌缩特征
     （注意：单地区统一价表 area='XX地区' 是合法形态，勿一刀切——
      真伪列的判据是"共存"或"该地区本该是县列表却只有地区列"）
  B. 表头与行值一致性：行里出现的 area 必须在表头清单里，反之亦然
  C. 缺失率：无价格行占比、缺含税/除税占比（与既有口径对比判断是否可接受）
  D. 回归对比：--baseline 指向上一版数据目录，按 section 统计行数/价格点数差异

用法：
  python audit_template.py <数据目录> [--baseline <旧数据目录>]
数据格式：目录下若干 <名称>.json，每个文件含 sections:[{region,kind,areas,rows:[{prices:[{area,incl,excl}]}]}]
"""
import argparse, io, json, sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def load_sections(data_dir):
    out = []
    for f in sorted(Path(data_dir).glob("*.json")):
        if f.name.startswith(("index", "official", "_")):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[跳过坏文件] {f.name}: {e}")
            continue
        for s in d.get("sections", []):
            out.append((f.stem, s))
    return out


def section_stats(s):
    areas_hdr = set(a.replace(" ", "") for a in s.get("areas", []))
    area_cnt, n_incl, n_excl, n_none = Counter(), 0, 0, 0
    for r in s["rows"]:
        ps = r.get("prices", [])
        if not ps:
            n_none += 1
            continue
        for p in ps:
            area_cnt[p.get("area", "")] += 1
            if (p.get("incl") or {}).get("num"):
                n_incl += 1
            if (p.get("excl") or {}).get("num"):
                n_excl += 1
    return areas_hdr, area_cnt, n_incl, n_excl, n_none


def audit(data_dir):
    problems = []
    for src, s in load_sections(data_dir):
        label = f"{src}|{s.get('region')}|{s.get('kind')}"
        areas_hdr, area_cnt, n_incl, n_excl, n_none = section_stats(s)
        all_areas = set(area_cnt) | areas_hdr
        region_cols = [a for a in all_areas if "地区" in a]
        county_cols = [a for a in all_areas if a and "地区" not in a]
        # A. 共现 = 塌缩
        if region_cols and county_cols:
            problems.append(f"[A伪列] {label}: 地区列{region_cols}与县列共存{county_cols[:6]}")
        # B. 表头/行值不一致
        only_hdr = areas_hdr - set(area_cnt)
        only_row = set(area_cnt) - areas_hdr
        if only_hdr:
            problems.append(f"[B表头] {label}: 表头县无价格 {sorted(only_hdr)}")
        if only_row:
            problems.append(f"[B表头] {label}: 行值县不在表头 {sorted(only_row)}")
        n_rows = len(s["rows"])
        if n_rows and n_none > n_rows * 0.05:
            problems.append(f"[C缺失] {label}: 无价格行 {n_none}/{n_rows}")
    return problems


def diff_baseline(data_dir, base_dir):
    """按 (region,kind) 统计行数与价格点数，与基线比对；只报差异方向，供人工判断。"""
    def agg(d):
        m = {}
        for _src, s in load_sections(d):
            k = (s.get("region"), s.get("kind"))
            n_price = sum(1 for r in s["rows"] for p in r.get("prices", [])
                          if (p.get("incl") or {}).get("num"))
            m[k] = m.get(k, (0, 0, 0)) + (len(s["rows"]), n_price, 1)
        return m
    cur, base = agg(data_dir), agg(base_dir)
    for k in sorted(set(cur) | set(base)):
        c, b = cur.get(k, (0, 0, 0)), base.get(k, (0, 0, 0))
        if c[:2] != b[:2]:
            dr, dp = c[0] - b[0], c[1] - b[1]
            tag = "增加" if (dr + dp) > 0 else "减少"
            print(f"  [D回归] {k[0]}|{k[1]}: 行 {b[0]}→{c[0]} 价格点 {b[1]}→{c[1]}（{tag}）"
                  f" ← 正向=修复恢复；负向=排查是否丢数据")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--baseline", default="")
    args = ap.parse_args()
    problems = audit(args.data_dir)
    if problems:
        print(f"发现 {len(problems)} 处问题：")
        for p in problems[:60]:
            print(" ", p)
    else:
        print("[A/B/C] 全部通过 ✓")
    if args.baseline:
        print(f"--- 基线对比（{args.baseline}）---")
        diff_baseline(args.data_dir, args.baseline)
    print("=== 体检完成 ===")


if __name__ == "__main__":
    main()
