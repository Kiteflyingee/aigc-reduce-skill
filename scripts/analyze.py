#!/usr/bin/env python3
"""把 AIGC 报告的标色结果映射回论文段落，并做文体特征诊断，输出诊断表。

用法: analyze.py paper.json report.json -o analysis.json [--md analysis.md]
  paper.json  由 docx_tool.py extract 生成
  report.json 由 parse_report.py 生成

每段输出: 报告标色比例(sig/sus)、匹配覆盖率(cov)、文体高危特征计数、综合风险分、建议动作。
"""
import argparse, json, re, statistics
from collections import Counter, defaultdict

N = 8  # n-gram 锚定长度

# 高危词：LLM 中文学术腔高频抽象词/四字格（不是禁用，而是密度过高时报警）
RISK_WORDS = ('赋能 协同 耦合 贯通 统合 锚定 融通 联动 赋予 助力 深度融合 有机统一 有机耦合 内在逻辑 内在机理 '
              '底层逻辑 价值引领 双向互动 多元主体 全方位 全过程 系统性 整体性 结构性 开放性 发展性 '
              '着力 聚焦 夯实 筑牢 赋权 驱动 范式 场域 维度 闭环 抓手 落地 落细 落实 落脚点 '
              '日益 不断 持续 进一步 深层 深刻 显著 有效 切实 充分 积极 精准 靶向 渐次 '
              '彰显 凸显 呈现 释放 激活 推动 促进 实现 构建 打造 形成 提升 强化 优化 完善 健全 '
              '症结 掣肘 瓶颈 困境 桎梏 张力 本末倒置 越俎代庖 渐行渐远 不容回避 应运而生 '
              '与此同时 换言之 究其根源 由此可见 综上所述 不难发现 值得注意的是 需要指出的是').split()
CONNECTIVES = '因此 从而 进而 由此 同时 此外 与此同时 换言之 总之 综上 可见 首先 其次 再次 最后 一方面 另一方面 不仅 而且 既要 也要'.split()
META_END = re.compile(r'(这一|上述|由此可见|综上|总之|为.{0,20}提供了|具有.{0,6}意义|奠定了|指明了|开辟了|折射出|彰显了)')


def norm(s):
    s = re.sub(r'\^\{.*?\}', '', s)
    s = re.sub(r'\[\d+(?:[-–,，]\d+)*\]\d*', '', s)
    return re.sub(r'[\s\u3000"“”‘’\'·•]', '', s)


def sentences(t):
    return [x for x in re.split(r'(?<=[。！？])', re.sub(r'\^\{.*?\}', '', t)) if x.strip()]


def style(text):
    t = re.sub(r'\^\{.*?\}', '', text)
    L = max(len(t), 1)
    sents = sentences(t)
    lens = [len(s) for s in sents] or [0]
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    risk_hits = Counter(w for w in RISK_WORDS for _ in range(t.count(w)))
    conn = sum(t.count(c) for c in CONNECTIVES)
    enum = len(re.findall(r'(?:[\u4e00-\u9fa5A-Za-z]{2,8}[、])(?:[\u4e00-\u9fa5A-Za-z]{2,8}[、])+[\u4e00-\u9fa5A-Za-z]{2,8}', t))
    seq = len(re.findall(r'首先|其次|再次|一方面|另一方面|事前|事中|事后|课前|课上|课后', t))
    clauses = [c.strip()[:2] for c in re.split(r'[，；。：]', t) if len(c.strip()) >= 4]
    lead_rep = sum(v for v in Counter(clauses).values() if v >= 3)
    de_chain = sum(1 for s in sents if s.count('的') >= 4)
    meta = 1 if sents and META_END.search(sents[-1]) else 0
    quoted = sum(len(q) for q in re.findall(r'“[^”]{8,}”', t))
    return dict(chars=len(t), sent_mean=round(mean, 1), sent_cv=round(cv, 2), long_sent=sum(1 for x in lens if x > 70),
                risk_per100=round(sum(risk_hits.values()) * 100 / L, 2), risk_top=[w for w, _ in risk_hits.most_common(6)],
                conn=conn, enum3=enum, seq=seq, lead_rep=lead_rep, de_chain=de_chain, meta_end=meta,
                quote_ratio=round(quoted / L, 2))


def style_score(s):
    sc = 0
    sc += min(s['risk_per100'] / 4, 1.5)
    sc += 0.4 * s['enum3'] + 0.4 * s['seq'] + 0.3 * s['lead_rep'] + 0.3 * s['de_chain'] + 0.5 * s['meta_end']
    sc += 0.3 * s['long_sent']
    sc += 0.5 if s['sent_cv'] < 0.35 and s['chars'] > 150 else 0
    return round(sc, 2)


def classify(p, after_refs):
    t = p['text'].strip()
    if not t:
        return 'empty'
    if after_refs or re.match(r'^[［\[]\d+[］\]]', t):
        return 'ref'
    if re.match(r'^(参考文献|注释|致谢)\s*$', t):
        return 'refhead'
    if re.match(r'^(关键词|Key\s*words)', t, re.I):
        return 'keywords'
    if re.match(r'^(摘\s*要|Abstract)', t, re.I):
        return 'abstract'
    if p.get('outline') is not None or (len(t) <= 40 and '。' not in t):
        return 'heading'
    return 'body'


def map_labels(paper, report):
    rtext, rlev = '', ''
    for rp in report['paragraphs']:
        for ch, lv in zip(rp['text'], rp['levels']):
            n = norm(ch)
            if n:
                rtext += n; rlev += lv
    grams = defaultdict(list)
    for i in range(len(rtext) - N + 1):
        grams[rtext[i:i + N]].append(i)
    res, last = [], 0
    for p in paper:
        t = norm(p['text'])
        lab = [None] * len(t)
        for j in range(len(t) - N + 1):
            pos = grams.get(t[j:j + N])
            if not pos:
                continue
            k = min(pos, key=lambda x: abs(x - (last + 1)))  # 优先选与上一次匹配位置相邻的
            last = k
            for d in range(N):
                lab[j + d] = rlev[k + d]
        L = max(len(t), 1)
        cov = sum(1 for x in lab if x is not None) / L
        if report['kind'] == 'simple':  # 简洁报告单不含未标识文字：未匹配即视为未标识
            sig = sum(1 for x in lab if x == 'S') / L
            sus = sum(1 for x in lab if x == 'U') / L
        else:
            matched = max(sum(1 for x in lab if x is not None), 1)
            sig = sum(1 for x in lab if x == 'S') / matched
            sus = sum(1 for x in lab if x == 'U') / matched
        res.append((round(sig, 2), round(sus, 2), round(cov, 2)))
    return res


def action(kind, sig, sus, ss, rate):
    if kind not in ('body', 'abstract'):
        return '保留'
    if sig >= 0.5:
        return '深改'
    if sig >= 0.1 or sus >= 0.3:
        return '中改'
    if rate is not None and rate >= 50 and ss >= 1.5:
        return '轻改'
    return '保留'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paper'); ap.add_argument('report'); ap.add_argument('-o', required=True); ap.add_argument('--md')
    a = ap.parse_args()
    paper = json.load(open(a.paper, encoding='utf8'))
    report = json.load(open(a.report, encoding='utf8'))
    rate = report['summary'].get('ai_rate')
    labels = map_labels(paper, report)
    rows, after_refs = [], False
    for p, (sig, sus, cov) in zip(paper, labels):
        kind = classify(p, after_refs)
        if kind == 'refhead':
            after_refs = True
        st = style(p['text']) if kind in ('body', 'abstract') else None
        ss = style_score(st) if st else 0
        rows.append(dict(idx=p['idx'], kind=kind, sig=sig, sus=sus, cov=cov, style=st, style_score=ss,
                         risk=round(0.6 * sig + 0.2 * sus + 0.2 * min(ss / 3, 1), 2),
                         action=action(kind, sig, sus, ss, rate), head=p['text'][:24]))
    body = [r for r in rows if r['kind'] in ('body', 'abstract')]
    blens = [r['style']['chars'] for r in body]
    heads = [p['text'].strip() for p, r in zip(paper, rows) if r['kind'] == 'heading']
    sub_heads = [h for h in heads if re.match(r'^（[一二三四五六七八九十]+）', h)]
    colon_pat = sum(1 for h in sub_heads if re.search(r'[：:]', h))
    tot_body = max(sum(blens), 1)
    cov_all = sum(r['cov'] * r['style']['chars'] for r in body) / tot_body if body else 0
    doc = dict(
        ai_rate=rate, report_kind=report['kind'], sections=report['summary'].get('sections'),
        body_paras=len(body), body_chars=sum(blens),
        para_len_cv=round(statistics.pstdev(blens) / statistics.mean(blens), 2) if len(blens) > 1 else None,
        sub_headings=len(sub_heads), sub_headings_with_colon_pattern=colon_pat,
        mapping_coverage=round(cov_all, 2),
        actions=Counter(r['action'] for r in rows if r['kind'] in ('body', 'abstract')),
        avg_risk_per100=round(statistics.mean([r['style']['risk_per100'] for r in body]), 2) if body else None,
        meta_end_paras=sum(r['style']['meta_end'] for r in body),
        enum3_total=sum(r['style']['enum3'] for r in body), seq_total=sum(r['style']['seq'] for r in body),
    )
    tier = None
    if rate is not None:
        tier = 'A-局部精修' if rate < 20 else ('B-重点段深改' if rate < 50 else 'C-全文重构')
    doc['tier'] = tier
    json.dump(dict(doc=doc, rows=rows), open(a.o, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    if a.md:
        L = ['# 诊断表', '', '## 全文', '']
        for k, v in doc.items():
            L.append('- **%s**: %s' % (k, json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v))
        if doc['mapping_coverage'] < 0.6 and report['kind'] == 'full':
            L += ['', '> ⚠️ 报告与论文匹配覆盖率低于 60%：报告可能不是这一版论文的检测结果，请向用户确认。']
        L += ['', '## 逐段', '', '| 段 | 类型 | 字数 | 显著 | 疑似 | 覆盖 | 文体分 | 高危词/100字 | 排比/序列/元收尾 | 句长均值/CV | 建议 | 开头 |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for r in rows:
            if r['kind'] not in ('body', 'abstract'):
                continue
            s = r['style']
            L.append('| P%d | %s | %d | %d%% | %d%% | %d%% | %.1f | %.1f %s | %d/%d/%d | %.0f/%.2f | **%s** | %s |' % (
                r['idx'], r['kind'], s['chars'], r['sig'] * 100, r['sus'] * 100, r['cov'] * 100, r['style_score'],
                s['risk_per100'], '、'.join(s['risk_top'][:4]), s['enum3'], s['seq'], s['meta_end'], s['sent_mean'], s['sent_cv'],
                r['action'], r['head'].replace('|', '｜')))
        open(a.md, 'w', encoding='utf8').write('\n'.join(L) + '\n')
    print('诊断完成: AI率=%s%%, 策略档=%s, 正文段=%d, 建议=%s, 报告匹配覆盖率=%.0f%%' % (
        rate, tier, len(body), dict(doc['actions']), doc['mapping_coverage'] * 100))


if __name__ == '__main__':
    main()
