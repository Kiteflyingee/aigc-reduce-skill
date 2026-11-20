# aigc-reduce-skill

一个面向中文学术论文的 Agent Skill（兼容 Antigravity / Claude Code 等支持 `SKILL.md` 的 Agent）：输入论文 `.docx` 和知网 AIGC 检测报告 `.pdf`（全文报告单或简洁报告单），自动解析标红/疑似位置并映射回论文段落，诊断 AI 特征成因，按总 AI 率分档给出改写方案并实施，校验引文/数字零改动后回写保留原格式的 `.docx`，并支持多轮复测对比以迭代调整策略。

## 功能概览

1. **解析报告（`scripts/parse_report.py`）**：自动识别知网 **全文报告单**（带颜色标注）与 **简洁报告单**，提取总 AI 特征值、各章节比例及逐字显著/疑似等级。
2. **段落抽取与格式保留回写（`scripts/docx_tool.py`）**：仅使用 Python 标准库操作 OOXML，抽取段落（保留上标引文 `^{[N]}`），改写后回写保留原段落样式与字体；支持生成**改写段标黄核对版**（`--mark`）和**试点章节送检测试稿**（`--excerpt`）。
3. **映射与文体诊断（`scripts/analyze.py`）**：将报告标色映射回论文段落（自动校验报告与论文版本是否匹配），统计高危抽象词密度、顿号并列、序列词、段尾元话语、句长变异系数等指标，按总 AI 率自动分档（A `<20%` / B `20–50%` / C `≥50%`）。
4. **硬约束校验（`scripts/verify.py`）**：改写后强制校验上标引文编号与 ≥8 字直接引文一字未动，检查数字缺失、长度波动及残留高危特征。
5. **跨轮对比（`scripts/compare_rounds.py`）**：复测后自动对比两轮报告，区分"标红→未标识（有效改法）"与"改了仍标红（无效改法）"，以论文自身的真实复测结果指导下一轮改写。

## 目录结构

```text
aigc-reduce-skill/
├── SKILL.md                  # Agent Skill 主指令与完整工作流
├── references/
│   └── playbook.md           # 改写手册（分档策略、段落/全文层手法、自检清单）
├── scripts/
│   ├── parse_report.py       # 解析知网 AIGC 检测报告 PDF
│   ├── docx_tool.py          # .docx 段落抽取与保格式回写
│   ├── analyze.py            # 报告映射 + 文体诊断 + 分档建议
│   ├── verify.py             # 引文/数字硬约束校验
│   └── compare_rounds.py     # 两轮复测效果对比
├── LICENSE
└── README.md
```

## 环境依赖

- **Python 3.8+**（仅需标准库，无需 `pip install` 第三方包）
- **poppler**（提供 `pdftohtml` 用于解析报告 PDF）
  - macOS: `brew install poppler`
  - Ubuntu/Debian: `sudo apt-get install poppler-utils`

## 安装与使用

### 作为 Agent Skill 使用

将本仓库克隆到你的项目或全局 Skills 目录：

```bash
# 项目级（Antigravity / 通用 .agents 规范）
git clone https://github.com/Kiteflyingee/aigc-reduce-skill.git .agents/skills/aigc-reduce

# 或全局 Skills 目录（按所用工具路径调整）
git clone https://github.com/Kiteflyingee/aigc-reduce-skill.git ~/.gemini/config/skills/aigc-reduce
```

在对话中直接提供论文 `.docx` 和知网检测报告 `.pdf`（优先使用**全文报告单**），告诉 Agent：

> 用 `aigc-reduce` 分析这篇论文和检测报告，给出降 AIGC 方案并实施。

### 单独运行脚本

```bash
# 1. 解析检测报告与论文
python3 scripts/parse_report.py report.pdf -o report.json
python3 scripts/docx_tool.py extract paper.docx -o paper.json

# 2. 映射并生成诊断表
python3 scripts/analyze.py paper.json report.json -o analysis.json --md analysis.md

# 3. 校验改写稿（rewrites.md）
python3 scripts/verify.py paper.json rewrites.md

# 4. 保格式回写（可加 --mark 标黄，--excerpt 仅导出改写章节作送检测试稿）
python3 scripts/docx_tool.py apply paper.docx rewrites.md -o paper_revised.docx
python3 scripts/docx_tool.py apply paper.docx rewrites.md -o paper_excerpt.docx --excerpt

# 5. 复测后对比两轮效果
python3 scripts/compare_rounds.py round1/ round2/ --md compare.md
```

## 说明与边界

- 本工具仅改写表达方式，**不改变论点、事实、数据、直接引文原文与文献编号**，且不替作者编造任何案例、调研或数据。
- AIGC 检测器为概率统计模型，不同论文、学科与检测器版本存在波动；对于高 AI 率稿件，建议先试点改写单个章节送检验证，并在关键位置补充作者本人的真实调研、案例或课堂/田野观察材料。

## License

[MIT](./LICENSE)
