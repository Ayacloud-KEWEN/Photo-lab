# LUMEN Studio — 架构决策记录

本文件记录实现过程中的重要架构决策，配合 [PROJECT_SPEC.md](PROJECT_SPEC.md) 阅读。
任何影响已有模块的变更都应先在此记录并经确认。

## 1. 分层

```
┌──────────────────────────────────────────────┐
│ desktop/src        React + TS (界面层)        │
│   └ api/           类型安全的 HTTP 客户端      │
├──────────────────────────────────────────────┤
│ desktop/src-tauri  Tauri 2 (桌面运行时)        │
│   ├ 原生对话框      tauri-plugin-dialog        │
│   └ backend.rs     启动/监控/关闭 Python 进程  │
├──────────────────────────────────────────────┤
│ backend/lumen      FastAPI (本地服务层)        │
│   ├ api/v1         路由：只做输入输出转换       │
│   ├ services       业务逻辑                   │
│   ├ db             连接、事务、迁移            │
│   └ core           配置、日志、鉴权            │
├──────────────────────────────────────────────┤
│ SQLite (WAL)       %LOCALAPPDATA%\LUMEN Studio │
└──────────────────────────────────────────────┘
```

## 2. 前后端通信（ADR-001）

- Tauri 在启动时生成一次性随机令牌，以子进程方式启动 Python 后端，
  通过环境变量传入 `LUMEN_TOKEN`、`LUMEN_DATA_DIR`、`LUMEN_ALLOWED_ORIGINS`。
- 后端只允许绑定回环地址（`127.0.0.1` / `::1`），端口为 0（由操作系统随机分配）。
- 后端开始监听后，向 **stdout** 输出一行 JSON 握手消息：
  `{"event": "ready", "port": 52341, "pid": 1234}`。stdout 只用于握手，日志走 stderr 和日志文件。
- 前端通过 Tauri 命令 `backend_status` 获取 `baseUrl` 与令牌，之后直接用 `fetch` 调用 API，
  每个请求携带 `Authorization: Bearer <token>`。
- CORS 只允许 Tauri 的来源（`http://tauri.localhost`、开发服务器 `http://localhost:1420`）。
- 生命周期：
  - 后端监听 stdin，stdin 关闭（Tauri 退出或崩溃）即优雅退出。
  - Windows 下子进程被放入 Job Object（`KILL_ON_JOB_CLOSE`），防止残留进程。

## 3. 数据目录（ADR-002）

- 默认 `%LOCALAPPDATA%\LUMEN Studio\`（而非 `%APPDATA%`）：数据库与以后的缩略图缓存体积可能很大，
  不适合随漫游配置文件同步。
- 结构：`lumen.db`、`logs/backend.log`、`backups/`（迁移前自动备份）。
- 可用 `LUMEN_DATA_DIR` 覆盖。

## 4. 数据库迁移（ADR-003）

- 不使用 ORM / Alembic，使用标准库 `sqlite3` 与自写的轻量迁移器：
  - 迁移文件位于 `backend/lumen/db/migrations/NNNN_name.sql`，按编号升序执行。
  - `schema_migrations` 记录版本、名称、SHA-256 校验和与执行时间。
  - 每个迁移在单独事务中执行，失败整体回滚。
  - 已执行迁移的文件被修改 → 拒绝启动（防止静默漂移）。
  - 数据库版本高于程序已知版本 → 拒绝启动（防止旧程序打开新库）。
  - 对已有数据的数据库执行新迁移前，先用 SQLite 备份 API 备份到 `backups/`。
- 每个连接启用 `foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout`。

## 5. 数据模型要点（ADR-004）

- **逻辑资产与物理文件分离**：`media_assets`（一张照片/一段视频）↔ `media_files`（磁盘上的文件）。
  RAW+JPEG 是同一个资产下的两个文件（`file_role` = `primary` / `companion`），XMP 为 `sidecar`。
- **路径存储为"根目录 + 相对路径"**：外接硬盘换盘符或整体移动时只需更新 `storage_roots.path`。
  `storage_roots.volume_serial` 用于将来识别重新接入的硬盘。
- **大小写不敏感的唯一性**：Windows 路径用 `path_key`（`normcase` 后）做唯一约束。
- **根目录不允许嵌套**：避免同一文件被重复索引。
- **元数据按文件存储**（`media_metadata.file_id`），记录提取器名称与版本，便于升级后重新提取。
- 删除存储根目录只删除数据库记录（级联删除其文件记录与任务），**绝不触碰磁盘文件**。
- 注册根目录时在同一事务中创建一个 `scan_storage_root` 待执行任务，供 Phase 2 的扫描器消费。

## 6. 前端（ADR-005）

- Tailwind CSS v4 + shadcn/ui（组件以源码形式放在 `src/components/ui`，`components.json` 保留以便后续用 CLI 添加组件）。
- 国际化：i18next，语言顺序 `zh-CN`（默认）→ `en` → `fr`，语言偏好暂存于 localStorage。
- API 类型由后端 OpenAPI 生成（`npm run gen:api` → `src/api/schema.d.ts`），避免手写类型漂移。
- 纯浏览器开发模式（无 Tauri）下，可通过 `VITE_LUMEN_API_URL` / `VITE_LUMEN_API_TOKEN` 连接独立运行的后端，
  目录选择退化为手动输入路径。仅限开发构建。

## 7. 打包（待 Phase 1 之后完成）

- 正式版用 PyInstaller 将后端打包为 `lumen-backend.exe`，作为 Tauri `externalBin` 随安装包分发。
- 开发模式直接使用 `backend/.venv` 中的 Python 运行 `python -m lumen`。
