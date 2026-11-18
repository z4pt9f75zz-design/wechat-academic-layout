"""docx → 纯文本（一段一行），纯标准库，不装 python-docx。

只取正文段落文本：`w:p` → 拼接其中所有 `w:t`，段内换行 `w:br` 当空格，`w:tab` 当空格。
表格里的段落也会被取到（按顺序展开成行），因为期刊导出的 docx 偶尔把摘要放表里。

用法：
    python3 scripts/docx2txt.py 论文.docx > 论文.txt
    python3 scripts/docx2txt.py 论文.docx 论文.txt
"""

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_bytes_to_text(data: bytes) -> str:
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    for p in root.iter(W + "p"):
        parts = []
        for node in p.iter():
            if node.tag == W + "t":
                parts.append(node.text or "")
            elif node.tag in (W + "br", W + "tab"):
                parts.append(" ")
        line = "".join(parts).strip()
        if line:
            out.append(line)
    return "\n".join(out) + "\n"


def docx_to_text(path) -> str:
    return docx_bytes_to_text(Path(path).read_bytes())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    text = docx_to_text(sys.argv[1])
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text, encoding="utf-8")
        print(f"{len(text.splitlines())} 段 / {len(text)} 字 → {sys.argv[2]}")
    else:
        sys.stdout.write(text)
