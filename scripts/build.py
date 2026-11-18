#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat-academic-layout / build.py
把一篇文章（markdown / 纯文本 / 复制来的 html）排成微信公众号正文 HTML（全内联样式）。

用法：
  python3 build.py article.md --theme peach -o dist
  python3 build.py article.txt --accent "#8FB3C7" --ink "#23384A"
  python3 build.py page.html --theme sage --with-title --list-theme-frags

产物：
  dist/<slug>.html          公众号正文片段（全内联样式，可直接粘贴 / 发给草稿箱脚本）
  dist/<slug>-preview.html  多主题预览页（切主题 + 一键复制 HTML 到剪贴板）
  dist/<slug>.md            归一化后的结构化稿（方便手改再重跑）
"""

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

from clean import clean_text
from docx2txt import docx_bytes_to_text

# --------------------------------------------------------------------------
# 配色：一个主题色 + 墨水色，其余派生
# --------------------------------------------------------------------------

THEMES = {
    "peach": {"label": "学术暖橙（原版）", "accent": "#FFB497", "ink": "#7A4442"},
    "ink":   {"label": "墨青",             "accent": "#9DB8C9", "ink": "#2B3F4E"},
    "sage":  {"label": "松绿",             "accent": "#A7C4A0", "ink": "#33472F"},
    "clay":  {"label": "陶土",             "accent": "#D7A28C", "ink": "#6B3B2E"},
    "sand":  {"label": "沙金",             "accent": "#DCC9A0", "ink": "#4A3F2A"},
    "mono":  {"label": "素灰",             "accent": "#C4BFB9", "ink": "#3A3A3A"},
}

FONT = ("-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
        "'Microsoft YaHei',Arial,sans-serif")


def _rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(t):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in t)


def _mix(c1, c2, t):
    """t = c2 的权重"""
    a, b = _rgb(c1), _rgb(c2)
    return _hex(tuple(a[i] * (1 - t) + b[i] * t for i in range(3)))


def tokens(theme="peach", accent=None, ink=None):
    base = THEMES.get(theme)
    if base is None:
        raise SystemExit(f"未知主题 {theme}，可选：{', '.join(THEMES)}")
    acc = accent or base["accent"]
    nk = ink or base["ink"]
    label = base["label"]
    if accent or ink:
        label = f"自定义 {acc.upper()}"
    return {
        "label": label,
        "accent": acc.upper(),
        "tint": _mix("#FFFFFF", acc, 0.33).upper(),      # 标题色块底
        "soft": _mix("#FFFFFF", acc, 0.13).upper(),      # 极浅底
        "line": _mix("#D2D0CD", acc, 0.10).upper(),      # 细灰线
        "dash": _mix("#FFFFFF", acc, 0.72).upper(),      # 虚线框
        "ink": nk.upper(),                               # 正文色
        "deep": _mix(nk, "#000000", 0.15).upper(),
        "gray": "#8A8A8A",
        "faint": "#3F3F3F",
        "bracket": "#5F5E5C",
    }


# --------------------------------------------------------------------------
# 输入 → 结构化块
# --------------------------------------------------------------------------

TERM = "。！？…”』」》〉!?."
H2_ZH = re.compile(r"^(?:[一二三四五六七八九十]+[、．.]\s*)")
H2_NUM = re.compile(r"^\d{1,2}[、．.]\s*(?!\d)")
H3_NUM = re.compile(r"^\d{1,2}\.\d{1,2}[、．.]?\s*")
H3_ZH = re.compile(r"^[（(][一二三四五六七八九十]+[）)]\s*")
EXAMPLE = re.compile(r"^\s*(?:例\s*\[\d+\](?:\s*(?:原文|原诗|译文|原词))?\s*[:：]?|\[\d+\]\s*(?:原文|原诗|原词)|"
                     r"原文[:：]|原诗[:：]|杨译[:：]|霍译[:：]|译文[:：])")
META_LABELS = ("内容摘要", "摘要", "关键词", "关键字", "基金项目", "项目基金", "作者简介",
               "译者简介", "转自", "来源", "本文首发", "原文刊载")


class _TextExtractor(htmllib.HTMLParser if False else object):
    pass


def html_to_text(src: str) -> str:
    """html → 带加粗标记的纯文本。加粗用 \x02 … \x03 包裹。"""
    from html.parser import HTMLParser

    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote",
             "section", "article", "table"}
    BOLD_TAGS = {"strong", "b"}

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out = []
            self.bold_stack = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag in ("script", "style"):
                self.skip += 1
                return
            if tag == "br":
                self.out.append("\n")
            elif tag == "img":
                s = a.get("src", "")
                alt = a.get("alt", "") or ""
                if s:
                    self.out.append(f"\n![]({s})\n")
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "tr"):
                self.out.append("\n\n")
                if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    self.bold_stack.append(True)
                    self.out.append("\x02")
            elif tag in BOLD_TAGS:
                self.bold_stack.append(True)
                self.out.append("\x02")
            elif tag == "span" and re.search(r"font-weight:\s*(bold|700|bolder)",
                                             a.get("style", ""), re.I):
                self.bold_stack.append(True)
                self.out.append("\x02")
            elif tag in ("td", "th"):
                self.out.append(" ")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip = max(0, self.skip - 1)
                return
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                if self.bold_stack:
                    self.bold_stack.pop()
                self.out.append("\x03\n\n")
            elif tag in BOLD_TAGS:
                if self.bold_stack:
                    self.bold_stack.pop()
                self.out.append("\x03")
            elif tag == "span":
                if self.bold_stack:
                    self.bold_stack.pop()
                    self.out.append("\x03")

        def handle_data(self, data):
            if self.skip:
                return
            self.out.append(data)

    p = P()
    p.feed(src)
    txt = "".join(p.out)
    txt = txt.replace("\x03\x02", "")
    txt = re.sub(r"\x02+", "\x02", txt)
    txt = re.sub(r"\x03+", "\x03", txt)
    txt = re.sub(r"[ \t]*\n[ \t]*", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    for a, b in (("&nbsp;", " "), ("\u00a0", " ")):
        txt = txt.replace(a, b)
    return htmllib.unescape(txt)


BOILERPLATE = ("预览时标签不可点", "继续滑动看下一个", "向上滑动看下一个", "轻触阅读原文",
               "微信扫一扫", "长按识别二维码", "点击蓝字 关注我们", "点击上方蓝字",
               "滑动查看下一张", "写下你的留言", "阅读原文", "分享收藏点赞在看")


def clean_line(s: str) -> str:
    s = s.rstrip().replace("\t", " ")
    s = re.sub(r"^[\s\u3000]+", "", s)
    # 中文引号/括号两侧的多余空格
    cjk = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef“”‘’—…"
    s = s.replace("\x03\x02", "")
    s = re.sub(rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", s)
    s = re.sub(r"[ ]{2,}", " ", s)
    s = re.sub(r"(?<=\d) (?=[\u4e00-\u9fff])", "", s)   # 4 种 → 4种
    s = re.sub(r"(?<=[\u4e00-\u9fff]) (?=%)", "", s)
    # 整行 **加粗** → 加粗控制符，供 is_heading 识别为大节/小节标题
    m = re.match(r"^\*\*(.+?)\*\*$", s.strip())
    if m and "**" not in m.group(1):
        s = "\x02" + m.group(1).strip() + "\x03"
    return _balance_marks(s.strip())


def _balance_marks(s: str) -> str:
    """修复不配对的加粗标记，避免控制字符漏进正文"""
    out, opened, mark_at = [], False, -1
    for ch in s:
        if ch == "\x02":
            if not opened:
                opened, mark_at = True, len(out)
                out.append(ch)
        elif ch == "\x03":
            if opened:
                opened = False
                out.append(ch)
        else:
            out.append(ch)
    if opened and mark_at >= 0:
        out.pop(mark_at)
    return "".join(out)


def is_heading(line: str):
    """返回 (level, text) 或 None；level: h2 大节 / h3 小节"""
    t = line.strip()
    # 加粗整行 = 大节标题（公众号复制过来的标题多为 <strong>）
    if t.startswith("\x02") and t.endswith("\x03") and t.count("\x02") == 1:
        inner = re.sub(r"[\x02\x03]", "", t).strip()
        if inner and len(inner) <= 46 and not re.search(r"[。；，,]$", inner):
            return ("h3" if (H3_NUM.match(inner) or H3_ZH.match(inner)) else "h2", inner)
    if not t or len(t) > 60:
        return None
    if t.startswith("#"):
        m = re.match(r"^(#{1,6})\s*(.+)$", t)
        if m:
            lv = len(m.group(1))
            return ("h1" if lv <= 2 else "h3", m.group(2).strip())
    if H3_NUM.match(t) and len(t) < 46:
        return ("h3", t)
    if H3_ZH.match(t) and len(t) < 30:
        return ("h3", t)
    if H2_ZH.match(t) and len(t) < 40:
        return ("h2", t)
    if H2_NUM.match(t) and len(t) < 40:
        return ("h2", t)
    if t in ("引言", "绪论", "结论", "结语", "余论", "参考文献", "注释"):
        return ("h2", t)
    return None


def parse_frontmatter(text: str):
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            body = text[end + 4:]
            for ln in head.splitlines():
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    meta[k.strip().lower()] = v.strip().strip('"').strip("'")
            return meta, body.lstrip("\n")
    return meta, text


def parse(text: str, merge=True, max_para_chars=0):
    """文本 → {meta, title, blocks}"""
    fm, text = parse_frontmatter(text)
    raw_lines = text.splitlines()

    blocks = []
    buf = []
    example_buf = []

    def flush_para():
        nonlocal buf
        if buf:
            joined = "".join(buf) if merge else "\n".join(buf)
            for chunk in split_long(joined, max_para_chars):
                blocks.append({"t": "p", "text": chunk})
            buf = []

    def flush_example():
        nonlocal example_buf
        if example_buf:
            blocks.append({"t": "example", "lines": example_buf})
            example_buf = []

    for raw in raw_lines:
        line = clean_line(raw)
        if re.match(r"^\d+(?:\.\d+)*[\u4e00-\u9fa5]", line):
            line = re.sub(r"^(\d+(?:\.\d+)*)", r"\1 ", line)
        if not line or line.strip(" \x02\x03") in BOILERPLATE:
            flush_para(); flush_example()
            continue
        if re.match(r"^[-*_]{3,}$", line):
            flush_para(); flush_example(); blocks.append({"t": "hr"}); continue

        # 图片
        m = re.match(r"^!\[(.*?)\]\((.*?)\)$", line)
        if m:
            flush_para(); flush_example()
            blocks.append({"t": "img", "alt": m.group(1), "src": m.group(2)}); continue
        m = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", line)
        if m:
            flush_para(); flush_example()
            blocks.append({"t": "img", "alt": "", "src": m.group(1)}); continue

        # 列表
        m = re.match(r"^[-*•]\s+(.*)$", line)
        if m:
            flush_para(); flush_example()
            if blocks and blocks[-1]["t"] == "list":
                blocks[-1]["items"].append(m.group(1))
            else:
                blocks.append({"t": "list", "items": [m.group(1)]})
            continue
        m = re.match(r"^\d{1,2}[.)]\s+(.{0,40})$", line)
        if m and not H3_NUM.match(line):
            pass  # 交给标题判断，否则按普通段落

        h = is_heading(line)
        if h:
            lv, txt = h
            flush_para(); flush_example()
            blocks.append({"t": lv, "text": txt})
            continue

        if line.startswith(">"):
            flush_para(); flush_example()
            blocks.append({"t": "quote", "text": clean_line(line.lstrip("> "))})
            continue

        if any(plain(line).startswith(lbl) for lbl in META_LABELS) and len(plain(line)) < 16 \
                and not re.search(r"[:：]", plain(line)):
            # 「内容摘要」这类小标题
            flush_para(); flush_example()
            blocks.append({"t": "metalabel", "text": plain(line)}); continue

        if EXAMPLE.match(line):
            flush_para()
            example_buf.append(line)
            continue

        # 普通段落：续行合并
        if merge and buf and not buf[-1].endswith(tuple(TERM)) and len(buf[-1]) > 12:
            buf.append(line)
        else:
            if buf and merge:
                flush_para()
            buf.append(line)

    flush_para(); flush_example()

    merged = []
    for b in blocks:
        if b["t"] == "example" and merged and merged[-1]["t"] == "example":
            merged[-1]["lines"].extend(b["lines"])
        else:
            merged.append(b)
    blocks = merged

    # ---- 从 blocks 里拣出元信息（标题、作者、摘要、关键词、基金、来源）----
    meta = dict(fm)
    if "title" not in meta:
        for b in blocks:
            if b["t"] == "h1":
                meta["title"] = plain(b["text"])
                blocks = [x for x in blocks if x is not b]
                break

    labels = (
        ("abstract", ("内容摘要", "摘要")),
        ("keywords", ("关键词", "关键字")),
        ("fund", ("基金项目", "项目基金", "基金课题", "基金")),
        ("authors", ("作者简介", "译者简介", "作者信息")),
        ("source", ("转自", "来源", "本文首发", "原文刊载", "转载自")),
    )
    rest, seen_heading = [], False
    for b in blocks:
        if b["t"] in ("h2", "h3"):
            seen_heading = True
        if b["t"] == "metalabel":
            b = {"t": "h3", "text": b["text"]}
        if b["t"] in ("p", "h3"):
            t = plain(b["text"]).strip()
            hit = None
            for key, pre in labels:
                if any(t.startswith(x) for x in pre):
                    hit = key
                    break
            if hit is None and b["t"] == "p" and not seen_heading and len(t) < 260 \
                    and not meta.get("authors"):
                if re.search(r"研究方向|主要从事", t) or \
                        (re.search(r"大学|学院|研究院|研究所", t) and
                         re.search(r"教授|副教授|讲师|博士|研究生导师|硕士生导师", t)):
                    hit = "authors"
            if hit:
                meta[hit] = (meta[hit] + "\n" + t).strip() if meta.get(hit) else t
                continue
        rest.append(b)
    blocks = rest

    for key in ("authors", "abstract", "keywords", "fund", "source"):
        if meta.get(key):
            meta[key] = "\n".join(plain(x) for x in meta[key].split("\n") if x.strip())

    return meta, blocks


def split_long(text, limit):
    if not limit or len(text) <= limit:
        return [text]
    out, cur = [], ""
    for sent in re.split(r"(?<=[。！？])", text):
        if len(cur) + len(sent) > limit and cur:
            out.append(cur); cur = sent
        else:
            cur += sent
    if cur:
        out.append(cur)
    return out


# --------------------------------------------------------------------------
# 结构化块 → 微信 HTML
# --------------------------------------------------------------------------

class Renderer:
    def __init__(self, tk, with_title=False):
        self.tk = tk
        self.with_title = with_title

    # ---- 基础 ----
    def p(self, text, indent=True, cls="p"):
        tk = self.tk
        style = (f"margin:0 0 1.05em;font-size:16px;line-height:1.75;letter-spacing:1.5px;"
                 f"color:{tk['ink']};text-align:justify;"
                 + ("text-indent:2em;" if indent else ""))
        return f'<p style="{style}">{inline(text)}</p>'

    def h3(self, text):
        tk = self.tk
        style = (f"margin:1.7em 0 0.7em;font-size:16px;font-weight:bold;line-height:1.75;"
                 f"letter-spacing:1.5px;color:{tk['ink']};text-align:justify;text-indent:2em;")
        return f'<p style="{style}">{inline(text)}</p>'

    def h2_pill(self, text):
        tk = self.tk
        return (
            f'<section style="margin:2.2em 0 0 6px;padding-left:6px;border-left:6px solid {tk["accent"]};'
            f'text-align:left;">'
            f'<section style="display:inline-block;padding:3px 12px;background:{tk["tint"]};'
            f'font-size:16px;font-weight:bold;line-height:1.6;letter-spacing:1.5px;'
            f'color:{tk["deep"]};text-align:left;">{inline(text)}</section></section>'
        )

    def box_open(self):
        tk = self.tk
        return (f'<section style="margin:0 0 0.4em 5px;">'
                f'<section style="border-left:1px solid {tk["line"]};'
                f'border-bottom:1px solid {tk["line"]};padding:14px 14px 6px;">')

    def box_close(self):
        tk = self.tk
        return (f'<section style="text-align:right;font-size:0;line-height:0;margin:2px 0 0;">'
                f'<section style="display:inline-block;width:19px;height:6px;'
                f'background:{tk["accent"]};"></section></section>'
                f'</section></section>')

    # ---- 组件 ----
    NAME = re.compile(r"(^|。|；)\s*([\u4e00-\u9fa5]{2,4})(?=（|，)")

    def author_card(self, text):
        tk = self.tk
        # 人名加粗（「张三，某大学…」「张三（某大学…」）
        body = "<br>".join(inline(x) for x in text.split("\n") if x.strip())
        body = self.NAME.sub(
            lambda m: m.group(1) + '<strong style="font-weight:bold;color:%s;">%s</strong>'
            % (tk["gray"], m.group(2)), body)
        return (f'<section style="margin:1.4em 0 1em;padding:14px 16px 14px 24px;'
                f'border:1px dashed {tk["dash"]};font-size:14px;line-height:1.7;'
                f'letter-spacing:1.4px;color:{tk["gray"]};text-align:justify;">'
                f'{body}</section>')

    def abstract_block(self, inner):
        tk = self.tk
        b = tk["bracket"]
        softline = _mix("#FFFFFF", b, 0.18)
        return (
            f'<section style="margin:1.2em 0 0.6em;">'
            f'<section style="font-size:0;line-height:0;text-align:left;">'
            f'<section style="display:inline-block;width:72px;height:72px;vertical-align:top;'
            f'border-top:2px solid {b};border-left:2px solid {b};"></section>'
            f'<section style="display:inline-block;width:14px;height:14px;'
            f'background:{b};margin-left:12px;vertical-align:top;"></section></section>'
            f'<section style="margin:-52px 0;padding:0 18px;font-size:14px;line-height:1.8;'
            f'letter-spacing:1.4px;color:{tk["faint"]};text-align:justify;">{inner}</section>'
            f'<section style="font-size:0;line-height:0;text-align:right;">'
            f'<section style="display:inline-block;width:14px;height:14px;'
            f'background:{softline};margin-right:12px;vertical-align:bottom;"></section>'
            f'<section style="display:inline-block;width:72px;height:72px;vertical-align:bottom;'
            f'border-bottom:2px solid {softline};border-right:2px solid {softline};"></section>'
            f'</section></section>'
        )

    def quote(self, text):
        tk = self.tk
        return (f'<section style="margin:0 0 1.05em;padding:12px 16px;background:{tk["soft"]};'
                f'border-left:3px solid {tk["accent"]};font-size:15px;line-height:1.8;'
                f'letter-spacing:1.4px;color:{tk["faint"]};text-align:justify;">'
                f'{inline(text)}</section>')

    def example(self, lines):
        tk = self.tk
        body = "<br>".join(inline(x) for x in lines)
        return (f'<section style="margin:0 0 1.05em;padding:12px 16px;background:{tk["soft"]};'
                f'font-size:14px;line-height:1.85;letter-spacing:1.3px;color:{tk["ink"]};'
                f'text-align:justify;">{body}</section>')

    def img(self, src, alt=""):
        tk = self.tk
        cap = (f'<section style="margin-top:6px;font-size:12px;line-height:1.6;'
               f'letter-spacing:1px;color:{tk["gray"]};text-align:center;">{inline(alt)}</section>'
               if alt else "")
        return (f'<section style="margin:0 0 1.3em;text-align:center;">'
                f'<img src="{htmllib.escape(src)}" style="max-width:100%;height:auto;display:block;'
                f'margin:0 auto;border-radius:2px;" />{cap}</section>')

    def ul(self, items):
        tk = self.tk
        lis = "".join(
            f'<p style="margin:0 0 0.5em;font-size:16px;line-height:1.75;letter-spacing:1.5px;'
            f'color:{tk["ink"]};text-align:justify;padding-left:3.2em;text-indent:-1.2em;">'
            f'·  {inline(x)}</p>' for x in items)
        return f'<section style="margin:0 0 1em;">{lis}</section>'

    def hr(self):
        tk = self.tk
        return (f'<section style="margin:1.8em 0;text-align:center;font-size:0;line-height:0;">'
                f'<section style="display:inline-block;width:40px;height:1px;'
                f'background:{tk["line"]};vertical-align:middle;"></section>'
                f'<section style="display:inline-block;width:6px;height:6px;margin:0 8px;'
                f'background:{tk["accent"]};vertical-align:middle;"></section>'
                f'<section style="display:inline-block;width:40px;height:1px;'
                f'background:{tk["line"]};vertical-align:middle;"></section></section>')

    def end_mark(self):
        tk = self.tk
        return (f'<section style="margin:2.4em 0 1em;text-align:center;">'
                f'<section style="display:inline-block;font-size:13px;letter-spacing:8px;'
                f'color:{tk["gray"]};text-indent:8px;">END</section>'
                f'<section style="width:46px;height:2px;background:{tk["accent"]};'
                f'margin:8px auto 0;"></section></section>')

    # ---- 文档 ----
    def render(self, meta, blocks):
        tk = self.tk
        out = []
        has_title = bool(meta.get("title")) and self.with_title
        if has_title:
            out.append(
                f'<section style="margin:0 0 0.4em;text-align:center;">'
                f'<section style="font-size:19px;font-weight:bold;line-height:1.55;'
                f'letter-spacing:1.2px;color:{tk["deep"]};text-align:center;">'
                f'{inline(meta["title"])}</section></section>')
            sub = meta.get("authors_short") or ""
            if sub:
                out.append(f'<section style="margin:0 0 1.2em;text-align:center;font-size:13px;'
                           f'letter-spacing:1.2px;color:{tk["gray"]};">{inline(sub)}</section>')

        # 作者简介
        if meta.get("authors"):
            out.append(self.author_card(meta["authors"]))

        # 摘要 + 关键词 + 基金
        abs_inner = []
        for key in ("abstract", "keywords", "fund"):
            if meta.get(key):
                txt = meta[key]
                if key == "abstract" and not re.match(r"^(内容摘要|摘要)", txt):
                    txt = "内容摘要：" + txt
                abs_inner.append(
                    f'<p style="margin:0 0 0.7em;text-align:justify;text-indent:2em;">'
                    f'{bold_lead(txt)}</p>')
        if abs_inner:
            out.append(self.abstract_block("".join(abs_inner)))

        # 正文
        opened = False
        pending_hr = False
        for b in blocks:
            t = b["t"]
            if t == "h2":
                if opened:
                    out.append(self.box_close()); opened = False
                out.append(self.h2_pill(b["text"]))
                out.append(self.box_open()); opened = True
            elif t == "h3":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.h3(b["text"]))
            elif t == "p":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.p(b["text"]))
            elif t == "quote":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.quote(b["text"]))
            elif t == "example":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.example(b["lines"]))
            elif t == "list":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.ul(b["items"]))
            elif t == "img":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.img(b["src"], b.get("alt", "")))
            elif t == "hr":
                if not opened:
                    out.append(self.box_open()); opened = True
                out.append(self.hr())
        if opened:
            out.append(self.end_mark())
            out.append(self.box_close())

        if meta.get("source") and not meta.get("source_in_body"):
            out.append(f'<section style="margin:1em 0 0;text-align:right;font-size:13px;'
                       f'letter-spacing:1.2px;color:{tk["gray"]};">{inline(meta["source"])}</section>')

        return (f'<section style="font-family:{FONT};font-size:16px;line-height:1.75;'
                f'letter-spacing:1.5px;color:{tk["ink"]};text-align:justify;'
                f'word-break:break-word;">' + "".join(out) + '</section>')


def plain(text):
    return re.sub(r"[\x02\x03]", "", text or "")


def bold_lead(txt):
    """把「内容摘要：」这类开头标签加粗，其余按行内规则处理"""
    m = re.match(r"^(\s*)([^：:\s]{1,8}[：:])", txt or "")
    if not m:
        return inline(txt)
    return (m.group(1) + '<strong style="font-weight:bold;">'
            + htmllib.escape(m.group(2), quote=False) + "</strong>" + inline(txt[m.end():]))


def inline(text):
    """轻量行内处理：\x02\x03 / **粗体** / ==高亮=="""
    s = htmllib.escape(text, quote=False)
    s = s.replace("\x02", '<strong style="font-weight:bold;">').replace("\x03", "</strong>")
    s = re.sub(r"\*\*(.+?)\*\*", r'<strong style="font-weight:bold;">\1</strong>', s)
    s = re.sub(r"==(.+?)==", r'<span style="border-bottom:2px solid currentColor;">\1</span>', s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
    return s


# --------------------------------------------------------------------------
# 产物
# --------------------------------------------------------------------------

def slugify(s, fallback="article"):
    s = (s or "").strip()
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:40].strip("-") or fallback)


def normalized_md(meta, blocks):
    out = []
    if meta.get("title"):
        out.append(f"# {meta['title']}\n")
    for key, label in (("authors", "作者简介"), ("abstract", "内容摘要"),
                       ("keywords", "关键词"), ("fund", "基金项目")):
        if meta.get(key):
            out.append(f"{meta[key]}\n")
    out.append("")
    for b in blocks:
        t = b["t"]
        if t == "h2":
            out.append(f"\n## {b['text']}\n")
        elif t == "h3":
            out.append(f"\n### {b['text']}\n")
        elif t == "p":
            out.append(f"{b['text']}\n")
        elif t == "quote":
            out.append(f"> {b['text']}\n")
        elif t == "example":
            out.extend(b["lines"]); out.append("")
        elif t == "list":
            out.extend(f"- {x}" for x in b["items"]); out.append("")
        elif t == "img":
            out.append(f"![{b.get('alt','')}]({b['src']})\n")
        elif t == "hr":
            out.append("---\n")
    return "\n".join(out)


PREVIEW = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 公众号排版预览</title>
<style>
  :root { --bd:#e6e3df; }
  * { box-sizing:border-box; }
  body { margin:0; background:#f4f2ef; font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
  .bar { position:sticky; top:0; z-index:9; background:#fffdfb; border-bottom:1px solid var(--bd);
         padding:10px 16px; display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
  .bar b { font-size:13px; color:#666; font-weight:600; margin-right:4px; }
  .chip { border:1px solid var(--bd); background:#fff; border-radius:999px; padding:5px 12px;
          font-size:13px; cursor:pointer; color:#444; display:flex; align-items:center; gap:6px; }
  .chip i { width:10px; height:10px; border-radius:50%; display:inline-block; flex:0 0 auto; }
  #chips { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .bar { align-items:center; }
  .chip.on { border-color:#333; color:#111; font-weight:600; }
  .btn { border:1px solid #333; background:#333; color:#fff; border-radius:8px; padding:7px 14px;
         font-size:13px; cursor:pointer; }
  .btn.ghost { background:#fff; color:#333; }
  .stage { padding:24px 12px 60px; }
  .paper { width:677px; max-width:100%; margin:0 auto; background:#fff; padding:28px 22px;
           box-shadow:0 1px 3px rgba(0,0,0,.06); border-radius:2px; }
  .panel { display:none; }
  .panel.active { display:block; }
  .hint { width:677px; max-width:100%; margin:0 auto 10px; font-size:12px; color:#8a857f; line-height:1.7; }
  .toast { position:fixed; left:50%; bottom:28px; transform:translateX(-50%) translateY(8px);
           background:#333; color:#fff; font-size:13px; padding:9px 16px; border-radius:8px;
           opacity:0; transition:.2s; pointer-events:none; }
  .toast.on { opacity:1; transform:translateX(-50%) translateY(0); }
</style></head>
<body>
<div class="bar">
  <b>主题色</b><span id="chips"></span>
  <span style="flex:1"></span>
  <button class="btn" id="copyBtn">复制正文 HTML</button>
  <button class="btn ghost" id="copyPlain">复制纯文本</button>
  <button class="btn ghost" id="dlBtn">下载片段</button>
</div>
<div class="stage">
  <div class="hint">粘贴到 <b>秀米</b> 或 <b>公众号后台</b> 时用「复制正文 HTML」；若浏览器拦截剪贴板，请在页面里 Ctrl/Cmd+A 全选正文后复制。</div>
  <div class="paper" id="paper">__PANELS__</div>
</div>
<div class="toast" id="toast"></div>
<script>
const panels = [...document.querySelectorAll('.panel')];
const chips = document.getElementById('chips');
let cur = 0;
panels.forEach((p, i) => {
  const c = document.createElement('button');
  c.className = 'chip' + (i === 0 ? ' on' : '');
  c.innerHTML = '<i style="background:' + p.dataset.accent + '"></i>' + p.dataset.label;
  c.onclick = () => {
    panels.forEach(x => x.classList.remove('active'));
    [...chips.children].forEach(x => x.classList.remove('on'));
    p.classList.add('active'); c.classList.add('on'); cur = i;
  };
  chips.appendChild(c);
});
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  setTimeout(() => t.classList.remove('on'), 1600);
}
function frag() { return panels[cur].querySelector('.wx-body'); }
document.getElementById('copyBtn').onclick = async () => {
  const node = frag();
  const htmlStr = node.innerHTML, textStr = node.innerText;
  try {
    await navigator.clipboard.write([new ClipboardItem({
      'text/html': new Blob([htmlStr], { type: 'text/html' }),
      'text/plain': new Blob([textStr], { type: 'text/plain' })
    })]);
    toast('已复制，去秀米 / 公众号后台粘贴');
  } catch (e) {
    const r = document.createRange(); r.selectNodeContents(node);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    document.execCommand('copy');
    toast('已复制（兼容模式）');
  }
};
document.getElementById('copyPlain').onclick = async () => {
  try { await navigator.clipboard.writeText(frag().innerText); toast('已复制纯文本'); }
  catch (e) { toast('复制失败，请手动选择'); }
};
document.getElementById('dlBtn').onclick = () => {
  const blob = new Blob([frag().innerHTML], { type: 'text/html;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '__SLUG__-' + panels[cur].dataset.theme + '.html';
  a.click();
};
</script>
</body></html>
"""


def build(inp: Path, theme: str, accent, ink, out_dir: Path, with_title: bool,
          merge: bool, max_para: int, all_themes: bool, title_override=None, clean=True,
          keywords=None):
    if inp.suffix.lower() == ".docx":
        raw = docx_bytes_to_text(inp.read_bytes())
    else:
        raw = inp.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"<(p|section|div|span|img)\b", raw, re.I) and re.search(r"</p>|<br|<section", raw, re.I):
        raw = html_to_text(raw)
    clean_report = None
    if clean:
        raw, clean_report = clean_text(raw, keywords=keywords)
    meta, blocks = parse(raw, merge=merge, max_para_chars=max_para)

    if clean_report and clean_report.get("title"):
        meta.setdefault("title", clean_report["title"])
    if title_override:
        meta["title"] = title_override
    title = meta.get("title") or inp.stem
    slug = slugify(title, inp.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    themes = list(THEMES) if all_themes else [theme]
    if accent or ink:
        themes = [theme]

    frag_path = out_dir / f"{slug}.html"
    tk0 = tokens(theme, accent, ink)
    main = Renderer(tk0, with_title=with_title)
    frag = main.render(meta, blocks)
    frag_path.write_text(
        f"<!-- 公众号正文片段 · 主题 {tk0['label']} · 由 wechat-academic-layout 生成 -->\n{frag}",
        encoding="utf-8")

    panels = []
    for th in themes:
        tk = tokens(th, accent, ink) if th == theme else tokens(th)
        r = Renderer(tk, with_title=with_title)
        body = r.render(meta, blocks) if th != theme else frag
        panels.append(
            f'<section class="panel{" active" if th == themes[0] else ""}" '
            f'data-theme="{th}" data-label="{tk["label"]}" data-accent="{tk["accent"]}">'
            f'<div class="wx-body">{body}</div></section>')

    preview = (PREVIEW
               .replace("__TITLE__", htmllib.escape(title))
               .replace("__SLUG__", slug)
               .replace("__PANELS__", "\n".join(panels)))
    prev_path = out_dir / f"{slug}-preview.html"
    prev_path.write_text(preview, encoding="utf-8")

    md_path = out_dir / f"{slug}.md"
    md_path.write_text(normalized_md(meta, blocks), encoding="utf-8")

    # 统计
    n_p = sum(1 for b in blocks if b["t"] == "p")
    n_h2 = sum(1 for b in blocks if b["t"] == "h2")
    n_h3 = sum(1 for b in blocks if b["t"] == "h3")
    words = sum(len(b.get("text", "") or "".join(b.get("lines", []) if b["t"] == "example" else ""))
                for b in blocks)
    return {
        "slug": slug, "title": title, "fragment": str(frag_path), "preview": str(prev_path),
        "md": str(md_path), "paragraphs": n_p, "h2": n_h2, "h3": n_h3,
        "chars": words, "theme": tk0["label"],
        **({"clean": clean_report} if clean_report else {}),
    }


def main():
    ap = argparse.ArgumentParser(description="公众号学术排版生成器")
    ap.add_argument("input", help="markdown / txt / html 文件；用 - 表示从标准输入读（配合 pbpaste）")
    ap.add_argument("--theme", default="peach", help=f"主题：{', '.join(THEMES)}")
    ap.add_argument("--accent", help="自定义主题色，如 #7FA8B8（覆盖 theme 的 accent）")
    ap.add_argument("--ink", help="自定义正文字色，如 #333333")
    ap.add_argument("-o", "--out", default="dist", help="输出目录")
    ap.add_argument("--with-title", action="store_true", help="正文顶部也排一个标题（粘到秀米时用）")
    ap.add_argument("--no-merge", action="store_true", help="不做硬换行合并")
    ap.add_argument("--max-para", type=int, default=0, help="超长段落自动断段字数，0 关闭")
    ap.add_argument("--all-themes", action="store_true", help="预览页内置全部主题")
    ap.add_argument("-t", "--title", help="文章标题（正文 h1 / 文件名用）")
    ap.add_argument("--clean", dest="clean", action="store_true", default=True,
                    help="自动清洗：删目录/英文摘要/参考文献注释/脚注「注」字，拆粘连标题（默认开）")
    ap.add_argument("--no-clean", dest="clean", action="store_false",
                    help="关掉自动清洗，原样排版")
    ap.add_argument("--keywords", help='手动指定关键词，用「；」分隔，覆盖自动断词')
    ap.add_argument("--list-themes", action="store_true")
    args = ap.parse_args()

    if args.list_themes:
        for k, v in THEMES.items():
            print(f"{k:6s} {v['label']:12s} accent={v['accent']} ink={v['ink']}")
        return

    if args.input == "-":
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="wxlayout-")) / "stdin.txt"
        tmp.write_text(sys.stdin.read(), encoding="utf-8")
        args.input = str(tmp)

    res = build(Path(args.input), args.theme, args.accent, args.ink, Path(args.out),
                args.with_title, not args.no_merge, args.max_para, args.all_themes,
                title_override=args.title, clean=args.clean, keywords=args.keywords)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
