#!/usr/bin/env bash
# 把本仓库安装为「全局」DSH 技能：~/ .dsh/skills/wechat-academic-layout
# 用法：./install.sh
# 只想装给单个项目：把本目录复制到 <项目根>/.dsh/skills/ 下即可，目录名保持 wechat-academic-layout。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HOME}/.dsh/skills/wechat-academic-layout"

mkdir -p "$(dirname "$DEST")"
if [ -d "$DEST" ]; then
  echo "已存在 $DEST，先备份到 ${DEST}.bak"
  rm -rf "${DEST}.bak"
  mv "$DEST" "${DEST}.bak"
fi

cp -R "$SRC" "$DEST"
rm -rf "$DEST/.git" "$DEST/docs"

echo "已安装到 $DEST"
echo "新开一个会话即可生效；试排："
echo "  python3 \"$DEST/scripts/build.py\" \"$DEST/examples/demo.md\" --theme sage --with-title -o /tmp/wxdemo"
