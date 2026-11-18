# 版式实测规格（design spec）

数据来源：公众号「比较文学与翻译研究」文章
《杨、霍〈红楼梦〉诗歌英译中的化境与事件化》（2026-10，转自《外国语文研究》）。
原始页面 `https://mp.weixin.qq.com/s/ZfVUjbrxtimmKuEjw2nhSw`，正文 HTML 快照见 `examples/source-article.html`。

测量方式：浏览器 `getComputedStyle` + `getBoundingClientRect`，视口 1400×739，内容区宽 **677px**、左边界 x=362。

## 1. 颜色

| 用途 | 原版值 | 说明 |
| --- | --- | --- |
| 主题色（竖条/标签底/小方块） | `#FFB497` | 浅橙，全文唯一强调色 |
| 标签浅底 | `#FFE8DF` | 主题色向白混约 66% |
| 正文文字 | `#7A4442` | 暖棕，长文阅读不刺眼 |
| 作者简介灰 | `#888888` | 14px |
| 摘要文字 | `#3F3F3F` | 14px |
| 角括号深色 | `#616360` | 摘要块左上角 |
| 细框线 | `#D0D0D0` | 正文框左/下 1px |
| 虚线框 | `#B5E8FC` | 作者卡（原版是浅蓝，和主题色不同族；本 skill 改为主题色同族浅色） |

## 2. 字号与行距

| 元素 | 原版 |
| --- | --- |
| 正文 | 16px / line-height 24.5px（≈1.53）/ letter-spacing 1.5px / `text-align:justify` |
| 大节标题文字 | 16px / bold / letter-spacing 1.5px |
| 小节标题（1.1、2.3） | 16px / bold / 与正文同色 |
| 作者简介 | 14px / lh 22.4px / 人名 bold |
| 摘要·关键词·基金 | 14px / lh 22.4px / `text-align:center` 容器内 p 为 justify + 2em 缩进 |
| 例句 | 14px 左右（原版是普通段落，本 skill 做成浅底卡） |

本 skill 采用 **16px / 1.75 / 1.5px** 作为正文基准——原版 1.53 在手机上偏挤，1.75 更接近当下公众号阅读习惯；其余结构尺寸照原版。

## 3. 组件结构（从上到下）

### 3.1 作者简介虚线卡

```html
<section style="padding:14px 16px 14px 24px;border:1px dashed <dash>;font-size:14px;line-height:1.7;letter-spacing:1.4px;color:#888">
```

原版：`border:1px dashed #B5E8FC`，内边距 `14px 14px 14px 25.2px`，宽 544，人名 bold。

### 3.2 摘要块（角括号）

原版做法：`display:inline-block` 的两段夹住正文 + 负边距 `-56px 0` 把文字压进括号行。

```html
<section style="margin:1.2em 0 0.6em">
  <section style="font-size:0;line-height:0;text-align:left">
    <section style="display:inline-block;width:72px;height:72px;border-top:2px solid <bracket>;border-left:2px solid <bracket>"></section>
    <section style="display:inline-block;width:14px;height:14px;background:<bracket>;margin-left:12px"></section>
  </section>
  <section style="margin:-52px 0;padding:0 18px;font-size:14px;line-height:1.8">…摘要/关键词/基金…</section>
  <section style="…text-align:right">…右下角极浅色方块 + 角括号…</section>
</section>
```

要点：`font-size:0;line-height:0` 必须加在角括号行，否则两个 inline-block 之间会多出空格；负边距是压叠的关键。

### 3.3 大节标题（色条 + 浅色标签）

原版：外层 `border-left:6px solid #FFB497; padding-left:6px`（高 30）；内层 `display:inline-block; padding:2px 12px; background:#FFE8DF`；文字 `16px/bold`。

### 3.4 大节正文框（开放方框）

原版：外层 `padding-left:5px`；内层 **只有 `border-left` + `border-bottom` 各 1px `#D0D0D0`**，`border-top/right:none`；内边距 `14px`；右下角 `19×6px` 主题色小方块 `float:right`。

### 3.5 例句卡

原版例句其实是普通段落（`[1] 原文：…／杨译：…／霍译：…`）。本 skill 做成浅色底卡（`background:<soft>`、14px、1.85 行距），相邻例句行合并成一块，便于手机端区分原文与译文。

### 3.6 结尾

- 居中 `END` + 下方 46×2px 主题色短线；
- 右下 `转自《外国语文研究》`，17px，`text-align:right`。

## 4. 主题色派生规则

生成器只接受一个主色 `accent`，其余由白/黑按比例混出，保证任意换色都不脏：

| token | 算法 | 用途 |
| --- | --- | --- |
| `tint` | 白 67% + accent 33% | 标签底、浅色块 |
| `soft` | 白 87% + accent 13% | 例句卡、引文底 |
| `line` | 白 78% + accent 22% | 细分隔线 |
| `dash` | 白 28% + accent 72% | 虚线框 |
| `bracket` | accent 压深 12% | 摘要角括号 |
| `deep` | accent 压深 25% | 标题文字 |

正文字色 `ink` 独立指定（原版 `#7A4442` 与 `#FFB497` 并不互为派生），所以 CLI 拆成 `--accent` 与 `--ink` 两个开关。

## 5. 微信/秀米兼容红线

- 只能内联 `style=`；`<style>`、`class`、`id`、`@media`、CSS 变量一律会被剥离。
- 结构统一用 `<section>`（`div` 偶有样式丢失）。
- 布局只用 `display:inline-block` / `float` / 负边距，**不用** flex、grid、position（微信编辑器会重排）。
- 图片必须带 `max-width:100%;height:auto`。
- 外链在正文里不可点，改为文末引用。
- 片段**不要**包含 `<html>`/`<body>`，公众号要的是正文片段。
