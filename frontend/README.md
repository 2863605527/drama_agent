# Drama-Agent 前端工程（Vue 3 + Vite）

短剧自动生成系统的企业级前端（Vue 3 + Vite + Pinia + Vue Router）。左侧「项目对话栏」管理任务会话与个人通道配置，右侧「工程执行栏」可视化整条短剧生产流水线。

## 技术栈

| 类别 | 选型 |
|---|---|
| 框架 | Vue 3（`<script setup>` 组合式 API） |
| 构建 | Vite 5 |
| 状态管理 | Pinia |
| 路由 | Vue Router 4（history 模式 + 登录守卫） |
| 请求 | Axios（token 拦截 / 401 自动跳登录 / 中文错误提取） |
| 样式 | 原生 CSS 设计令牌（深色豆包风，无重型 UI 库依赖） |

## 目录结构

```
frontend/
├── index.html
├── vite.config.js          # dev 代理 /api→127.0.0.1:8010；产物输出 app-assets（避开后端 /assets）
├── package.json
└── src/
    ├── main.js
    ├── App.vue             # 根组件 + 全局 toast
    ├── styles/global.css   # 设计系统（颜色/按钮/输入/徽章/动画）
    ├── router/index.js     # 路由表 + 全局登录守卫
    ├── api/                # request 封装 + auth/channel/task 接口
    ├── stores/             # Pinia：auth / channel / task / toast
    ├── utils/format.js     # 状态/时间/选项等纯函数
    ├── layouts/MainLayout.vue       # 左栏 + 右工作区布局
    ├── views/
    │   ├── LoginView.vue           # 登录 / 注册
    │   └── WorkspaceView.vue       # 右侧工程执行栏（组合各业务面板）
    └── components/
        ├── AppSidebar.vue          # 左：品牌/新建/任务会话列表/用户区/通道入口
        ├── ChannelConfigDialog.vue # 通道配置弹窗（LLM/图片/视频 × CV/ARK/HTTP）
        └── workspace/              # 流水线步骤、日志、剧本、资产、审核、片段、合成
```

## 开发与构建

```bash
# 1. 安装依赖（Node 18+，已在 Node 20 验证）
cd frontend
npm install

# 2. 开发模式（默认 5173，/api 自动代理到后端 8010）
npm run dev
# 浏览器打开 http://127.0.0.1:5173

# 3. 生产构建（产物在 frontend/dist，由 FastAPI 自动托管）
npm run build
```

构建后直接启动后端（默认 8010），访问 `http://127.0.0.1:8010/` 即加载本前端；
未匹配的前端路由（如刷新 `/login`）由后端 SPA 回退到 `index.html`。

> 资源目录刻意命名为 `app-assets/`：后端已把素材目录挂载在 `/assets`（图片/视频），
> 若前端产物也放 `/assets` 会被后端素材静态服务优先匹配而 404。

## 三大核心功能

### 1. 登录与个人信息
- 登录 / 注册一体页，JWT 存 `localStorage`，路由守卫拦截未登录访问。
- 左下角用户区显示当前账号，可一键退出。

### 2. 通道 / 模型 / Key 自主配置
- 左下角「模型通道」打开配置弹窗，分 **大模型 / 图片 / 视频** 三段。
- 每段可选：系统默认（.env）、火山即梦 CV（AK/SK + req_key）、火山方舟 ARK（Key + 模型）、通用 HTTP。
- 模型下拉、分辨率、宽高比等全部由后端 `GET /api/channels/meta` 动态下发，前端不硬编码。
- Key 等敏感字段回显为掩码，留空表示不修改；保存时后端 Fernet 加密落库。
- 「连通测试」：LLM 发极简真实请求，图片/视频校验凭据完整性（不烧额度）。
- 配置在**提交任务时快照**到该任务，任务执行全程使用快照，事后改配置不影响在跑任务。

### 3. 豆包式工作台
- 左栏：新建短剧、任务会话列表（标题 + 状态徽章）、当前三段通道摘要。
- 右栏：流水线步骤条 → 实时 SSE 日志 → 剧本 → 角色/昼夜场景资产（生成/重绘/上传替换/编辑）
  → 人工审核断点 → 片段/分镜视频（配音方式切换、分镜编辑、重生成）→ 合成成片与下载。

## 与后端的接口约定

- 业务接口统一前缀 `/api`，除 SSE 外均用 `Authorization: Bearer <token>`。
- SSE 进度流：`GET /api/task/stream/{task_id}?token=`（EventSource 无法自定义头，token 走 query）。
- 图片替换：`POST /api/task/{id}/replace_image`（multipart/form-data）。
