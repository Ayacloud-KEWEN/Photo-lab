# LUMEN Studio — 交接文档（HANDOFF）

> 给接手的开发者或新的 Claude 会话：先读本文，再按需读 `docs/`。最后更新：2026-11-03（Phase 5.3 视频基础处理完成，分支 `phase-5-studio`）。

## 1. 一句话现状

Windows 桌面照片/视频管理工作站，**Phase 1–4 已完成并合并进 `main`**。**Phase 5（摄影工作室）进行中**，
在分支 `phase-5-studio` 上分 4 步交付，每步由用户试用确认：
5.1 显影（非破坏性照片编辑）✅ → 5.2 导出与批量（导出 JPEG 任务、拷贝/粘贴调整、预设）✅ →
5.3 视频基础处理（首尾剪辑、旋转、静音、导出、抽帧）✅ → 5.4 旅行作品集（collections 表、排序、说明、旅行建议、批量导出）。
用户（中文沟通）会先试用当前版本，可能带着问题反馈回来。

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | Tauri + React + Python 后端骨架、SQLite 迁移、文件夹登记 | ✅ |
| Phase 2 | 扫描、元数据、指纹、缩略图、RAW+JPEG 配对、移动/丢失/重复、后台任务 | ✅ |
| Phase 3 | 照片墙、全屏浏览、时间轴、地图、星级/收藏/标签/备注、搜索筛选 | ✅ |
| Phase 4 | SigLIP2 语义搜索/相似照片/自动标签、OpenCLIP 对照工具、DeepSeek 云端分析 | ✅ |
| Phase 5 | RAW 后期、色彩调整、非破坏性编辑、视频基础处理、旅行摄影作品集 | 🚧 5.1–5.3 已完成 |

## 2. 必读文档

| 文件 | 用途 |
|---|---|
| `docs/PROJECT_SPEC.md` | 产品需求（原始需求，勿随意改动） |
| `docs/phases.md` | 阶段划分 |
| `docs/Project_Initialization.md` | Phase 1 任务书（工作方式：先查环境、提方案、经确认再实施） |
| `docs/ARCHITECTURE.md` | **所有架构决策（ADR-001 ~ ADR-021）**，改动架构前先读 |
| `README.md` | 安装、开发、测试、API 列表、快捷键 |

## 3. 环境（用户的开发机）

- Windows 11 Pro，**RTX 4070 SUPER 12 GB**（驱动 610，支持 CUDA 13）
- Python 3.13（`backend\.venv`，已装 `.[dev]`、AI 栈 torch 2.14.1+cu130 / transformers 5.22、open_clip_torch）
- Node 22.19 / npm、Rust 1.96（MSVC）、VS Build Tools 2019、WebView2
- ExifTool 13.60（scoop：`~\scoop\shims\exiftool`），FFmpeg/FFprobe（`D:\Software\ffmpeg-master-latest-win64-gpl\bin`）
- 已下载模型（HuggingFace 缓存 `%USERPROFILE%\.cache\huggingface\hub`）：
  `google/siglip2-so400m-patch14-384`（4.3 GB）、`laion/CLIP-ViT-B-32-laion2B-s34B-b79K`（OpenCLIP 对照用）
- Git 远程：`https://github.com/Ayacloud-KEWEN/Photo-lab.git`（本机没有 `gh` CLI）

## 4. 常用命令

```powershell
# 试用（发布版，源码有改动会自动重建）：双击仓库根目录的 "启动 LUMEN Studio.cmd"
powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 [-Rebuild]

powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-WithAI]   # 新机器准备环境
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1               # 开发模式（Vite + Tauri）
powershell -ExecutionPolicy Bypass -File scripts\test.ps1              # 全部检查：ruff/mypy/pytest + tsc/vitest + clippy

cd desktop; npm run gen:api        # 后端模型/路由改动后，重新生成前端 API 类型（src/api/schema.d.ts）
cd backend; .\.venv\Scripts\python.exe -m tests.media_factory D:\LumenSample   # 生成样本库
cd backend; .\.venv\Scripts\python.exe -m lumen.ai.bench --library --models ...  # 模型对照
```

当前检查结果：后端 **133** 个测试、前端 **60** 个测试全部通过；ruff、mypy（strict）、tsc（strict）、clippy 零问题。

## 5. 代码地图

```
backend/lumen/
  __main__.py      进程入口：stdout 握手 {"event":"ready","port":N}，--watch-stdin 退出
  app.py           FastAPI 工厂、中间件（令牌、CORS、请求日志）、生命周期（迁移、TaskRunner）
  core/            config（LUMEN_* 环境变量）、logging（JSON）、security（Bearer 令牌）、volumes
  db/              connection、migrator（前向迁移+校验和+迁移前备份）、migrations/000N_*.sql
  media/           纯媒体引擎（不碰数据库）：formats、walker、fingerprint、metadata、thumbnails
  library/         scan / ingest 流水线、search（FTS 重建）、tags、handlers（任务注册表）
  tasks/           queue（SQLite 任务表）、runner（后台线程、重试、取消、恢复）
  ai/              models（注册表）、encoders（SigLIP2/OpenCLIP）、engine（加载/卸载）、
                   index（内存向量检索）、labels（标签词表）、pipeline（下载/索引任务）、
                   cloud（DeepSeek）、bench（对照工具）
  develop/         显影（Phase 5）：recipe（编辑配方）、engine（numpy+OpenCV 渲染、底图缓存）、renditions（编辑后的缩略图）、
                   exporter（导出 JPEG：ICC、元数据、不覆盖）；导出任务在 library/exports.py
  services/        供 API 调用的业务逻辑；api/v1/ 路由只做输入输出
desktop/src/
  api/             client.ts、hooks.ts（React Query）、query.ts、schema.d.ts（生成，勿手改）
  library/         layout（等高行布局，纯函数）、selection（多选）、state（共享筛选/浏览器/云端对话框）、useWall
  components/      layout/、library/（PhotoWall 等）、viewer/、develop/（显影工作区、裁剪框、滑块、直方图）、
                   ai/CloudDialog、settings/AiSettings、ui/
  pages/           Library / Timeline / Map（懒加载）/ AISearch / Settings / Placeholder
  i18n/locales/    zh-CN（源）、en、fr —— 有测试保证三种语言的键完全一致
desktop/src-tauri/src/  lib.rs、backend.rs（启动/监控/关闭 Python 后端）、job.rs（Windows Job Object）
```

## 6. 必须遵守的约定

1. **原始文件只读**：任何代码都不能写、移动、重命名、删除用户的照片/视频/XMP。编辑结果只存数据库。
2. **数据库迁移只增不改**：已发布的 `000N_*.sql` 不能再修改（迁移器校验 SHA-256，改了会拒绝启动）。新改动写新迁移文件。
   SQLite 改 CHECK 约束需重建表；被视图引用的表重建时先 `DROP VIEW` 再重建（见 0004）。
3. **界面中文优先**，新增文案必须同时加 zh-CN / en / fr 三份（`locales.test.ts` 会检查）。
4. **API 类型由后端生成**：改了 Pydantic 模型或路由就 `npm run gen:api`。
5. **隐私**：后端只听 127.0.0.1 + 每次启动的随机令牌；云端 AI 必须经用户逐次确认（后端要求 `confirmed: true`）；
   GPS 默认不上传；API 密钥只存 Windows 凭据管理器；在线地图默认关闭。
6. **工作流**：每个阶段先给方案、经用户确认再做；每个阶段一个分支（`phase-N-…`），完成后由用户决定提交，
   然后**快进合并进 `main` 并推送**。提交信息结尾附 `Co-Authored-By` 行。
7. 改动架构（ADR 中记录的内容）前先征得用户同意，并在 `docs/ARCHITECTURE.md` 追加 ADR。

## 7. 踩过的坑（新会话很容易再踩）

- **PowerShell 5.1 按 GBK 读取无 BOM 的 .ps1**：`scripts/*.ps1` 必须保持纯 ASCII（中文写在 README 里）。
- **用 Python 脚本改文件时务必 `encoding="utf-8"`**（系统默认 GBK）。Git Bash 里的 heredoc 遇到复杂引号/`\n` 容易出错，
  复杂编辑写成 scratch 目录下的 .py 文件再执行更稳。
- **从 Claude 桌面版里启动应用时**，Windows（MSIX 虚拟化）会把 `%LOCALAPPDATA%` 的写入重定向到
  `…\Packages\Claude_…\LocalCache\Local\`，所以那里的数据库和用户双击启动时看到的不是同一个。
  测试用临时数据目录（`LUMEN_DATA_DIR`），给用户用的数据让用户自己启动。
  需要**只读**查看用户真实的日志/数据库时，可以走 UNC 路径绕过重定向：
  `\\localhost\C$\Users\pc\AppData\Local\LUMEN Studio\logs\backend.log`。
- **子进程绝不能继承后端的 stdin**：桌面版里后端的 stdin 是 Tauri 的管道，`--watch-stdin` 线程一直挂着一个读操作。
  在 Windows 上 ffmpeg 处理超过约 0.5 秒（第一个 stats 周期）后会去轮询 stdin，然后一直卡到超时
  （之前 iPhone 4K MOV 每个卡 120 秒 × 重试 3 次，1000 多个文件的导入要几十分钟甚至几小时）。
  所有 `subprocess` 调用都要 `stdin=subprocess.DEVNULL`，ffmpeg 还要加 `-nostdin`。
  pytest 下复现不了（小视频处理不到 0.5 秒），所以由 `test_video_tools_never_inherit_stdin` 检查调用参数。
- **部分导出视频的色彩标记是保留值**（社交软件下载的 MP4 常见）：ffmpeg 报 `Invalid color space` 拒绝建滤镜图。
  `thumbnails._video_frame` 会在这种情况下用输入端比特流过滤器（`h264_metadata` / `hevc_metadata`）
  把标记改成“未指定”后重试。迁移 0005 会重试此前因超时或抽帧失败的文件。
- **浏览器预览面板被遮挡时 requestAnimationFrame 会暂停**：MapLibre 不触发 `load`、截图超时。截一张图会唤醒渲染。
- **MapLibre 的 Web Worker** 用 `?raw` 源码 + `blob:` URL 启动（`MapPage.tsx`），不要改回默认路径或 `?url`（Vite 开发模式会改写 worker）。
- **Tauri CSP**（`tauri.conf.json`）：视频需要 `media-src`，地图需要 `worker-src blob:`，在线地图需要 `https://tiles.openfreemap.org`。
  用浏览器验证 CSP 时，需要给脚本加 `'unsafe-inline'`（Tauri 自己会给内联脚本加哈希）。
- **SigLIP 的 sigmoid 概率对中文查询几乎全为 0**：不能当阈值。搜索用余弦（0.075），自动标签用标签间 softmax 占比（0.25）。
- **jsdom 没有布局**：虚拟列表测试要 mock `clientWidth/clientHeight`（`src/test/backend.tsx` 的 `fakeViewport`）。
- **应用运行在 React StrictMode 下**：开发模式会把副作用“卸载再挂载”一次。带请求/中止的 hook（如 `useDevelopPreview`）
  的清理函数必须把状态复位，否则开发版里请求被中止后不再重发；显影测试因此包在 `<StrictMode>` 里。
- **全屏浏览器的快捷键挂在对话框根元素上**：焦点所在元素被移除（如退出显影时的滑块）后要把焦点还给根元素；
  焦点在滑块上时只让出方向键/Home/End，其余快捷键照常生效。
- **在浏览器面板里试界面**：Vite 开发服务器的内联脚本会被面板的 CSP 拦截。改用
  `NODE_ENV=development vite build --mode development` 再 `vite preview --port 1420`
  （`VITE_LUMEN_API_URL/TOKEN` 只在开发构建中生效）；后端用 `LUMEN_DATA_DIR/LUMEN_PORT/LUMEN_TOKEN` 单独启动。
- **HuggingFace 在 Windows 无法建符号链接**（未开开发者模式），会有警告且占用更多空间，无害；启动脚本已屏蔽该警告。

## 8. 已知未完成 / 待验证（按优先级）

1. **DeepSeek 未用真实 API 密钥测试过**；`deepseek-flash` 支持图片只有第三方资料佐证。用户填入密钥后用“测试连接”确认。
2. **RAW 解码未用真实 RAW 文件验证**（只用伪造 RAW 测了配对逻辑）。请用户提供 CR3/NEF/ARW/DNG 样本。
3. **阈值只在小样本上校准**：语义搜索 0.075、自动标签 0.25、相似照片 0.6。等用户真实照片库反馈后调整（`services/ai.py`、`ai/labels.py`）。
4. **SPEC 中 MVP 的“数据库备份与恢复”尚未实现**（目前只有迁移前自动备份）。
5. **正式打包**：后端用 PyInstaller 打成 `lumen-backend.exe`（Tauri externalBin，`backend.rs` 已预留查找逻辑），
   随附 ExifTool/FFmpeg，NSIS 安装包；AI 栈体积大（torch ~3 GB），需决定是否作为可选组件。
   当前启动程序依赖项目里的 `backend\.venv`。
6. 重复文件只有 API（`GET /duplicates`），还没有界面；失败任务没有专门的查看/重试界面。
7. AI 标签名固定为中文（不随界面语言变化）。
8. 外接硬盘换盘符后，需要手动处理（已记录卷序列号，未自动重定位）；删除来源后缩略图缓存不会自动清理。
9. **iPhone 实况照片**已配对（ADR-017，`library/live.py`）。查看器和图库瓦片悬停 LIVE 标记都会播放片段
   （瓦片悬停 250ms 后才挂载 `<video>`，不预加载）；用户已确认 WebView2 能播 HEVC（依赖系统 HEVC 扩展），
   没有做转码兜底，解码失败时只显示静态图。用户库里 547 个 MOV 中 388 个是实况片段。
10. 性能：导入并行线程数上限是 4（`ingest_workers`，用户机器有 20 线程）；HEIC 没有降采样解码（12MP 约 1 秒/张）；
   缩略图用 LANCZOS 缩放，是 JPEG 处理中最耗时的一步。AI 索引约 44 张/秒（瓶颈是 CPU 端预处理，可换 torchvision 快速处理器）；前端主包 675 KB（可懒加载 AI 页面）。

## 9. Phase 5 进度与下一步

已确认的方案（2026-11-03）：编辑全部在后端渲染（ADR-019）、配方存 `edit_history`（ADR-018）、新增 OpenCV 依赖。
- **5.1 显影 ✅**：全屏浏览中按 D 或点“编辑”进入；基本/色彩/细节/效果滑块、旋转/翻转/拉直/裁剪（比例锁定）、
  直方图、对比原图、撤销/重做/历史、编辑后的缩略图与“已编辑”标记。用真实 HEIC/JPG 在浏览器里验证过。
  未验证：RAW 显影（用户库里没有 RAW，`_decode_raw` 只测了错误路径）。
- **5.2 导出与批量 ✅**（ADR-020）：导出对话框（多选操作条和全屏浏览中的“导出”）、后台导出任务（长边、质量、
  保留 EXIF、GPS 默认删除、原图 ICC、同名不覆盖、重启续传）；显影面板的 8 个预设与拷贝/粘贴设置；
  多选操作条可粘贴设置、应用预设。任务结果存 `tasks.result`（迁移 0008）。用真实 HEIC 验证过导出的元数据与 P3 配置文件。
- **5.3 视频基础处理 ✅**（ADR-021）：全屏浏览中按 D 剪辑视频（起点/终点、I/O 键、旋转、静音），编辑后的视频
  按剪辑播放；导出任务支持视频（保持原画质的流复制，或 H.264 重新编码）；导出当前帧。用真实 iPhone MOV
  （含 -90° 显示旋转、空间音频和数据轨）验证过两种导出。没有 HDR 色调映射（用户的视频都是 SDR）。
- **5.4 旅行作品集（下一步）**：`collections`/`collection_items` 表（新迁移）、作品集页面（替换占位页）、
  从图库多选加入、拖动排序、图片说明、封面、按日期+地点建议旅行、批量导出、调用云端分析“生成旅行故事”。

## 10. 测试素材

- `backend/tests/media_factory.py`：生成带 EXIF/GPS 的 JPEG、HEIC、PNG、MP4/MOV、XMP、中文文件名、重复文件。
- 真实照片样本：从 scikit-image 的 wheel 里解压 `skimage/data/*.png|jpg`（astronaut、chelsea 猫、coffee、rocket 等），
  只解压不安装：`pip download --no-deps scikit-image` 后用 zipfile 取出。
- 需要真实 GPU 的测试 `tests/test_ai.py::test_real_siglip2_on_gpu` 在没有 CUDA 或模型时自动跳过。
