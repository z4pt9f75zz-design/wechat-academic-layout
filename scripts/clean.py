"""文章清洗：把知网/期刊导出或网页粘贴来的整篇论文，压成「能直接排版」的干净稿。

解决的问题（顺序即处理顺序）：
  1. 期刊信息头 `标题 (期刊) 中国比较文学 2026 (04)` → 抽标题，改写成文末「来源：《…》2026年第4期」
  2. 目录整块删掉（顺带把它当作大节标题字典，用来精确切分后面粘连的标题）
  3. 「标题 + 作者 + 单位 + 摘要：…」被挤成一段 → 拆成摘要行，作者单位单独一行
  4. 英文标题 / Abstract / Keywords 整段删掉
  5. 粘连标题（`一、xxx 正文…`）拆成 标题行 + 正文行，标题加粗便于识别
  6. 正文里的脚注标记「注」（`；注二是…`、`。注然而…`）删掉，保留「注释」「关注」「注定」等真词
  7. 参考文献 / 注释 / References 等尾部整块删掉
  8. 网页 UI 噪声（研学工具、顶部、引证文献 笔记…）删掉
  9. 输出时每段之间空一行，避免排版器把相邻段合并；例句行保持紧邻以便合并成例句卡

只依赖标准库。对外主函数：clean_text(text) -> (text, report)
"""

import re

CJK = r"\u4e00-\u9fa5"

# 元信息行首标签（这些行永远不参与「粘连标题拆分」「注字删除」）
META_RE = re.compile(
    r"^(内容摘要|摘要|关键词|关键字|基金项目|项目基金|基金课题|基金|作者简介|译者简介|作者信息"
    r"|转自|来源|本文首发|原文刊载|转载自|收稿日期|DOI|中图分类号|文献标识码|文章编号)\s*[:：]"
)

# 目录里的条目：一、二、三 / （一）/ 1. / 结论：/ 结语
HEAD_ZH = re.compile(r"^[一二三四五六七八九十]+\s*[、.．]\s*")
HEAD_PAREN = re.compile(r"^[（(][一二三四五六七八九十]+[）)]\s*")
HEAD_WORD = re.compile(r"^(引言|绪论|结语|结论|余论|小结|尾论|代结语|参考文献|注释|致谢|目录)\s*[:：]?")

TAIL_RE = re.compile(
    r"^(参考文献|引用文献|征引文献|参考书目|注释|注\s*释|尾注|脚注"
    r"|References|REFERENCES|Bibliography|BIBLIOGRAPHY|Works\s+Cited|Notes|NOTES)\b"
)

NOISE_RE = re.compile(
    r"^(研学工具|顶部|底部|分享|收藏|点赞|在看|预览时标签不可点|微信扫一扫|长按识别"
    r"|参考文献\s*引证文献\s*注释\s*笔记|\d{1,3})$"
)

ENGLISH_HEAD_RE = re.compile(r"^(Abstract|ABSTRACT|Key\s*words?|Keywords?|KEYWORDS?)\s*[:：]", re.I)

# 「注」是真词的情况：注+这些字不删
NOTE_KEEP = "释意目明定解重入册视脚记疏家水关销资射述音"

# 例句行：这类行要彼此紧邻，不能被空行隔开
EXAMPLE_RE = re.compile(r"^(例\s*\[?\d+\]?\s*[:：]|原文\s*[:：]|译文\s*[:：]|[杨霍苏许林辜]\S{0,3}译\s*[:：])")


KEYWORD_LABEL = re.compile(r"^(关键词|关键字)\s*[:：]\s*(.*)$")
KEYWORD_SEP = re.compile(r"[；;、，,／/|｜]+")
STOP_START = "与和的在而以及之为是等及了着其此该"


def _kw_dp(chunk, body, maxlen=12, p=2.5, q=0.2, fmin=2):
    """在 chunk 上做 DP 切词，返回词列表；切不动返回 None。"""
    n = len(chunk)
    NEG = -1e18
    dp = [NEG] * (n + 1)
    pre = [-1] * (n + 1)
    dp[0] = 0.0
    for i in range(n):
        if dp[i] == NEG:
            continue
        for j in range(i + 1, min(n, i + maxlen) + 1):
            seg = chunk[i:j]
            if not seg.isascii():
                if len(seg) < 2 or seg[0] in STOP_START:
                    continue
            f = body.count(seg)
            if f < fmin:
                continue
            sc = (len(seg) ** p) * (f ** q)
            if dp[i] + sc > dp[j]:
                dp[j] = dp[i] + sc
                pre[j] = i
    if dp[n] == NEG:
        return None
    out, k = [], n
    while k > 0:
        i = pre[k]
        out.append(chunk[i:k])
        k = i
    return out[::-1]


def split_keywords(s, body):
    """把「印度英语纳萨尔小说底层南方启蒙先锋后卫知识分子裂隙式联结」切成词。

    有分隔符就直接用；没有时：先在书名号前切开（`庞德《华夏集》` → 庞德 | 《华夏集》），
    再在每个块里用「长度^2.5 × 文中出现次数^0.3」做 DP（词组要在正文里出现过 ≥2 次），
    切不动的块整块保留。
    """
    s = (s or "").strip()
    if not s:
        return [], False
    if KEYWORD_SEP.search(s):
        return [x.strip() for x in KEYWORD_SEP.split(s) if x.strip()], False
    cuts = set()
    for i, ch in enumerate(s):
        if ch == "《" and i > 0:
            cuts.add(i)
    # 音译人名「理查德·赖特俳句」：点号后 2 个汉字收一名，若后半段也是正文里的词就在此切开
    dot = s.rfind("·")
    if dot > 0:
        k = dot + 3                      # · 后再 2 个汉字
        if len(s) - k >= 2 and s[:k] in body and s[k:k + 2] in body:
            cuts.add(k)
    chunks, cur = [], ""
    for i, ch in enumerate(s):
        if i in cuts and cur:
            chunks.append(cur)
            cur = ""
        cur += ch
    chunks.append(cur)
    out = []
    for c in chunks:
        r = _kw_dp(c, body) or _kw_dp(c, body, fmin=1)
        out += r if r else [c]
    return out, True


def _ascii_ratio(s: str) -> float:
    if not s:
        return 0.0
    letters = sum(1 for c in s if c.isascii() and c.isalpha())
    return letters / len(s)


def _strip_note_marks(s: str) -> str:
    """删脚注标记「注」：只删紧跟在标点后、且不是「注释/关注/注定」这类真词的。"""
    pat = re.compile(
        r"(?<=[；。，、：:！？）)\]】”’\s])注(?=[" + CJK + r"《（(“‘A-Za-z0-9]|[；。，、！？）]|$)"
    )

    def rep(m):
        nxt = s[m.end():m.end() + 1]
        return m.group(0) if (nxt and nxt in NOTE_KEEP) else ""

    return pat.sub(rep, s)


def _split_title_header(line: str):
    """`标题 (期刊) 中国比较文学 2026 (04)` → (标题, '来源：《中国比较文学》2026年第4期')"""
    m = re.match(r"^(?P<t>.+?)\s*[(（]期\s*刊[)）]\s*(?P<rest>.+)$", line)
    if not m:
        return None, None
    title = m.group("t").strip()
    rest = m.group("rest").strip()
    j = re.match(
        r"^(?P<j>.+?)\s*(?P<y>(?:19|20)\d{2})\s*年?\s*[（(]?\s*(?P<i>\d+)?\s*[)）]?\s*期?\s*$",
        rest,
    )
    if not j:
        return title, None
    journal = j.group("j").strip().strip("《》")
    year = j.group("y")
    issue = j.group("i")
    src = f"来源：《{journal}》{year}年" + (f"第{int(issue)}期" if issue else "")
    return title, src


def _heading_like(entry: str) -> bool:
    return bool(HEAD_ZH.match(entry) or HEAD_PAREN.match(entry)
                or re.match(r"^(结论|结语|引言|绪论|余论|小结|代结语)\s*[:：]", entry)
                or (HEAD_WORD.match(entry) and len(entry) < 40))


def _try_split_heading(line: str, entries):
    """粘连标题：返回 (heading, rest) 或 None。优先用目录条目精确匹配。"""
    for e in entries:
        if len(e) >= 4 and line.startswith(e) and len(line) > len(e) + 8:
            return e, line[len(e):].strip()
    # 通用：一、xxx 后面接一个空格再跟正文
    m = re.match(r"^([一二三四五六七八九十]+\s*[、.．][^。；！？]{3,45}?)\s+(?=[" + CJK + r"“《（])", line)
    if m and len(line) > m.end() + 15:
        return m.group(1).strip(), line[m.end():].strip()
    m = re.match(r"^([（(][一二三四五六七八九十]+[）)][^。；！？]{2,40}?)\s+(?=[" + CJK + r"“《（])", line)
    if m and len(line) > m.end() + 15:
        return m.group(1).strip(), line[m.end():].strip()
    m = re.match(r"^((?:结论|结语|引言|绪论|余论|小结)[:：][^。；！？]{2,40}?)\s+(?=[" + CJK + r"“《（])", line)
    if m and len(line) > m.end() + 15:
        return m.group(1).strip(), line[m.end():].strip()
    return None


def clean_text(text: str, keep_english=False, keywords=None):
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    report = {"toc_entries": 0, "dropped_toc": 0, "dropped_english": 0,
              "dropped_tail": 0, "dropped_noise": 0, "note_marks": 0,
              "split_headings": 0, "keywords_split": None, "title": None, "source": None}

    # ---- 1. 期刊信息头 ----
    source_line = None
    title_hint = None
    if lines:
        t, src = _split_title_header(lines[0])
        if t:
            title_hint = t
            report["title"] = t
            if src:
                source_line = src
                report["source"] = src
            lines = lines[1:]

    # ---- 2. 目录整块（顺便收标题字典）----
    toc, body = [], []
    in_toc = False
    for l in lines:
        if re.match(r"^(目录|目\s*录)(\s*目录)*$", l) or re.match(r"^目录\s*目录", l):
            in_toc = True
            rest = re.sub(r"^(目录\s*)+", "", l).strip()
            if rest:
                toc.append(rest)
            continue
        if in_toc:
            if len(l) > 70 or META_RE.match(l) or ENGLISH_HEAD_RE.match(l):
                in_toc = False          # 目录结束，这一行照常处理
            else:
                toc.append(l)
                continue
        body.append(l)
    entries = [e for e in toc if _heading_like(e)]
    report["toc_entries"] = len(entries)
    report["dropped_toc"] = len(toc) - len(entries)

    # ---- 3. 标题/作者/单位/摘要挤成一段 → 拆开 ----
    out = []
    author_line = None
    for l in body:
        m = re.search(r"(内容摘要|摘要)\s*[:：]", l)
        if m and m.start() > 0:
            prefix = l[:m.start()].strip()
            while title_hint and prefix.startswith(title_hint):
                prefix = prefix[len(title_hint):].strip()
            if prefix:
                parts = prefix.split(None, 1)
                author_line = parts[0] + ((" " + parts[1]) if len(parts) > 1 else "")
            out.append(l[m.start():].strip())
            continue
        out.append(l)
    body = out

    # ---- 4. 英文标题 / Abstract / Keywords ----
    kept = []
    in_front = True
    for l in body:
        if in_front and not META_RE.match(l):
            if ENGLISH_HEAD_RE.match(l) or (_ascii_ratio(l) > 0.5 and len(l) > 40):
                report["dropped_english"] += 1
                continue
            if len(l) > 120 and _ascii_ratio(l) < 0.2:
                in_front = False        # 正文开始（纯中文长段）
        kept.append(l)
    body = kept

    # ---- 5-8. 拆粘连标题 / 删注字 / 截尾部 / 删噪声 ----
    out = []
    started = False
    for l in body:
        if NOISE_RE.match(l):
            report["dropped_noise"] += 1
            continue
        if started and TAIL_RE.match(l) and (_ascii_ratio(l) > 0.25 or len(l) < 200):
            report["dropped_tail"] = 1
            break
        is_meta = bool(META_RE.match(l))
        if not is_meta:
            sp = _try_split_heading(l, entries if not started else [])
            if sp:
                head, rest = sp
                report["split_headings"] += 1
                out.append("**" + head + "**")
                l = rest
            elif _heading_like(l) and len(l) < 60 and not l.startswith("**"):
                out.append("**" + l + "**")
                if HEAD_ZH.match(l) or _heading_like(l):
                    started = True
                continue
        if not is_meta:
            new = _strip_note_marks(l)
            if new != l:
                report["note_marks"] += l.count("注") - new.count("注")
                l = new
        if not is_meta and len(l) > 120:
            started = True
        out.append(l)
    body = out

    # ---- 9. 作者单位行：有「作者简介」就不重复 ----
    if author_line:
        has_bio = any(META_RE.match(l) and l.startswith(("作者简介", "译者简介", "作者信息")) for l in body)
        name = author_line.split()[0]
        if has_bio and any(name in l for l in body if l.startswith(("作者简介", "译者简介"))):
            report["dropped_dup_author"] = True
        else:
            idx = 0
            for i, l in enumerate(body):
                if META_RE.match(l):
                    break
                idx = i + 1
            body.insert(idx, author_line)

    # ---- 8.5 关键词切词 ----
    if body and any(KEYWORD_LABEL.match(l) for l in body):
        vocab = "\n".join([title_hint or ""] + [l for l in body if not KEYWORD_LABEL.match(l)])
        new_body = []
        for l in body:
            m = KEYWORD_LABEL.match(l)
            if m:
                if keywords:
                    words, changed = [w.strip() for w in re.split(r"[；;、,，]", keywords) if w.strip()], True
                else:
                    words, changed = split_keywords(m.group(2), vocab)
                if words:
                    if changed:
                        report["keywords_split"] = "；".join(words)
                    l = m.group(1) + "：" + "；".join(words)
            new_body.append(l)
        body = new_body

    # 来源行放最后
    if source_line and not any(l.startswith(("来源", "转自", "原文刊载")) for l in body):
        body.append(source_line)

    # ---- 输出：段间空行，例句行紧邻 ----
    chunks = []
    for i, l in enumerate(body):
        chunks.append(l)
        if i < len(body) - 1:
            nxt = body[i + 1]
            chunks.append("\n" if (EXAMPLE_RE.match(l) or EXAMPLE_RE.match(nxt)) else "\n\n")
    return "".join(chunks) + "\n", report


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    src = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
    cleaned, rep = clean_text(src)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(cleaned, encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(cleaned[:1200])
