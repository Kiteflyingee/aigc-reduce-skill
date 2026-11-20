#!/usr/bin/env python3
"""解析知网 AIGC 检测报告 PDF（全文报告单 / 简洁报告单均可），输出结构化 JSON。

依赖: poppler 的 pdftohtml（brew install poppler）。
用法: parse_report.py <report.pdf> -o report.json

输出:
  summary   总AI特征值、AI特征字符数、总字符数、前/中/后部、分段结果、片段列表
  paragraphs  报告正文按段切分，每段 text 与逐字 levels（S=显著 U=疑似 N=未标识）
  kind      full（全文报告单，含未标识文字及颜色）/ simple（简洁报告单，只含被标识片段）
"""
import argparse, json, os, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from collections import Counter


def run_pdftohtml(pdf):
    d = tempfile.mkdtemp()
    out = os.path.join(d, 'r')
    try:
        subprocess.run(['pdftohtml', '-xml', '-i', '-q', '-nodrm', pdf, out], check=True)
    except FileNotFoundError:
        sys.exit('未找到 pdftohtml，请先安装 poppler（macOS: brew install poppler）')
    return out + '.xml'


def color_level(hexc):
    r, g, b = int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)
    if r > 170 and g < 90 and b < 90:
        return 'S'  # 红色 = AI特征显著
    if r > 120 and 50 <= g <= 190 and b < 120 and r - b > 60:
        return 'U'  # 棕/橙色 = AI特征疑似
    return 'N'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf'); ap.add_argument('-o', required=True)
    args = ap.parse_args()
    root = ET.parse(run_pdftohtml(args.pdf)).getroot()
    fonts = {}
    for f in root.iter('fontspec'):
        fonts[f.get('id')] = dict(size=int(f.get('size')), color=f.get('color', '#000000'),
                                  family=f.get('family', ''), watermark=f.get('opacity') is not None)
    elems = []  # (page, top, left, font, text)
    for page in root.iter('page'):
        pn = int(page.get('number'))
        for t in page.iter('text'):
            txt = ''.join(t.itertext())
            if not txt.strip():
                continue
            elems.append((pn, int(t.get('top')), int(t.get('left')), t.get('font'), txt))
    # ---- 概要（取所有非正文文字按行拼起来再用正则）
    lines = {}
    for pn, top, left, fid, txt in elems:
        if fonts[fid]['watermark']:
            continue
        lines.setdefault((pn, top // 4), []).append((left, txt))
    plain = [' '.join(t for _, t in sorted(v)) for k, v in sorted(lines.items())]
    joined = '\n'.join(plain)
    summary = {}
    m = re.search(r'AI特征值：\s*([\d.]+)%', joined)
    if m:
        summary['ai_rate'] = float(m.group(1))
    m = re.search(r'AI特征字符数：\s*(\d+)', joined)
    if m:
        summary['ai_chars'] = int(m.group(1))
    m = re.search(r'总字符数：(\d+)', joined)
    if m:
        summary['total_chars'] = int(m.group(1))
    summary['sections'] = [dict(no=int(a), rate=float(b), ai_chars=int(c), chars=int(d), name=e.strip())
                           for a, b, c, d, e in re.findall(r'^\s*(\d+)\s*([\d.]+)%\s*(\d+)\s*/\s*(\d+)\s*(\S.*)$', joined, re.M)]
    summary['segments'] = [dict(name=a, chars=int(b), level=c)
                           for a, b, c in re.findall(r'(片段\d+)\s*字符数：\s*(\d+)\s*AI特征：\s*(显著|疑似)', joined)]
    # ---- 正文：取字号众数的那一档（排除水印）
    # 知网报告界面文字用 *CNKI 字体，正文（论文原文）用宋体/仿宋等其他字体
    ui = lambda f: 'CNKI' in fonts[f]['family'].upper() or fonts[f]['watermark']
    cand = [(fonts[f]['size'], f) for _, _, _, f, t in elems if not ui(f) and len(t) >= 6]
    if not cand:
        ui = lambda f: fonts[f]['watermark']
        cand = [(fonts[f]['size'], f) for _, _, _, f, t in elems if not ui(f) and len(t) >= 6]
    body_size = Counter(s for s, _ in cand).most_common(1)[0][0]
    is_body = lambda f: fonts[f]['size'] == body_size and not ui(f)
    kind = 'full' if any(is_body(f) and color_level(fonts[f]['color']) != 'N' for _, _, _, f, _ in elems) else 'simple'
    # 简洁报告单：用 "NO.x 片段x ... AI特征：显著/疑似" 行确定片段范围
    markers = []  # (page, top, level)
    for (pn, tb), v in sorted(lines.items()):
        s = ' '.join(t for _, t in sorted(v))
        mm = re.search(r'片段\d+.*AI特征：\s*(显著|疑似)', s)
        if mm:
            markers.append((pn, tb * 4, 'S' if mm.group(1) == '显著' else 'U'))
        elif re.match(r'^\s*\d+\.\s*\S', s) or '片段指标列表' in s or '片段详情' in s:
            markers.append((pn, tb * 4, None))
    def seg_level(pn, top):
        lvl, idx = None, -1
        for i, (mp, mt, ml) in enumerate(markers):
            if (mp, mt) <= (pn, top):
                lvl, idx = ml, i
            else:
                break
        return lvl, idx
    margin = re.compile(r'^\s*\d+(\.\d+)?%\(\d+\)\s*$')  # 右侧边栏 "8.5%(710)" 标签
    body = sorted([e for e in elems if is_body(e[3]) and not margin.match(e[4])], key=lambda e: (e[0], e[1], e[2]))
    # 分行
    blines = []
    for e in body:
        if blines and blines[-1][0] == e[0] and abs(blines[-1][1] - e[1]) <= 4:
            blines[-1][2].append(e)
        else:
            blines.append([e[0], e[1], [e]])
    page_min_left = {}
    for pn, top, es in blines:
        l = min(x[2] for x in es)
        page_min_left[pn] = min(page_min_left.get(pn, 10**6), l)
    paras, cur, cur_lv = [], '', ''
    prev_seg = None
    for pn, top, es in blines:
        es.sort(key=lambda x: x[2])
        left = es[0][2]
        sl, si = seg_level(pn, top) if kind == 'simple' else (None, None)
        if kind == 'simple' and sl is None:
            continue  # 简洁报告单中片段以外的正文
        new_para = left > page_min_left[pn] + 15 or (kind == 'simple' and si != prev_seg)
        prev_seg = si
        if new_para and cur:
            paras.append(dict(text=cur, levels=cur_lv)); cur, cur_lv = '', ''
        for _, _, _, fid, txt in es:
            lv = sl if kind == 'simple' else color_level(fonts[fid]['color'])
            cur += txt; cur_lv += lv * len(txt)
    if cur:
        paras.append(dict(text=cur, levels=cur_lv))
    out = dict(kind=kind, summary=summary, paragraphs=paras)
    json.dump(out, open(args.o, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    s_chars = sum(p['levels'].count('S') for p in paras)
    u_chars = sum(p['levels'].count('U') for p in paras)
    print('报告类型: %s | 总AI特征值: %s%% | 正文 %d 段, 显著 %d 字, 疑似 %d 字 -> %s' % (
        '全文报告单' if kind == 'full' else '简洁报告单', summary.get('ai_rate'), len(paras), s_chars, u_chars, args.o))


if __name__ == '__main__':
    main()
