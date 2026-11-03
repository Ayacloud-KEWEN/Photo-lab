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

## 8. 媒体处理流水线（ADR-006，Phase 2）

```
storage_roots ──scan──▶ media_files (pending) ──ingest──▶ assets / metadata / renditions
                 快：只比对大小+mtime          慢：指纹 → 归组 → 元数据 → 缩略图
```

- **扫描**（`library/scan.py`）只读文件系统属性，按 `size + mtime_ns` 判断新增/修改/未变，
  每次扫描递增 `scan_generation`；扫描完整结束后，代数落后的文件标记为 `missing`（不删除）。
  根目录不可达时标记 `offline` 并以不可重试错误结束任务，文件记录不变。
- **入库**（`library/ingest.py`）按批（24 个文件）处理 `ingest_state = 'pending'` 的文件：
  1. 指纹：整文件 xxh3-128（`xxh128:<hex>`），只在内容变化后重算；
  2. 归组：同一目录、同名主干的照片合并为一个资产（RAW 为 `primary`，JPEG/HEIC 为 `companion`
     并作为封面），`.xmp` 为 `sidecar`；视频不与照片配对；
  3. 元数据：ExifTool 常驻进程（`-stay_open`，`-charset filename=utf8` 支持中文路径）一次读一批，
     视频再用 FFprobe 补充编码、帧率、旋转与时长；
  4. 缩略图（长边 400px）与预览图（长边 2048px），JPEG，原子写入。
- **拍摄时间**统一存为本地挂钟时间 `YYYY-MM-DDTHH:MM:SS`：优先 EXIF DateTimeOriginal，
  QuickTime 的 UTC 时间换算为本机时区，都没有时退回文件修改时间。
- **尺寸**存为显示方向（EXIF 方向 5–8、视频旋转 ±90° 时交换宽高）。

## 9. 任务引擎（ADR-007）

- 队列就是 `tasks` 表；`TaskRunner` 在后端进程内用一个线程依次执行任务，任务内部再并行。
- 同类型、同根目录的活动任务去重（重复点"重新扫描"不会排多个任务）。
- 失败按指数退避重试（10s、20s…，最多 `max_attempts` 次）；`PermanentTaskError` 不重试。
- 取消：排队中的任务直接取消；运行中的任务设置 `cancel_requested`，处理器在下一次进度上报时退出。
- 关闭应用：运行中的任务放回队列（不计入尝试次数），下次启动继续。
- **崩溃恢复**：启动时把残留的 `running` 任务放回队列。入库在处理文件**之前**先把该文件的
  `ingest_attempts` 加一，所以导致进程崩溃的坏文件最多重试 3 次就被标记为 `error`，不会卡住队列。

## 10. 移动、丢失与重复（ADR-008）

- **移动**：新文件的指纹与同一根目录下某个 `missing` 文件相同 → 视为移动，新文件继承原资产
  （评分、收藏、备注保留），旧记录删除。
- **丢失**：文件记录保留并标记 `missing`；资产不删除（硬盘可能重新接入）。
- **重复**：`GET /duplicates` 按指纹列出内容相同的文件，只报告，不自动合并或删除。

## 11. 缩略图缓存与访问（ADR-009）

- 位置：`cache/renditions/<指纹前两位>/<指纹>_t1.jpg|_p1.jpg`；按内容寻址，所以重复文件共用一份，
  文件移动后仍然有效；`_t1/_p1` 中的数字是渲染器版本，算法变化时递增即可整体失效。
- 同一指纹的渲染在进程内加锁，避免并发写同一文件（Windows 上会冲突）。
- 缓存被删除时，接口按需重新生成。
- `<img>` 无法携带请求头，因此**仅**缩略图接口额外接受 `?token=`；URL 带内容版本号 `v=`，
  响应可永久缓存（`Cache-Control: immutable`）。

## 12. 外部工具

- ExifTool、FFmpeg、FFprobe 通过 `PATH` 或 `LUMEN_*_PATH` 查找；缺失时降级运行（不提取照片元数据 /
  不生成视频封面），并在日志中警告。正式安装包将随附这些工具（打包阶段处理）。

## 13. 标签、星级与导入（ADR-010，Phase 3）

- `tags`（`name_key` 小写唯一，大小写不同视为同一标签）+ `media_tags(asset_id, tag_id, source)`，
  `source` 为 `user`（在 LUMEN 中添加）或 `import`（来自文件）。
- 入库时只读读取 `XMP:Rating`/`EXIF:Rating` 与 `XMP:Subject`/`IPTC:Keywords`，包括 RAW 旁边的
  `.xmp`（Lightroom 把 RAW 的星级和关键词写在这里）。一个资产取其所有文件中的最高星级。
- `media_assets.rating_source`：`NULL` 未评级，`import` 来自文件，`user` 在 LUMEN 中设置。
  `user` 星级永远不会被重新导入覆盖。
- 迁移 0003 会把已入库文件标记为重新读取元数据并排队入库任务；指纹和缩略图已缓存，所以很快。

## 14. 全文搜索（ADR-011）

- 视图 `asset_search_source` 是"哪些内容可被搜索"的唯一定义：文件相对路径、来源名称、相机、
  镜头、标签名、备注。`lumen.library.search.reindex_assets` 在资产变化时（入库、编辑标签/备注、
  标签改名/删除）从视图重建对应文档；删除资产由触发器同步删除。
- FTS5 使用 `trigram` 分词，查询用 `LIKE '%词%'`：既支持子串匹配，也支持没有空格分词的中文。
  不足 3 个字符的词（如"西湖"）无法使用三元组索引，退化为对索引表的扫描，仍足够快。
- 多个词之间是"且"的关系；`%` 和 `_` 会被转义。

## 15. 查询接口（ADR-012）

- 列表、全选 id、时间轴统计、地图坐标共用同一个筛选构造器（`services/assets._filters`），
  所以同一组筛选条件在各页面结果一致。
- 游标分页编码了排序方式和排序键；用错排序方式的游标会被拒绝。
- `facets` 统计的是整个图库（不随筛选变化），用于填充筛选下拉框。

## 16. 前端：照片墙、浏览器与地图（ADR-013）

- 照片墙用"等高行"（justified）布局：按宽高比把照片排进行，每行恰好填满宽度，最后一行不拉伸；
  宽高比限制在 0.4–3 之间，避免全景图独占一行。布局是纯函数（`library/layout.ts`），配合虚拟滚动，
  只渲染可见行。
- 筛选条件在图库、时间轴、地图之间共享（`library/state.tsx`）；顶部搜索栏实时更新筛选。
- 时间轴按天分组；跳转到某个月是把列表"锚定"在该月（`date_to` 为下个月），可一键回到最新。
- 全屏浏览显示 2048px 预览；浏览器可直接解码的格式（JPEG/PNG）可切换到原图 1:1。
  视频直接播放原文件（`/original` 支持 Range）。
- 地图使用 MapLibre；照片在前端用 Supercluster 聚合，气泡用 HTML 标记显示缩略图，因此离线
  底图不需要字体文件。离线底图来自 `world-atlas`（Natural Earth 1:50m 国界，按需加载）。
- MapLibre 的 Web Worker 以原始源码（`?raw`）通过 `blob:` URL 启动：MapLibre 默认按自身模块
  路径寻找 worker，打包后会失效；CSP 中对应放开 `worker-src blob:`。
- CSP 中新增 `media-src`（视频）和 `https://tiles.openfreemap.org`（仅在线地图使用）。
