# 项目目录规划

## 目标

该仓库既要保存 `gpt-image-2` 生成资产，又要为未来的 Vercel 山海经网站提供可直接消费的内容结构。

## 分层原则

- 原始数据和站点内容分开
- 站点运行时代码和静态资产分开
- 单个异兽的图片、提示词、元数据就近收纳
- 未来批量生成页面时，优先从结构化内容目录读取，而不是反向解析 Markdown

## 目录说明

- `content/creatures/<id-slug>/`
  - `entry.json`：异兽基础信息、展示描述、来源与资产索引
  - `prompt.*.txt`：出图时实际使用的 prompt 版本
- `public/images/creatures/<id-slug>/`
  - 存放最终入站图片
- `data/catalogs/`
  - 批量清单、总表、原始抓取结果
- `scripts/`
  - 抓取和数据构建逻辑
- `src/app/`
  - 未来首页、列表页、详情页路由
- `src/components/`
  - 卡片、画廊、筛选器、页头等 UI 组件
- `src/lib/`
  - 内容读取、数据转换、排序与搜索逻辑
- `src/styles/`
  - 全局样式和主题变量

## 内容约定

- 异兽目录统一采用 `三位编号 + 英文 slug`
- 站点图片采用稳定文件名，避免后续页面引用失效
- 每次生成新图时：
  1. 图片复制到 `public/images/creatures/...`
  2. prompt 存档到 `content/creatures/...`
  3. 更新对应 `entry.json`

