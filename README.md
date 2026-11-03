# LUMEN Studio

本地优先的个人摄影与视频资产管理工作站（Windows 桌面应用）。

当前进度：**Phase 2 — 媒体管理引擎**（见 [docs/phases.md](docs/phases.md)）。

- Phase 1：桌面外壳、界面框架、本地后端、SQLite 数据库与迁移、照片文件夹登记。
- Phase 2：文件夹扫描、RAW/JPEG/HEIC/PNG/TIFF/视频识别、EXIF 与视频元数据、内容指纹、
  RAW+JPEG 配对、缩略图与预览图、文件移动与重复检测、可断点续跑的后台任务、缩略图网格。

- 产品需求：[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)
- 架构决策：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 技术栈

| 层 | 技术 |
|---|---|
| 界面 | React 19 · TypeScript 5.9（strict）· Vite · Tailwind CSS 4 · shadcn/ui · i18next |
| 桌面运行时 | Tauri 2（Rust）· tauri-plugin-dialog |
| 本地服务 | Python 3.12+ · FastAPI · Pydantic 2 · uvicorn |
| 媒体处理 | ExifTool · FFmpeg/FFprobe · Pillow · pillow-heif · rawpy（LibRaw）· xxHash |
| 数据库 | SQLite（WAL）+ 自研 SQL 迁移器 |

## 目录结构

```
Photo-lab/
├─ docs/                    需求、阶段规划、架构决策
├─ scripts/                 setup.ps1 / dev.ps1 / test.ps1
├─ backend/                 Python 本地服务
│  ├─ lumen/
│  │  ├─ __main__.py        进程入口与启动握手
│  │  ├─ app.py             FastAPI 应用工厂、中间件、错误处理
│  │  ├─ api/v1/            路由（只做输入输出转换）
│  │  ├─ services/          业务逻辑（供 API 调用）
│  │  ├─ media/             媒体引擎：格式、目录遍历、指纹、元数据、缩略图（不访问数据库）
│  │  ├─ library/           扫描与入库流水线（文件系统 ⇄ 数据库）
│  │  ├─ tasks/             持久化任务队列与后台执行器
│  │  ├─ schemas/           Pydantic 请求/响应模型
│  │  ├─ db/                连接、事务、迁移器、migrations/*.sql
│  │  ├─ core/              配置、结构化日志、令牌鉴权、卷信息
│  │  └─ openapi.py         导出 OpenAPI（供前端生成类型）
│  └─ tests/                pytest；media_factory.py 生成测试用照片和视频
└─ desktop/                 桌面应用
   ├─ src/
   │  ├─ api/               API 客户端、React Query hooks、生成的 schema.d.ts
   │  ├─ components/        layout/（顶栏、侧栏、检查器、状态栏）、library/（缩略图网格）、ui/
   │  ├─ pages/             图库、设置、占位页
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

它会创建 `backend\.venv` 并安装后端依赖，再安装前端 npm 依赖。

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

所有请求都需要 `Authorization: Bearer <token>`（缩略图接口也接受 `?token=`，供 `<img>` 使用）。错误统一返回
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
| GET | `/api/v1/assets?cursor=&limit=` | 资产列表，按拍摄时间倒序，游标分页 |
| GET | `/api/v1/assets/{id}` | 资产详情：元数据、位置、全部文件 |
| GET | `/api/v1/assets/{id}/thumbnail?variant=thumb\|preview` | 缩略图（400px）或预览图（2048px） |
| GET | `/api/v1/duplicates` | 内容完全相同的文件分组（只报告，不合并、不删除） |
| GET | `/api/v1/openapi.json` | OpenAPI 文档 |

## 快捷键

| 按键 | 功能 |
|---|---|
| Ctrl 1–5 | 图库 / 时间轴 / 地图 / AI 搜索 / 作品集 |
| Ctrl , | 设置 |
| Ctrl K 或 Ctrl F | 聚焦搜索栏 |
| Ctrl I | 显示或隐藏检查器 |

## 数据安全原则

- 原始照片和视频文件永远不会被移动、重命名、修改或删除。
- 取消登记文件夹只删除 LUMEN Studio 数据库中的记录。
- 磁盘上找不到的文件只标记为"丢失"，不会删除其记录、评分和备注；硬盘未连接时来源标记为"离线"。
- 缩略图和预览图只写入 `cache\`，删除后会按需重新生成。
- 后端只监听 `127.0.0.1`，每次启动使用随机端口和随机令牌。
- 升级数据库结构前，自动将旧数据库备份到 `backups\`。
