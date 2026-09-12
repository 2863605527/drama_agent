# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 语义化版本。

## [Unreleased]

### 新增
- P0 安全三件套：
  - 生产环境 JWT 弱/占位/过短密钥直接拒绝启动（默认口令硬化）
  - JWT 吊销机制：`users.token_version` + payload `ver`，改密 / 退出所有设备后旧 token 立即失效
  - 新增 `POST /api/auth/change-password`、`POST /api/auth/logout-all`
  - `/assets` 媒体资源访问签名（HMAC 短时签名，无签名/过期/篡改 403；`ASSET_SIGN_DISABLED=1` 可整体关闭）
- 前端稳定性：
  - 全局错误边界（连续渲染异常整页兜底，单次仅 toast，不再白屏）
  - 日志流增量渲染（DOM 窗口 500 条，store 保留全量，防长任务卡顿）
- 测试工程：
  - 前端 Vitest 单测（task store 核心 getters）
  - CI MySQL 8 矩阵（建表/补列/CRUD 兼容性真实验证）
  - CI Playwright E2E 冒烟（注册 → 工作台 → 未配置拦截 → 通道教程）
  - 后端 JWT 吊销 / 资产签名 / MySQL 兼容专项测试
- 治理：
  - 审计日志表 `audit_logs`（注册/登录/改密/登出/删任务/保存通道）
  - `scripts/compress_assets.py` 媒体资产压缩工具（可选运行）
  - Dependabot 自动依赖更新

### 变更
- `ChannelConfigDialog.vue` 通道字段元数据抽离至 `frontend/src/config/channelFields.js`
- 前端通道字段改为手动配置（图片/视频模型可手填任意最新模型），移除「系统默认(.env)」选项

## [1.0.0] - 初始企业化版本
- 登录/注册/用户通道配置（LLM/图片/视频，CV/ARK/HTTP）
- 短剧多集续写、分段式渲染、SSE 实时日志、人工断点审核
- 任务对账（重启恢复悬挂任务）、资产生命周期 GC
- 飞书登录态/录音、灰度通道、限流、Fernet 加密 Key
