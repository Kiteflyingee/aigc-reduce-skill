#!/usr/bin/env python3
"""docx 段落抽取 / 回写工具（仅用标准库，保留原段落格式）。

用法:
  extract <paper.docx> -o paper.json
      按文档顺序抽取所有段落（含表格内段落）。上标（如引文编号）以 ^{...} 标记保留。
  apply <paper.docx> <rewrites.md> -o out.docx [--mark] [--excerpt]
      把 rewrites.md 中的改写写回 docx，只替换被改写段落的文字，段落格式(pPr)与字体(rPr)沿用原段。
      --mark     给改写过的段落加黄色高亮，方便人工核对
      --excerpt  只保留改写过的段落及其所在章节标题，生成"送检测试稿"（省检测费用）

rewrites.md 格式:
  ## P23
  改写后的整段文字（上标保留为 ^{[15]} 形式）
  （段内空一行 = 拆成两段，沿用同一段落格式）
  ## P24
  (删除)
"""
import argparse, json, re, sys, zipfile
from collections import Counter
from xml.sax.saxutils import escape, unescape

TAG_RE = re.compile(r'<(/?)(w:p|w:tbl)\b([^>]*?)(/?)>')


def read_xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read('word/document.xml').decode('utf8')


def body_bounds(xml):
    s = xml.index('<w:body>') + len('<w:body>')
    e = xml.rindex('</w:body>')
    return s, e


def scan(xml, start, end):
    """返回 (paragraphs, toplevel)。paragraphs: [(s,e)] 最外层 w:p；toplevel: [(kind,s,e,[para_idx])]"""
    paras, top = [], []
    stack = []  # (name, start)
    for m in TAG_RE.finditer(xml, start, end):
        closing, name, _, selfclose = m.groups()
        if selfclose:
            if not stack:
                if name == 'w:p':
                    paras.append((m.start(), m.end()))
                    top.append([name, m.start(), m.end(), [len(paras) - 1]])
            elif name == 'w:p' and not any(n == 'w:p' for n, _ in stack):
                paras.append((m.start(), m.end()))
                if top and top[-1][2] is None:
                    top[-1][3].append(len(paras) - 1)
            continue
        if not closing:
            if not stack:
                top.append([name, m.start(), None, []])
            stack.append((name, m.start()))
        else:
            n, s = stack.pop()
            if n == 'w:p' and not any(x == 'w:p' for x, _ in stack):
                paras.append((s, m.end()))
                top_entry = top[-1]
                top_entry[3].append(len(paras) - 1)
            if not stack:
                top[-1][2] = m.end()
    return paras, top


RUN_RE = re.compile(r'<w:r\b[^>]*>(.*?)</w:r>', re.S)
RPR_RE = re.compile(r'<w:rPr>.*?</w:rPr>', re.S)


def runs_of(pxml):
    out = []
    for m in RUN_RE.finditer(pxml):
        inner = m.group(1)
        rpr_m = RPR_RE.search(inner)
        rpr = rpr_m.group(0) if rpr_m else ''
        txt = ''
        for t in re.finditer(r'<w:t\b[^>]*>(.*?)</w:t>|<w:t\b[^>]*/>|<w:tab\s*/>|<w:br\b[^>]*/>', inner, re.S):
            if t.group(0).startswith('<w:tab'):
                txt += '\t'
            elif t.group(0).startswith('<w:br'):
                txt += '\n'
            elif t.group(1) is not None:
                txt += unescape(t.group(1), {'&quot;': '"', '&apos;': "'"})
        sup = 'w:val="superscript"' in rpr
        out.append((rpr, txt, sup))
    return out


def para_text(pxml):
    s, cur_sup = '', False
    for rpr, txt, sup in runs_of(pxml):
        if not txt:
            continue
        if sup and not cur_sup:
            s += '^{'
        if not sup and cur_sup:
            s += '}'
        cur_sup = sup
        s += txt
    if cur_sup:
        s += '}'
    return s


def style_of(pxml):
    m = re.search(r'<w:pStyle w:val="([^"]+)"', pxml)
    o = re.search(r'<w:outlineLvl w:val="(\d)"', pxml)
    return (m.group(1) if m else ''), (int(o.group(1)) if o else None)


def extract(path):
    xml = read_xml(path)
    bs, be = body_bounds(xml)
    paras, _ = scan(xml, bs, be)
    out = []
    for i, (s, e) in enumerate(paras):
        p = xml[s:e]
        style, lvl = style_of(p)
        locked = ('<w:drawing' in p or '<w:pict' in p or '<w:object' in p or 'fldChar' in p or '<w:instrText' in p)
        out.append({'idx': i, 'text': para_text(p), 'style': style, 'outline': lvl, 'locked': locked})
    return out


def parse_rewrites(path):
    txt = open(path, encoding='utf8').read()
    parts = re.split(r'^##\s*P(\d+)\s*$', txt, flags=re.M)
    rw = {}
    for i in range(1, len(parts), 2):
        body = parts[i + 1].strip()
        rw[int(parts[i])] = body
    return rw


def strip_highlight(rpr):
    return re.sub(r'<w:highlight\b[^>]*/>', '', rpr)


def build_para(pxml, new_text, mark):
    open_m = re.match(r'<w:p\b[^>]*>', pxml)
    open_tag = open_m.group(0) if open_m else '<w:p>'
    ppr_m = re.search(r'<w:pPr>.*?</w:pPr>', pxml, re.S)
    ppr = ppr_m.group(0) if ppr_m else ''
    runs = runs_of(pxml)
    normal = Counter(strip_highlight(r) for r, t, s in runs if not s and t.strip())
    supers = [strip_highlight(r) for r, t, s in runs if s and t.strip()]
    base = normal.most_common(1)[0][0] if normal else ''
    sup_rpr = supers[0] if supers else '<w:rPr><w:vertAlign w:val="superscript" /></w:rPr>'
    if mark:
        add = '<w:highlight w:val="yellow" />'
        base = base.replace('</w:rPr>', add + '</w:rPr>') if base else '<w:rPr>' + add + '</w:rPr>'
    pieces = re.split(r'(\^\{.*?\})', new_text)
    rx = ''
    for pc in pieces:
        if not pc:
            continue
        if pc.startswith('^{') and pc.endswith('}'):
            rx += '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (sup_rpr, escape(pc[2:-1]))
        else:
            rx += '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (base, escape(pc))
    return open_tag + ppr + rx + '</w:p>'


def is_heading(item):
    t = item['text'].strip()
    return bool(t) and (item['outline'] is not None or (len(t) <= 40 and '。' not in t and not t.startswith('［')))


def apply(path, rw_path, out, mark=False, excerpt=False):
    xml = read_xml(path)
    bs, be = body_bounds(xml)
    paras, top = scan(xml, bs, be)
    items = extract(path)
    rw = parse_rewrites(rw_path)
    bad = [k for k in rw if k >= len(paras)]
    if bad:
        sys.exit('rewrites 中段号越界: %s' % bad)
    for k in rw:
        if items[k]['locked']:
            print('警告: P%d 含图片/域代码，回写会丢失这些对象' % k, file=sys.stderr)
    new_para = {}
    for k, body in rw.items():
        pxml = xml[paras[k][0]:paras[k][1]]
        if body.strip() in ('(删除)', '（删除）'):
            new_para[k] = ''
            continue
        chunks = [re.sub(r'\s*\n\s*', '', c) for c in re.split(r'\n\s*\n', body) if c.strip()]
        new_para[k] = ''.join(build_para(pxml, c, mark) for c in chunks)
    keep = None
    if excerpt:
        keep = set(rw)
        # 为每个改写段补上它之前最近的各级标题
        for k in rw:
            seen_lvls = set()
            for j in range(k - 1, -1, -1):
                if is_heading(items[j]):
                    lvl = items[j]['outline'] if items[j]['outline'] is not None else 9
                    if lvl not in seen_lvls:
                        keep.add(j)
                        seen_lvls.add(lvl)
                    if lvl <= 1 or len(seen_lvls) >= 3:
                        break
        if 0 in range(len(items)) and is_heading(items[0]):
            keep.add(0)
    # 重建 body
    body = []
    cursor = bs
    for kind, s, e, pidx in top:
        body.append(xml[cursor:s])
        seg = xml[s:e]
        if excerpt:
            if kind == 'w:p':
                if not (pidx[0] in keep or '<w:sectPr' in seg):
                    cursor = e
                    continue
            elif kind == 'w:tbl' and not keep.intersection(pidx):
                cursor = e
                continue
        # 替换段落
        out_seg, c2 = [], s
        for pi in pidx:
            ps, pe = paras[pi]
            if pi in new_para:
                out_seg.append(xml[c2:ps])
                out_seg.append(new_para[pi])
                c2 = pe
        out_seg.append(xml[c2:e])
        body.append(''.join(out_seg))
        cursor = e
    body.append(xml[cursor:be])
    new_xml = xml[:bs] + ''.join(body) + xml[be:]
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = new_xml.encode('utf8') if info.filename == 'word/document.xml' else zin.read(info.filename)
            zout.writestr(info, data)
    print('已写出 %s（改写 %d 段%s）' % (out, len(rw), '，送检测试稿' if excerpt else ''))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('extract'); a.add_argument('docx'); a.add_argument('-o', required=True)
    b = sub.add_parser('apply'); b.add_argument('docx'); b.add_argument('rewrites'); b.add_argument('-o', required=True)
    b.add_argument('--mark', action='store_true'); b.add_argument('--excerpt', action='store_true')
    args = ap.parse_args()
    if args.cmd == 'extract':
        items = extract(args.docx)
        json.dump(items, open(args.o, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
        print('抽取 %d 段 -> %s' % (len(items), args.o))
    else:
        apply(args.docx, args.rewrites, args.o, args.mark, args.excerpt)


if __name__ == '__main__':
    main()
