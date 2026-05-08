# ScholarPilot Design Brief

给 **Claude Design**(`claude.ai/design`)和本地 **frontend-design skill** 吃的素材包。

## 目录结构

```
design-brief/
├── README.md                   本文件
├── 01_design-system.css        从 frontend/src/assets/ 拷过来(使用时复制最新版)
├── 02_current-screenshots/     现有页面截图,给 Claude Design 看"目前长啥样"
├── 03_brand-brief.md           品牌基调,首次会话必喂
└── 04_page-specs/              每页一个规格,用到哪页喂哪份
    ├── dashboard.md
    ├── login.md
    └── project-view.md
```

## 使用流程

### 一次性(首次基调会话)

1. 打开 `claude.ai/design`,新建会话
2. 粘贴 `03_brand-brief.md` 全文作为第一条消息
3. 同时上传附件:
   - `01_design-system.css`(从 `../frontend/src/assets/design-system.css` 复制最新的)
   - `02_current-screenshots/` 下所有 PNG
4. 让 Claude Design 先吐一个 style guide 页,作为后续所有页面的视觉基线

### 每页迭代

1. **同一个 thread 里继续**,不要开新会话(保持基调)
2. 粘贴对应的 `04_page-specs/<page>.md`
3. 生成 HTML 原型,用 slider 微调
4. 点 "Share with Claude Code" → 复制 handoff instruction
5. 回到 Claude Code,贴给我,我翻译成 Vue + Element Plus 落到 `frontend/src/views/`

## 维护原则

- `01_design-system.css` **每次用前重新复制一次**,保证是最新的
- `02_current-screenshots/` 每次 UI 有显著变化后更新,否则 Claude Design 参考的是过期的
- `04_page-specs/` 当某页迭代完成后更新 spec,记录定稿后的决策
