# LUMEN Studio

本地优先的个人摄影与视频资产管理工作站（Windows 桌面应用）。

当前进度：**Phase 4 — AI 集成**（见 [docs/phases.md](docs/phases.md)）。

- Phase 1：桌面外壳、界面框架、本地后端、SQLite 数据库与迁移、照片文件夹登记。
- Phase 2：文件夹扫描、RAW/JPEG/HEIC/PNG/TIFF/视频识别、EXIF 与视频元数据、内容指纹、
  RAW+JPEG 配对、缩略图与预览图、文件移动与重复检测、可断点续跑的后台任务、缩略图网格。
- Phase 3：等高行照片墙与多选批量操作、全屏浏览与视频播放、时间轴、地图（离线底图，可选在线；深色/浅色等多种底图样式；离线地名）、
  星级/收藏/标签/备注、全文搜索（支持中文）与元数据筛选、只读导入 XMP/EXIF 关键词与星级。
- Phase 4：本机 GPU 上的 SigLIP2 语义搜索（中文可直接搜索）、相似照片、自动场景标签；
  OpenCLIP 模型对照实验工具；DeepSeek 云端分析（描述、点评、选片、旅行故事，逐次确认后才上传）。

- 产品需求：[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)
- 架构决策：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 技术栈

| 层 | 技术 |
|---|---|
| 界面 | React 19 · TypeScript 5.9（strict）· Vite · Tailwind CSS 4 · shadcn/ui · i18next |
| 地图 | MapLibre GL · Supercluster · Natural Earth（离线底图）· OpenFreeMap（可选在线）· GeoNames（离线地名） |
| AI | PyTorch（CUDA）· transformers · SigLIP2 · OpenCLIP（对照）· DeepSeek API（可选） |
| 桌面运行时 | Tauri 2（Rust）· tauri-plugin-dialog |
| 本地服务 | Python 3.12+ · FastAPI · Pydantic 2 · uvicorn |
| 媒体处理 | ExifTool · FFmpeg/FFprobe · Pillow · pillow-heif · rawpy（LibRaw）· xxHash |
| 数据库 | SQLite（WAL）+ 自研 SQL 迁移器 |

## 目录结构

```
Photo-lab/
├─ docs/                    需求、阶段规划、架构决策
├─ scripts/                 setup.ps1 / dev.ps1 / test.ps1 / launch.ps1（启动程序）
├─ backend/                 Python 本地服务
│  ├─ lumen/
│  │  ├─ __main__.py        进程入口与启动握手
│  │  ├─ app.py             FastAPI 应用工厂、中间件、错误处理
│  │  ├─ api/v1/            路由（只做输入输出转换）
│  │  ├─ services/          业务逻辑（供 API 调用）
│  │  ├─ media/             媒体引擎：格式、目录遍历、指纹、元数据、缩略图（不访问数据库）
│  │  ├─ library/           扫描与入库流水线、全文索引、标签（文件系统 ⇄ 数据库）
│  │  ├─ tasks/             持久化任务队列与后台执行器
│  │  ├─ ai/                AI 引擎：模型注册、编码器、向量索引、标签、云端分析、对照工具
│  │  ├─ develop/           显影：编辑配方、渲染器（numpy + OpenCV）、编辑后的缩略图（不访问数据库）
│  │  ├─ schemas/           Pydantic 请求/响应模型
│  │  ├─ db/                连接、事务、迁移器、migrations/*.sql
│  │  ├─ core/              配置、结构化日志、令牌鉴权、卷信息
│  │  └─ openapi.py         导出 OpenAPI（供前端生成类型）
│  └─ tests/                pytest；media_factory.py 生成测试用照片和视频
└─ desktop/                 桌面应用
   ├─ src/
   │  ├─ api/               API 客户端、React Query hooks、生成的 schema.d.ts
   │  ├─ components/        layout/（顶栏、侧栏、检查器、状态栏）、library/（照片墙、筛选栏、
   │  │                     批量操作条、星级、标签输入）、viewer/（全屏浏览）、develop/（显影）、
   │  │                     ai/（云端分析确认框）、settings/（AI 设置）、ui/
   │  ├─ library/           布局算法、多选、共享筛选状态、照片墙逻辑
   │  ├─ pages/             图库、时间轴、地图、AI 搜索、作品集、设置
   │  ├─ i18n/              zh-CN / en / fr
   │  └─ lib/               后端连接、原生对话框、工具函数
   └─ src-tauri/
      └─ src/               lib.rs、backend.rs（后端进程管理）、job.rs（Windows Job Object）
```

## Windows 环境准备

需要预先安装：

1. **Node.js** 20+（含 npm）
2. **Rust**（stable，`x86_64-pc-windows-msvc` 工具链）：<https://rustup.rs>
3. **Microsoft C++ 生成工具**（Visual Studio Build Tools，勾选"使用 C++ 的桌面开发"）
4. **WebView2 运行时**（Windows 11 已自带）
5. **Python** 3.12+（建议从 python.org 安装，并安装 `py` 启动器）
6. **ExifTool**：读取照片元数据。推荐 `scoop install exiftool`，或从 <https://exiftool.org> 下载
7. **FFmpeg**（含 ffprobe）：读取视频信息、截取视频封面。推荐 `scoop install ffmpeg`

ExifTool 和 FFmpeg 需要在 `PATH` 中，或用下文的环境变量指定路径。缺少时应用仍可运行，
但照片不会提取元数据、视频不会生成封面。

然后在仓库根目录执行一次：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

如需本地 AI（AI 搜索、相似照片、自动标签），加上 `-WithAI`：会安装 CUDA 版 PyTorch 等（约 3 GB）。
模型（SigLIP2 so400m，约 4.5 GB）在应用里启用 AI 时自动下载到 HuggingFace 缓存
（`%USERPROFILE%\.cache\huggingface`）。需要 NVIDIA 显卡和较新的驱动；没有 GPU 时会用 CPU，但很慢。

它会创建 `backend\.venv` 并安装后端依赖，再安装前端 npm 依赖。

## 试用（启动程序）

在项目文件夹中双击 **`启动 LUMEN Studio.cmd`**：

- 首次运行会自动准备环境（等同 `scripts\setup.ps1`），并构建优化后的发布版（需几分钟）；
- 之后只有前端或桌面端源码有改动时才会重新构建，否则几秒内启动；
- 发布版没有控制台窗口；后端使用 `backend\.venv` 中的 Python（正式安装包会内置后端，属于后续打包工作）。

强制重新构建：`powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 -Rebuild`

照片库数据位于 `%LOCALAPPDATA%\LUMEN Studio`，与开发模式共用。

## 开发

启动桌面应用（Vite 开发服务器 + Tauri 窗口，Tauri 会自动启动 Python 后端）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

首次启动需要编译 Rust 依赖，约 1–3 分钟。

### 单独运行后端

```powershell
cd backend
.\.venv\Scripts\python.exe -m lumen
```

未提供 `LUMEN_TOKEN` 时，后端会生成一个令牌，并在 stdout 的就绪消息中打印出来：
`{"event": "ready", "port": 52341, "pid": 1234, "token": "..."}`。之后所有请求都需要带上
`Authorization: Bearer <token>`。

### 在浏览器中开发界面（不启动 Tauri）

先单独运行后端，记下端口和令牌，然后创建 `desktop\.env.development.local`：

```
VITE_LUMEN_API_URL=http://127.0.0.1:<端口>
VITE_LUMEN_API_TOKEN=<令牌>
```

执行 `cd desktop; npm run dev`，然后打开 <http://localhost:1420>。这种模式下没有原生对话框，
选择文件夹会改为手动输入路径。

### 后端配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LUMEN_DATA_DIR` | `%LOCALAPPDATA%\LUMEN Studio` | 数据库、日志、备份所在目录 |
| `LUMEN_HOST` | `127.0.0.1` | 只允许回环地址 |
| `LUMEN_PORT` | `0` | 0 表示由系统随机分配 |
| `LUMEN_TOKEN` | 随机生成 | API 令牌（由 Tauri 每次启动时生成） |
| `LUMEN_ALLOWED_ORIGINS` | Tauri 与 `localhost:1420` | 逗号分隔的 CORS 来源 |
| `LUMEN_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LUMEN_LOG_TO_FILE` | `true` | 是否写入 `logs\backend.log` |
| `LUMEN_EXIFTOOL_PATH` | 在 `PATH` 中查找 | ExifTool 可执行文件 |
| `LUMEN_FFMPEG_PATH` / `LUMEN_FFPROBE_PATH` | 在 `PATH` 中查找 | FFmpeg / FFprobe 可执行文件 |
| `LUMEN_INGEST_WORKERS` | CPU 核数，最多 4 | 并行处理文件的线程数 |
| `LUMEN_AI_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `LUMEN_AI_IDLE_UNLOAD_S` | `600` | AI 模型空闲多少秒后从显存卸载 |
| `HF_HOME` | HuggingFace 默认 | 模型缓存位置 |
| `LUMEN_BACKEND_PYTHON` | — | （Tauri 侧）用指定的 Python 启动后端 |

### 更新前端 API 类型

修改后端的 Pydantic 模型或路由后，执行：

```powershell
cd desktop
npm run gen:api
```

## 测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

包含：后端 ruff、mypy（strict）、pytest；前端 TypeScript 类型检查、vitest；Rust clippy。
端到端测试（`tests/test_pipeline.py`）会用真实的 ExifTool 和 FFmpeg 处理生成的样本文件；
两者缺一时这些测试会自动跳过。

生成一个样本照片库用于手动试用：

```powershell
cd backend
.\.venv\Scripts\python.exe -m tests.media_factory D:\LumenSample
```

## API（v1）

所有请求都需要 `Authorization: Bearer <token>`（缩略图和原文件接口也接受 `?token=`，供 `<img>`/`<video>` 使用）。错误统一返回
`{"error": {"code": "...", "message": "...", "details": {}}}`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 服务状态、版本、数据库结构版本 |
| GET | `/api/v1/storage-roots` | 列出已登记的照片文件夹 |
| POST | `/api/v1/storage-roots` | 登记文件夹：`{"path": "D:\\Photos", "display_name": "可选"}` |
| DELETE | `/api/v1/storage-roots/{id}` | 取消登记（只删除索引记录，不碰磁盘文件） |
| POST | `/api/v1/storage-roots/{id}/scan` | 重新扫描（已有排队或进行中的扫描时直接复用） |
| GET | `/api/v1/tasks?active=true` | 后台任务及进度 |
| POST | `/api/v1/tasks/{id}/cancel` · `/retry` | 取消 / 重试任务 |
| GET | `/api/v1/assets?q=&media_type=&min_rating=&favorite=&camera=&lens=&format=&tag_id=&storage_root_id=&date_from=&date_to=&has_location=&country=&place_id=&rejected=&sort=&cursor=&limit=` | 资产列表：筛选、排序（`capture_desc`/`capture_asc`/`added_desc`）、游标分页 |
| GET | `/api/v1/assets/ids?…` | 符合筛选条件的全部资产 id（全选用） |
| GET | `/api/v1/assets/facets` | 可选的相机、镜头、格式、年份、标签、地点及数量 |
| PATCH | `/api/v1/assets/{id}` | 修改星级、收藏、备注 |
| POST | `/api/v1/assets/batch` | 批量修改星级、收藏，批量添加/移除标签 |
| GET | `/api/v1/assets/{id}` | 资产详情：元数据、位置、全部文件 |
| GET | `/api/v1/assets/{id}/thumbnail?variant=thumb\|preview\|full` | 缩略图（400px）、预览图（2048px）或全尺寸图（按需生成并缓存，含编辑效果） |
| GET | `/api/v1/assets/{id}/original` | 原文件（只读，支持 Range，用于视频播放和原图查看） |
| GET | `/api/v1/assets/{id}/motion` | 实况照片的视频片段（只读，支持 Range） |
| GET/PUT | `/api/v1/assets/{id}/edit` | 当前编辑配方与历史 / 保存新的一步（非破坏性，不写原文件） |
| POST | `/api/v1/assets/{id}/edit/undo` · `/redo` · `/select` | 撤销、重做、回到历史中的某一步（`null` 为原图） |
| POST | `/api/v1/assets/{id}/develop/preview` | 按未保存的配方渲染 JPEG（`X-Histogram` 头为 RGB 直方图） |
| POST | `/api/v1/edits/batch` | 把配方中的指定字段应用到多张照片（粘贴设置、预设） |
| POST | `/api/v1/exports` | 导出照片为新的 JPEG（后台任务；长边、质量、是否保留 EXIF / GPS） |
| GET | `/api/v1/exports/{task_id}` | 导出进度与结果（导出、跳过、失败） |
| GET/PUT | `/api/v1/assets/{id}/video-edit` | 视频剪辑：起止时间、旋转、静音（非破坏性） |
| POST | `/api/v1/assets/{id}/frame-export` | 把视频某一帧存成新的 JPEG |
| GET/POST | `/api/v1/collections` | 作品集列表 / 新建（可同时带入资产） |
| GET | `/api/v1/collections/suggestions` | 按拍摄时间与地点找出的旅行建议 |
| GET/PATCH/DELETE | `/api/v1/collections/{id}` | 作品集详情（按顺序的条目与说明）/ 修改 / 删除（不删照片） |
| POST | `/api/v1/collections/{id}/items` · `/items/remove` | 加入 / 移出资产 |
| PUT | `/api/v1/collections/{id}/order` | 整体重排 |
| PATCH | `/api/v1/collections/{id}/items/{asset_id}` | 修改说明 |
| GET | `/api/v1/timeline?granularity=year\|month\|day&…` | 按时间段统计数量 |
| GET | `/api/v1/map/points?…` | 带位置的资产坐标 |
| GET/POST | `/api/v1/tags` · PATCH/DELETE `/api/v1/tags/{id}` | 标签列表、新建、重命名、删除 |
| GET/PATCH | `/api/v1/settings` | 应用设置（在线地图、底图样式、AI、云端） |
| GET | `/api/v1/ai/status` | 本地 AI（GPU、模型、已分析数量）与云端配置状态 |
| POST | `/api/v1/ai/model/download` · `/api/v1/ai/index` | 下载模型 / 分析照片（后台任务） |
| GET | `/api/v1/ai/search?text=&…` | 语义搜索（可叠加筛选条件），返回相似度和明显相关的数量 |
| GET | `/api/v1/assets/{id}/similar` | 相似照片 |
| PUT/DELETE | `/api/v1/ai/cloud/key` | 保存 / 删除 DeepSeek API 密钥（Windows 凭据管理器） |
| POST | `/api/v1/ai/cloud/test` | 测试密钥并检查模型能否识别图片 |
| POST | `/api/v1/ai/cloud/preview` | 列出将要发送的内容（图片、字段、目标），不联网 |
| POST | `/api/v1/ai/cloud/analyze` | 云端分析，必须带 `confirmed: true`；结果按内容缓存 |
| GET | `/api/v1/assets/{id}/analyses` | 该照片以往的云端分析 |
| GET | `/api/v1/cull/similar?window_minutes=&similarity=&pending_only=` | 相似照片分组与推荐保留的照片（需本地 AI 向量） |
| GET | `/api/v1/cull/suspects?pending_only=` | 可能模糊或曝光不当的照片（最差的在前） |
| GET | `/api/v1/cull/rejected-files` | 淘汰照片在磁盘上的全部文件路径（只列出，不删除） |
| POST | `/api/v1/files/{id}/reveal` | 在资源管理器中显示某个文件 |
| POST | `/api/v1/assets/{id}/open-map` | 在默认浏览器中打开谷歌地图，定位到照片的拍摄地点（点击时才会把坐标发给谷歌） |
| GET/POST | `/api/v1/backups` | 备份列表（含文件夹是否可用）· 立即备份 |
| POST | `/api/v1/backups/restore` | 从列表中的备份（`name`）或任意文件（`path`）恢复，先另存“恢复前”备份 |
| POST | `/api/v1/backups/reveal` | 在资源管理器中显示备份文件 |
| GET | `/api/v1/duplicates` | 因文件内容完全相同而重复出现的照片分组，以及建议保留的一份 |
| POST | `/api/v1/duplicates/merge` | 把重复的副本合并为一张照片（只改数据库，文件都留在原处） |
| GET | `/api/v1/openapi.json` | OpenAPI 文档 |

## 快捷键

| 按键 | 功能 |
|---|---|
| Ctrl 1–6 | 图库 / 时间轴 / 地图 / AI 搜索 / 作品集 / 整理 |
| Ctrl , | 设置 |
| Ctrl K 或 Ctrl F | 聚焦搜索栏 |
| Ctrl I | 显示或隐藏检查器 |
| 方向键 · Home/End | 在照片墙中移动（加 Shift 扩展选择） |
| 单击 · Ctrl+单击 · Shift+单击 | 选择 · 加选/取消 · 连续选择 |
| Ctrl A · Esc | 全选当前筛选结果 · 取消选择 |
| Enter / 空格 / 双击 | 全屏浏览 |
| 0–5 · F · X · P | 打星（0 为清除）· 收藏/取消收藏 · 淘汰 · 保留（再按一次取消；作用于所有选中项，全屏中也可用） |
| 全屏中：← → · I · Esc | 上一张/下一张 · 信息面板 · 关闭（放大时先回到适合窗口） |
| 全屏中：滚轮 · 拖动 · 双击或 Z | 以鼠标为中心缩放（最大为原始像素的 400%）· 放大后平移 · 在适合窗口与 100% 之间切换 |
| 全屏中：D | 进入 / 退出显影（照片）或剪辑（视频） |
| 剪辑视频中：I · O | 把当前位置设为起点 · 终点 |
| 显影中：Ctrl Z · Ctrl Shift Z（Ctrl Y） · \ · C · Enter · Esc | 撤销 · 重做 · 对比原图 · 裁剪 · 完成裁剪 · 取消裁剪 / 退出显影 |
| 显影中：双击滑块或其名称 | 恢复该项默认值 |
| 显影中：Ctrl Shift C · Ctrl Shift V | 拷贝设置 · 粘贴设置（不含旋转和裁剪） |

## 数据安全原则

- 原始照片和视频文件永远不会被移动、重命名、修改或删除。
- 取消登记文件夹只删除 LUMEN Studio 数据库中的记录。
- “淘汰”只是标记（默认隐藏），不会删除文件；整理页可以复制淘汰文件的路径，由你自己决定是否删除。
- 合并重复文件只把副本记为同一张照片的多个位置；之后在资源管理器中删除多余副本，只要还剩一份，照片和它的评分、编辑都不会丢失。
- 磁盘上找不到的文件只标记为"丢失"，不会删除其记录、评分和备注；硬盘未连接时来源标记为"离线"（导入或扫描中途拔盘也不会误标），
  插回后自动恢复并继续没导完的导入；盘符变了也会按卷序列号认回原来的来源。
- 缩略图和预览图只写入 `cache\`，删除后会按需重新生成。
- 星级、收藏、标签、备注只存在数据库中；XMP/EXIF 中的关键词和星级只读导入，从不写回文件。
- 地图默认完全离线；只有在设置中开启在线地图后，才会向 OpenFreeMap 请求地图图块（不上传照片）。
- 本地 AI 完全在本机运行；云端分析默认关闭，每次都先显示将上传的内容（缩小后的图片和字段），
  确认后才发送；GPS 默认不发送；API 密钥只保存在 Windows 凭据管理器中。
- 后端只监听 `127.0.0.1`，每次启动使用随机端口和随机令牌。
- 升级数据库结构前，自动将旧数据库备份到 `backups\`；另有自动备份（默认每周、保留 10 份）、手动备份和恢复
  （设置 → 备份与恢复；恢复前会先另存当前数据）。

## AI 模型对照实验

`python -m lumen.ai.bench` 比较不同模型的文字搜图效果（Recall@1/5/10、mAP、速度）。
OpenCLIP 模型需要先安装：`pip install -e .[bench]`。

```powershell
cd backend
# 用你自己的照片库：手动或导入的标签作为查询，带该标签的照片作为正确答案
.\.venv\Scripts\python.exe -m lumen.ai.bench --library --models siglip2-so400m-patch14-384 openclip-xlm-roberta-large-vit-h-14
# 或：一个图片文件夹 + {"查询": ["文件名", ...]} 的 JSON
.\.venv\Scripts\python.exe -m lumen.ai.bench --folder D:\eval --queries D:\eval\queries.json --output result.json
```
