#!/usr/bin/env python3
"""改写后硬约束校验 + 文体特征前后对比。

用法: verify.py paper.json rewrites.md [--tol 0.15]
检查（FAIL=必须修，WARN=需人工判断）:
  FAIL  上标/引文编号 ^{...} 与 [N] 是否一个不少、一个不多
  FAIL  原段中≥8字的直接引文“……”是否逐字保留
  WARN  原段数字（年份、百分比、数量）是否都还在
  WARN  段落长度变化是否超出 ±tol
  WARN  改写后仍残留的高危特征（排比、序列词、元话语收尾、高危词密度）
退出码: 有 FAIL 时为 1。
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import style, style_score, RISK_WORDS  # noqa: E402
from docx_tool import parse_rewrites  # noqa: E402


def multiset_diff(a, b):
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    return list((ca - cb).elements()), list((cb - ca).elements())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paper'); ap.add_argument('rewrites'); ap.add_argument('--tol', type=float, default=0.15)
    a = ap.parse_args()
    paper = json.load(open(a.paper, encoding='utf8'))
    rw = parse_rewrites(a.rewrites)
    fails = warns = 0
    tot_old = tot_new = 0
    # 按"连续改写块"合并比较，允许段落拆分/合并/删除
    for k in sorted(rw):
        old = paper[k]['text']
        new = rw[k]
        deleted = new.strip() in ('(删除)', '（删除）')
        new_clean = '' if deleted else re.sub(r'\s+', '', new)
        msgs = []
        sup_o = re.findall(r'\^\{.*?\}', old); sup_n = re.findall(r'\^\{.*?\}', new_clean)
        br_o = re.findall(r'(?<!\^\{)\[\d+\]', re.sub(r'\^\{.*?\}', '', old))
        br_n = re.findall(r'(?<!\^\{)\[\d+\]', re.sub(r'\^\{.*?\}', '', new_clean))
        miss, extra = multiset_diff(sup_o + br_o, sup_n + br_n)
        if miss or extra:
            msgs.append(('FAIL', '引文编号不一致 缺:%s 多:%s' % (miss, extra)))
        for q in re.findall(r'“([^”]{8,})”', old):
            if re.sub(r'\s', '', q) not in new_clean:
                msgs.append(('FAIL', '直接引文被改动或丢失: “%s…”' % q[:20]))
        nums_o = re.findall(r'\d+(?:\.\d+)?%?', re.sub(r'\^\{.*?\}|\[\d+\]', '', old))
        nums_n = re.findall(r'\d+(?:\.\d+)?%?', re.sub(r'\^\{.*?\}|\[\d+\]', '', new_clean))
        miss_n, _ = multiset_diff(nums_o, nums_n)
        if miss_n:
            msgs.append(('WARN', '数字缺失: %s' % miss_n))
        lo = len(re.sub(r'\^\{.*?\}', '', old)); ln = len(re.sub(r'\^\{.*?\}', '', new_clean))
        tot_old += lo; tot_new += ln
        if not deleted and lo and abs(ln - lo) / lo > a.tol:
            msgs.append(('WARN', '长度 %d→%d (%+.0f%%)' % (lo, ln, (ln - lo) * 100 / lo)))
        if not deleted:
            so, sn = style(old), style(new_clean)
            resid = []
            if sn['enum3']: resid.append('顿号并列×%d' % sn['enum3'])
            if sn['seq']: resid.append('序列词×%d' % sn['seq'])
            if sn['meta_end']: resid.append('段尾元话语')
            if sn['risk_per100'] > 1.5: resid.append('高危词%.1f/100字(%s)' % (sn['risk_per100'], '、'.join(sn['risk_top'][:5])))
            if sn['long_sent']: resid.append('超长句×%d' % sn['long_sent'])
            if resid:
                msgs.append(('WARN', '残留特征: ' + '；'.join(resid)))
            info = '文体分 %.1f→%.1f | 句长CV %.2f→%.2f' % (style_score(so), style_score(sn), so['sent_cv'], sn['sent_cv'])
        else:
            info = '（删除）'
        f = sum(1 for m in msgs if m[0] == 'FAIL'); w = len(msgs) - f
        fails += f; warns += w
        print('P%-3d %s %s' % (k, '❌' if f else ('⚠️ ' if w else '✅'), info))
        for lvl, m in msgs:
            print('      [%s] %s' % (lvl, m))
    print('\n合计: %d 段, FAIL %d, WARN %d, 总字数 %d→%d (%+.1f%%)' % (
        len(rw), fails, warns, tot_old, tot_new, (tot_new - tot_old) * 100 / max(tot_old, 1)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
