#!/usr/bin/env python3
"""公众号粘贴兼容性体检：检查生成的正文片段是否「微信 / 秀米」双端安全。

用法：
    python3 scripts/check.py dist/我的文章.html
    python3 scripts/check.py dist/            # 检查目录下所有 .html（跳过 preview）

退出码：0 = 通过（可能带警告）；1 = 有错误，需要修。
"""
from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ALLOWED_TAGS = {
    "section", "p", "span", "strong", "b", "em", "i", "br", "img", "a",
    "ul", "ol", "li", "blockquote", "table", "thead", "tbody", "tr", "td", "th",
    "div", "h1", "h2", "h3", "h4", "hr", "sup", "sub",
}
# 这些标签微信会保留但容易掉样式，仅提示
SOFT_TAGS = {"div", "h1", "h2", "h3", "h4", "table", "tr", "td", "th", "blockquote"}
FORBIDDEN_IN_VALUE = ("position:", "position :", "z-index", "animation", "transform",
                      "@media", "@import", "calc(")


class Auditor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.tags: dict[str, int] = {}
        self.styleless: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if tag not in ALLOWED_TAGS:
            self.errors.append(f"不支持的标签 <{tag}>（微信可能整段丢弃）")
        if tag in SOFT_TAGS:
            self.warns.append(f"<{tag}> 在微信编辑器里偶有样式丢失，建议统一用 <section>")
        for bad in ("class", "id"):
            if bad in a:
                self.errors.append(f"<{tag}> 带 {bad}={a[bad]!r}：微信会剥离，样式必须全内联")
        style = a.get("style", "")
        if tag not in ("br", "img", "hr") and not style:
            self.styleless.append(f"<{tag}>")
        for k in a:
            if k.startswith("on"):
                self.errors.append(f"<{tag}> 带事件属性 {k}：微信会清除")
        low = style.lower()
        for bad in FORBIDDEN_IN_VALUE:
            if bad in low:
                self.errors.append(f"<{tag}> style 含微信不支持的写法：{bad}")
        if "var(--" in low:
            self.errors.append(f"<{tag}> style 用了 CSS 变量：粘贴后会失去颜色")
        if "!important" in low:
            self.warns.append(f"<{tag}> style 用了 !important，微信会忽略")
        if tag == "img":
            if not a.get("src"):
                self.errors.append("<img> 缺 src")
            if "max-width" not in low:
                self.warns.append("<img> 建议加 max-width:100%;height:auto 防止窄屏溢出")
        if tag == "a" and a.get("href", "").startswith("http") and "mp.weixin" not in a.get("href", ""):
            self.warns.append("外部链接在公众号正文里不可点击，建议在文末列出引用")

    def handle_data(self, data):
        if "\x02" in data or "\x03" in data:
            self.errors.append("正文残留内部加粗标记 \\x02/\\x03")


def audit(path: Path) -> tuple[list[str], list[str], dict]:
    raw = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warns: list[str] = []

    if "<html" in raw.lower() or "<body" in raw.lower():
        errors.append("片段里出现 <html>/<body>：公众号要的是正文片段，不是整页")
    if re.search(r"<style[\s>]", raw, re.I):
        errors.append("出现 <style> 块：微信会整段剥离，样式必须内联")
    if re.search(r"<script[\s>]", raw, re.I):
        errors.append("出现 <script>：微信直接清除")
    if re.search(r"class\s*=", raw):
        errors.append("出现 class=：微信会剥离，样式必须内联")
    if "var(--" in raw:
        errors.append("出现 CSS 变量 var(--…)：换主题只能在生成时完成")
    if re.search(r"@media|@import|@keyframes", raw):
        errors.append("出现 @media/@import/@keyframes：微信不支持")
    if re.search(r"url\(\s*['\"]?(?!data:)", raw):
        warns.append("出现外部 url() 资源：微信可能加载失败，图标建议用文字/色块")

    # 只取正文片段部分（去掉生成器注释）
    body = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    aud = Auditor()
    aud.feed(body)
    errors += aud.errors
    warns += aud.warns
    if aud.styleless:
        uniq = sorted(set(aud.styleless))
        warns.append(f"{len(aud.styleless)} 个标签没有内联样式（如 {', '.join(uniq[:5])}）")

    info = {
        "file": str(path),
        "bytes": len(raw.encode("utf-8")),
        "chars": len(raw),
        "colors": len(set(re.findall(r"#[0-9A-Fa-f]{6}", raw))),
        "tags": aud.tags,
    }
    if info["chars"] > 300_000:
        warns.append("片段超过 30 万字符，公众号可能保存失败，建议拆篇")
    return errors, warns, info


def main() -> int:
    ap = argparse.ArgumentParser(description="公众号正文片段体检")
    ap.add_argument("target", help="html 文件或目录")
    args = ap.parse_args()

    t = Path(args.target)
    files = sorted(p for p in t.glob("*.html") if "preview" not in p.name) if t.is_dir() else [t]
    if not files:
        print("没有找到待检查的 html")
        return 1

    bad = 0
    for f in files:
        errors, warns, info = audit(f)
        print(f"\n=== {f.name} ===")
        print(f"  字符 {info['chars']} · 颜色 {info['colors']} 种 · 标签 {len(info['tags'])} 类")
        top = sorted(info["tags"].items(), key=lambda x: -x[1])[:6]
        print("  " + "  ".join(f"{k}×{v}" for k, v in top))
        for e in errors:
            print(f"  ✗ {e}")
        for w in warns[:12]:
            print(f"  ! {w}")
        if len(warns) > 12:
            print(f"  … 另有 {len(warns) - 12} 条提示")
        if not errors:
            print("  ✓ 通过（警告不影响粘贴）")
        bad += 1 if errors else 0

    print(f"\n合计 {len(files)} 个文件，{bad} 个有错误")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
