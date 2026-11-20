#!/usr/bin/env python3
"""对比两轮检测：哪些段从标红变成未标识（有效改法），哪些改了仍标红（无效改法）。

用法: compare_rounds.py <旧轮目录> <新轮目录> [--md out.md]
  每个目录需含 paper.json 与 analysis.json（第1步生成）。
用途: 从用户自己论文的真实复测结果里学习"什么改法对这篇论文/这个检测器有效"，
      指导下一轮改写，而不是只凭经验规则。
"""
import argparse, difflib, json, os


def load(d):
    return (json.load(open(os.path.join(d, 'paper.json'), encoding='utf8')),
            json.load(open(os.path.join(d, 'analysis.json'), encoding='utf8'))['rows'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('old'); ap.add_argument('new'); ap.add_argument('--md')
    a = ap.parse_args()
    p1, r1 = load(a.old); p2, r2 = load(a.new)
    body1 = [i for i, r in enumerate(r1) if r['kind'] in ('body', 'abstract')]
    groups = {'有效（标红→未标识）': [], '无效（改了仍标红）': [], '变差（未标识→标红）': [], '未改动仍标红': []}
    for r in r2:
        if r['kind'] not in ('body', 'abstract'):
            continue
        t2 = p2[r['idx']]['text']
        j = max(body1, key=lambda i: difflib.SequenceMatcher(None, p1[i]['text'], t2, autojunk=False).quick_ratio())
        sim = difflib.SequenceMatcher(None, p1[j]['text'], t2, autojunk=False).ratio()
        o, n = r1[j]['sig'], r['sig']
        item = dict(old=j, new=r['idx'], sig_old=o, sig_new=n, sim=round(sim, 2), old_text=p1[j]['text'], new_text=t2)
        changed = sim < 0.9
        if o >= 0.5 and n < 0.2:
            groups['有效（标红→未标识）'].append(item)
        elif o >= 0.5 and n >= 0.5 and changed:
            groups['无效（改了仍标红）'].append(item)
        elif o < 0.2 and n >= 0.5:
            groups['变差（未标识→标红）'].append(item)
        elif o >= 0.5 and n >= 0.5:
            groups['未改动仍标红'].append(item)
    L = ['# 两轮对比', '']
    for g, items in groups.items():
        L.append('- %s：%d 段' % (g, len(items)))
    for g in ('有效（标红→未标识）', '变差（未标识→标红）', '无效（改了仍标红）'):
        if not groups[g]:
            continue
        L += ['', '## ' + g, '']
        for it in groups[g][:12]:
            L += ['### 旧P%d(%d%%) → 新P%d(%d%%) 相似度%.2f' % (it['old'], it['sig_old'] * 100, it['new'], it['sig_new'] * 100, it['sim']),
                  '- 旧：' + it['old_text'][:300], '- 新：' + it['new_text'][:300], '']
    out = '\n'.join(L) + '\n'
    if a.md:
        open(a.md, 'w', encoding='utf8').write(out)
    print('\n'.join(L[:6]))


if __name__ == '__main__':
    main()
