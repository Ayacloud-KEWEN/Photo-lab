# LUMEN Studio — 交接文档（HANDOFF）

> 给接手的开发者或新的 Claude 会话：先读本文，再按需读 `docs/`。最后更新：2026-11-04
> （Phase 5 及其后的修复全部合并进 `main`，`main` = `2d58113` 之后的本文更新提交）。

## 1. 一句话现状

Windows 桌面照片/视频管理工作站，**Phase 1–5 及之后的扩展（离线地名、备份恢复、整理）全部完成并合并进 `main`**，工作区干净，没有进行中的分支。
用户（中文沟通）在日常试用，会带着问题或新需求回来。最近一次全面测试（2026-11-04，用用户真实图库的副本）
发现的 5 个问题已全部修复（见第 9 节）；目前没有已知的严重 bug。

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | Tauri + React + Python 后端骨架、SQLite 迁移、文件夹登记 | ✅ |
| Phase 2 | 扫描、元数据、指纹、缩略图、RAW+JPEG 配对、移动/丢失/重复、后台任务 | ✅ |
| Phase 3 | 照片墙、全屏浏览、时间轴、地图、星级/收藏/标签/备注、搜索筛选 | ✅ |
| Phase 4 | SigLIP2 语义搜索/相似照片/自动标签、OpenCLIP 对照工具、DeepSeek 云端分析 | ✅ |
| Phase 5 | 显影（非破坏性编辑）、导出与预设、视频剪辑与导出、旅行作品集 | ✅ |
| 之后 | 实况照片配对、图库悬停播放实况、地图标记修复、全屏滚轮缩放、测试中发现的问题修复、可选底图样式、离线地名、备份与恢复、整理（相似/废片/淘汰/重复文件） | ✅ |

`docs/phases.md` 只规划到 Phase 5，**没有 Phase 6**。下一步做什么由用户决定（候选见第 9 节末尾）。

## 2. 必读文档

| 文件 | 用途 |
|---|---|
| `docs/PROJECT_SPEC.md` | 产品需求（原始需求，勿随意改动） |
| `docs/phases.md` | 阶段划分 |
| `docs/Project_Initialization.md` | Phase 1 任务书（工作方式：先查环境、提方案、经确认再实施） |
| `docs/ARCHITECTURE.md` | **所有架构决策（ADR-001 ~ ADR-028）**，改动架构前先读 |
| `README.md` | 安装、开发、测试、API 列表、快捷键 |

## 3. 环境（用户的开发机）

- Windows 11 Pro，**RTX 4070 SUPER 12 GB**（驱动 610，支持 CUDA 13）
- Python 3.13（`backend\.venv`，已装 `.[dev]`、AI 栈 torch 2.14.1+cu130 / transformers 5.22、open_clip_torch、
  `opencv-python-headless`（Phase 5 新增依赖））
- Node 22.19 / npm、Rust 1.96（MSVC）、VS Build Tools 2019、WebView2（已装系统 HEVC 视频扩展）
- ExifTool 13.60（scoop：`~\scoop\shims\exiftool`），FFmpeg/FFprobe（`D:\Software\ffmpeg-master-latest-win64-gpl\bin`）
- 已下载模型（HuggingFace 缓存 `%USERPROFILE%\.cache\huggingface\hub`）：
  `google/siglip2-so400m-patch14-384`（4.3 GB）、`laion/CLIP-ViT-B-32-laion2B-s34B-b79K`（OpenCLIP 对照用）
- Git 远程：`https://github.com/Ayacloud-KEWEN/Photo-lab.git`（本机没有 `gh` CLI）

**用户的真实数据**（只读参考，2026-11-04）：
- 图库根目录 `D:\Photo 20260612`；数据目录 `%LOCALAPPDATA%\LUMEN Studio`（数据库结构版本 9，缓存约 460 MB）。
- 676 个资产：503 照片（几乎全是 iPhone 16 Pro 的 HEIC/JPG，**没有 RAW**）、173 视频（HEVC，**全部 SDR/bt709**，
  部分带 -90° 显示旋转和空间音频轨）；388 张实况照片；558 个带 GPS；家在巴黎附近。
- 设置：在线地图开、本地 AI 开（已索引 676/676）、云端未配置。用户编辑过 1 张照片（色温），没有作品集。

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

当前检查结果：后端 **164** 个测试、前端 **84** 个测试全部通过；ruff、mypy（strict）、tsc（strict）、clippy 零问题。

### 4.1 在浏览器面板里用真实图库副本测试（推荐的验收方式）

单元测试覆盖不到真实素材（4K HEVC、实况照片、HEIC 的 P3 配置文件等），改完界面后最好这样实测。
**只读用户的原图；数据库和缓存都用副本，绝不写用户的数据目录。**

1. 复制数据（走 UNC 路径，绕过 Claude 桌面版的 MSIX 重定向）到 scratch 目录：
   `Copy-Item "\\localhost\C$\Users\pc\AppData\Local\LUMEN Studio\lumen.db" <scratch>\realdata\`，
   缓存用 `robocopy "...\LUMEN Studio\cache" <scratch>\realdata\cache /E`。
2. 启动后端（PowerShell 脚本放在 scratch 里）：`LUMEN_DATA_DIR=<scratch>\realdata`、`LUMEN_PORT=8765`、
   `LUMEN_TOKEN=devtoken`、`LUMEN_LOG_TO_FILE=false`，PATH 加上 FFmpeg 和 scoop shims，然后 `backend\.venv\Scripts\python.exe -m lumen`。
3. 前端不能用 Vite 开发服务器（内联脚本被面板 CSP 拦截），要：
   `VITE_LUMEN_API_URL=http://127.0.0.1:8765`、`VITE_LUMEN_API_TOKEN=devtoken`、`NODE_ENV=development`，
   `npx vite build --mode development --outDir <scratch>\devdist`，再 `npx vite preview --outDir <scratch>\devdist --port 1420`
   （后端默认 CORS 允许 `http://localhost:1420`）。重建时用同一个 PowerShell 脚本，Git Bash 和 PowerShell 写到的目录可能不同。
4. 浏览器面板打开 `http://localhost:1420`，`resize_window` 设 1440×900。
   注意：自动化的鼠标拖动不会触发 HTML5 拖放（作品集排序要用脚本派发 `DragEvent` 验证）；截图偶尔是旧帧，再截一次。
5. 结束时停掉两个进程（端口 1420/8765），重置视口。**只停自己启动的那两个后台任务**（用任务工具按任务 ID 停，
   或按端口找到的 PID）。**绝不要按命令行 `-m lumen` 匹配去结束进程**：用户自己正在运行的 LUMEN Studio 后端
   也是 `python -m lumen --watch-stdin`（父进程 `lumen-studio.exe`），2026-11-04 曾因此把用户的后端连同导入一起停掉。

## 5. 代码地图

```
backend/lumen/
  __main__.py      进程入口：stdout 握手 {"event":"ready","port":N}，--watch-stdin 退出，过滤 Windows 连接重置日志
  app.py           FastAPI 工厂、中间件（令牌、CORS、请求日志）、生命周期（迁移、TaskRunner）
  core/            config（LUMEN_* 环境变量）、logging（JSON）、security（Bearer 令牌）、volumes
  db/              connection、migrator（前向迁移+校验和+迁移前备份）、migrations/0001–0009
  media/           纯媒体引擎（不碰数据库）：formats、walker、fingerprint、metadata（含 ExifTool 写元数据）、thumbnails
  library/         scan / ingest 流水线、live（实况配对）、trips（旅行建议，纯函数）、exports（导出任务）、
                   search（FTS 重建）、tags、handlers（任务注册表）
  tasks/           queue（SQLite 任务表、任务结果）、runner（后台线程、重试、取消、恢复）
  ai/              models、encoders（SigLIP2/OpenCLIP）、engine、index、labels、pipeline、cloud（DeepSeek）、bench
  develop/         recipe（照片/视频编辑配方）、engine（numpy+OpenCV 渲染、底图缓存）、renditions（编辑后的
                   缩略图、全尺寸图及其 2 GB 上限）、exporter（导出 JPEG）、video（FFmpeg 导出视频与单帧）
  services/        供 API 调用的业务逻辑（assets、develop、exports、collections、folders…）；api/v1/ 路由只做输入输出
desktop/src/
  api/             client.ts、hooks.ts（React Query）、query.ts、schema.d.ts（生成，勿手改）
  library/         layout（等高行布局）、selection（多选）、state（共享筛选、全屏浏览、云端/导出/加入作品集对话框）、useWall
  components/      layout/、library/（PhotoWall、SelectionBar、ExportDialog…）、viewer/（Viewer、ZoomableImage、zoom.ts）、
                   develop/（显影工作区、视频剪辑工作区、TrimmedVideo、裁剪框、滑块、直方图、预设）、
                   collections/（加入作品集对话框）、ai/CloudDialog、settings/AiSettings、ui/
  pages/           Library / Timeline / Map（懒加载）/ AISearch / Collections / Settings
  i18n/locales/    zh-CN（源）、en、fr —— 有测试保证三种语言的键完全一致
desktop/src-tauri/src/  lib.rs、backend.rs（启动/监控/关闭 Python 后端）、job.rs（Windows Job Object）
```

## 6. 必须遵守的约定

1. **原始文件只读**：任何代码都不能写、移动、重命名、删除用户的照片/视频/XMP。编辑结果只存数据库；
   导出只写用户选定文件夹里的新文件，绝不覆盖已有文件。
2. **数据库迁移只增不改**：已发布的 `000N_*.sql` 不能再修改（迁移器校验 SHA-256，改了会拒绝启动）。新改动写新迁移文件。
   SQLite 改 CHECK 约束需重建表；被视图引用的表重建时先 `DROP VIEW` 再重建（见 0004）。
3. **界面中文优先**，新增文案必须同时加 zh-CN / en / fr 三份（`locales.test.ts` 会检查）。
4. **API 类型由后端生成**：改了 Pydantic 模型或路由就 `npm run gen:api`。
5. **隐私**：后端只听 127.0.0.1 + 每次启动的随机令牌；云端 AI 必须经用户逐次确认（后端要求 `confirmed: true`）；
   GPS 默认不上传、导出默认删除 GPS；API 密钥只存 Windows 凭据管理器；在线地图默认关闭。
6. **工作流**（用户已习惯，照做）：
   - 新功能：先给方案（含依赖和架构变更）→ 用户说“按方案实施” → 新分支（阶段用 `phase-N-…`，其余如 `viewer-zoom`）。
   - Bug：先复现、定位原因并说明 → 用户说“开分支修复” → `fix-…` 分支 → 修完在浏览器里实测。
   - 用户说“提交并合并”：提交（结尾附 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`）→ 推送分支 →
     `git merge --ff-only` 进 `main` → 推送 `main`。没让提交就不提交。
   - 回复用中文；完成后告诉用户怎么试用（双击启动程序会自动重建）。
7. 改动架构（ADR 中记录的内容）前先征得用户同意，并在 `docs/ARCHITECTURE.md` 追加 ADR。

## 7. 踩过的坑（新会话很容易再踩）

- **PowerShell 5.1 按 GBK 读取无 BOM 的 .ps1**：`scripts/*.ps1` 必须保持纯 ASCII（中文写在 README 里）。
- **用 Python 脚本改文件时务必 `encoding="utf-8"`**（系统默认 GBK）。Git Bash 里的 heredoc 遇到复杂引号、反斜杠、`\n`
  容易出错（`D:\Exports` 这类路径尤其），复杂编辑写成 scratch 目录下的 .py 文件，或直接用 Edit 工具。
- **从 Claude 桌面版里启动应用时**，Windows（MSIX 虚拟化）会把 `%LOCALAPPDATA%` 的写入重定向到
  `…\Packages\Claude_…\LocalCache\Local\`，所以那里的数据库和用户双击启动时看到的不是同一个。
  测试用临时数据目录（`LUMEN_DATA_DIR`），给用户用的数据让用户自己启动。
  需要**只读**查看用户真实的日志/数据库时，走 UNC 路径绕过重定向：
  `\\localhost\C$\Users\pc\AppData\Local\LUMEN Studio\logs\backend.log`（JSON 行，可按 level 统计）。
- **子进程绝不能继承后端的 stdin**：桌面版里后端的 stdin 是 Tauri 的管道，`--watch-stdin` 线程一直挂着一个读操作。
  在 Windows 上 ffmpeg 处理超过约 0.5 秒后会去轮询 stdin，然后一直卡到超时。
  所有 `subprocess` 调用都要 `stdin=subprocess.DEVNULL`，ffmpeg 还要加 `-nostdin`（`develop/video.py` 的导出也一样）。
  pytest 下复现不了，所以由 `test_video_tools_never_inherit_stdin` 检查调用参数。
- **部分导出视频的色彩标记是保留值**：ffmpeg 报 `Invalid color space`。`thumbnails._video_frame` 会用比特流过滤器
  （`h264_metadata` / `hevc_metadata`）把标记改成“未指定”后重试。迁移 0005 会重试此前失败的文件。
- **媒体 URL 的版本参数**：`rendition_version` 在编辑后会变（`<指纹>-<配方哈希>`）。缩略图要跟着变，
  但原文件/实况片段的 URL 只能用内容版本（`originalUrl`/`motionUrl` 内部已处理），否则每次自动保存都会
  让 `<video>` 重新下载整个视频（剪辑 4K 视频时播放位置被重置，I/O 设点出错）。
- **MapLibre 标记的外层元素不能加 Tailwind 的 `scale-*`/`hover:scale-*`**：MapLibre 用行内 `transform` 定位标记，
  而 Tailwind v4 的缩放是独立的 CSS `scale` 属性，会叠加在定位之后、连平移距离一起放大，悬停时标记被推离鼠标，
  于是点不中。缩放效果放在内层元素上（`MapPage.tsx` 的 `markerElement`）。
- **MapLibre 的 Web Worker** 用 `?raw` 源码 + `blob:` URL 启动（`MapPage.tsx`），不要改回默认路径或 `?url`。
- **浏览器预览面板被遮挡时 requestAnimationFrame 会暂停**：MapLibre 不触发 `load`、截图超时。截一张图会唤醒渲染。
- **Tauri CSP**（`tauri.conf.json`）：视频需要 `media-src`，地图需要 `worker-src blob:`，显影预览需要 `img-src blob:`，
  在线地图需要 `https://tiles.openfreemap.org`。显影直方图在跨域响应头 `X-Histogram` 里，CORS 已 `expose_headers`。
- **Windows 上 asyncio 的 `ConnectionResetError`**：webview 取消图片请求时 Proactor 事件循环会记 ERROR，
  `__main__._quiet_connection_resets` 把这一种过滤掉了，其余异常照常记录。
- **SigLIP 的 sigmoid 概率对中文查询几乎全为 0**：不能当阈值。搜索用余弦（0.075），自动标签用标签间 softmax 占比（0.25）。
  第一次 AI 搜索要加载模型（约 17 秒），之后约 50 毫秒。
- **jsdom 没有布局、不加载图片**：虚拟列表测试要 mock `clientWidth/clientHeight`（`fakeViewport`）；
  缩放测试要给 `<img>` 定义 `naturalWidth/naturalHeight` 再 `fireEvent.load`；object URL 在 `test/setup.ts` 里打桩。
- **应用运行在 React StrictMode 下**：开发模式会把副作用“卸载再挂载”一次。带请求/中止的 hook（如 `useDevelopPreview`）
  的清理函数必须把状态复位；显影测试因此包在 `<StrictMode>` 里。
- **全屏浏览器的快捷键挂在对话框根元素上**：焦点所在元素被移除（退出显影时的滑块、导出开始后的按钮）后要把焦点还给根元素；
  焦点在滑块上时只让出方向键/Home/End，其余快捷键照常生效。
- **HuggingFace 在 Windows 无法建符号链接**（未开开发者模式），会有警告，无害；启动脚本已屏蔽该警告。

## 8. 已知未完成 / 待验证（按优先级）

1. **RAW 显影和 RAW 解码都没用真实 RAW 文件验证过**（用户库里没有 RAW；`develop.engine._decode_raw` 只测了错误路径）。
   用户有 CR3/NEF/ARW/DNG 样本时优先验证。
2. **DeepSeek 未用真实 API 密钥测试过**（“生成旅行故事”、云端点评等都依赖它）；用户填入密钥后用“测试连接”确认。
3. ~~数据库备份与恢复~~ 已完成（ADR-024）；恢复只在副本上实测过，用户真实数据未做过恢复。
4. **正式打包**：PyInstaller 打成 `lumen-backend.exe`（Tauri externalBin，`backend.rs` 已预留），随附 ExifTool/FFmpeg，
   NSIS 安装包；AI 栈体积大（torch ~3 GB），需决定是否作为可选组件。当前启动程序依赖项目里的 `backend\.venv`。
5. **阈值只在小样本上校准**：语义搜索 0.075、自动标签 0.25、相似照片 0.6（`services/ai.py`、`ai/labels.py`）。
6. 失败任务没有专门的查看/重试界面（重复文件界面已完成，ADR-026）。
7. HDR 视频转 H.264 没有色调映射（会偏灰）；显影模式里不能缩放查看细节；窗口缩放时已放大的视图不重新校正位置。
8. 外接硬盘换盘符后按卷序列号自动认回（ADR-028，只用单元测试验证过，subst 盘没有序列号）；删除来源后缩略图缓存不会自动清理
   （全尺寸图有 2 GB 上限，缩略图/预览图没有）。
9. AI 标签名固定为中文（不随界面语言变化）。
10. 性能：导入默认 8 线程（`ingest_workers`，ADR-027）；HEIC 无降采样解码（12MP 约 1 秒/张）；AI 索引约 44 张/秒；
    前端主包超过 500 KB（构建时 Vite 会提示，可懒加载 AI/作品集页面）。第一次 `GET /ai/status` 约 6 秒（导入 torch）。

## 9. 最近完成的工作（2026-11-03 ~ 04）

按时间顺序，均已合并进 `main`：
- **导入修复**：ffmpeg 继承 stdin 导致的超时（1000 多个文件导入从几十分钟降到约 3 分钟）、保留色彩标记的 MP4（迁移 0005）。
- **实况照片**（ADR-017，迁移 0006）：静态照片与 MOV 按 ContentIdentifier 配对；查看器和图库瓦片悬停 LIVE 播放。
- **Phase 5**（分支 `phase-5-studio`，4 个提交）：
  - 5.1 显影（ADR-018/019，迁移 0007）：全屏浏览按 D；滑块、裁剪/旋转/拉直、直方图、对比原图、撤销/历史。
  - 5.2 导出与批量（ADR-020，迁移 0008）：后台导出任务（不覆盖、ICC、EXIF、默认去 GPS、续传）、8 个预设、拷贝/粘贴设置。
  - 5.3 视频剪辑（ADR-021）：起止点（I/O）、旋转、静音、按剪辑播放、流复制或 H.264 导出、导出当前帧。
  - 5.4 旅行作品集（ADR-022，迁移 0009）：作品集页面、拖动排序、说明、封面、旅行建议、按序号导出、旅行故事。
- **地图标记点不中**（`fix-map-markers`）：Tailwind `scale` 与 MapLibre `transform` 冲突，见第 7 节。
- **全屏滚轮缩放**（`viewer-zoom`）：以鼠标为中心缩放到原始像素 400%、拖动平移、双击/Z 切换 100%、Esc 先回适合窗口；
  放大时加载全尺寸图（未编辑的 JPEG/PNG 用原文件，其余用 `thumbnail?variant=full`）。
- **全面测试后的修复**（`fix-review-issues`）：视频剪辑时反复重新加载、全尺寸缓存 2 GB 上限、导出后 Esc、
  设置页空检查器、日志里的连接重置噪音。测试方法见 4.1；当时用户真实日志里修复后没有任务/渲染/导出错误。
- **可选底图样式**（`map-basemaps`）：设置项 `map_style`（深色/彩色/明亮/浅灰 = OpenFreeMap 同名样式；离线时深色/浅色），
  设置页和地图页左下角切换，`setStyle` 原地换底图（见 ARCHITECTURE 第 16 节）。
- **离线地名**（`offline-places`，迁移 0010，ADR-023）：GeoNames 数据随程序发布（`lumen/geo/`），检查器/筛选/搜索/
  地图/旅行建议显示城市·地区·国家；`python -m lumen.geo.build <目录>` 重新生成数据。
- **数据库备份与恢复**（`db-backup`，ADR-024）：自动/手动备份、可换文件夹、恢复前另存当前数据，不重启进程
  （`services/backups.py`、`TaskRunner.paused()`）。SPEC 的 MVP 项至此全部完成。
- **整理**（`cull`，迁移 0011，ADR-025）：保留/淘汰标记（X/P，淘汰默认隐藏、不删文件）、画质评分
  （`library/quality.py`）、相似照片分组与推荐（`services/cull.py`）、整理页（Ctrl 6）。
- **重复文件**（`duplicates-ui`，ADR-026）：整理页“重复文件”标签，合并副本为一张照片（只改数据库），
  扫描时封面换到仍在场的副本（`scan.switch_missing_covers`）。用户库副本上 9 组、约 85 MB。
- **大图库性能**（`fix-import-performance`，ADR-027）：实况配对查询不再全表扫描；导入改为滑动窗口
  （8 线程，机械硬盘 2 个并发读）；导入期间界面少刷新；统计/地图/旅行建议/重复文件按写入代数缓存；
  相似照片用内存向量并缓存分组、分页；AI 搜索页打开时预热模型。G: 盘实测导入约快 2 倍。
- **外接硬盘断开**（`fix-drive-offline`，ADR-028）：扫描/导入中途拔盘不再误标丢失（来源 offline、任务暂停）；
  `library/drives.py` 每 30 秒检查，插回后自动扫描并继续导入，换盘符时按卷序列号认回；全屏浏览提示原图所在盘未连接。

**用户的图库（2026-11-04 晚）**：来源 `D:\照片`（SSD）、`G:\照片整理202507`、`G:\照片整理`（USB 机械硬盘，
14.4 万个文件、678 GB，当时仍在导入）；约 19 万个文件。性能问题先在这个规模上验证（方法见 4.1，副本 + 关闭后台任务）。

**注意（2026-11-04 测试时发现）**：用户的图库根目录 `D:\Photo 20260612` 当时不存在（被移动或改名？）。
数据库和缓存都在，缩略图照常显示，但编辑过的照片、原图查看、导出、在资源管理器中显示都要等原文件回来。
用户回来时先问清楚，必要时把新位置添加为照片来源并扫描。

**下一步候选**（等用户选，按价值排序的建议）：
1. 正式打包（安装包，不再依赖项目里的 `.venv`）。
2. 失败任务的查看/重试界面。
3. 作品集幻灯片放映 / 导出为网页画廊；旅行故事保存到作品集；“那年今日”；智能相册。
4. 用户提供 RAW 样本后验证 RAW 显影；HDR 视频色调映射。

## 10. 测试素材

- `backend/tests/media_factory.py`：生成带 EXIF/GPS 的 JPEG、HEIC、PNG、MP4/MOV（可带音轨）、XMP、中文文件名、重复文件。
- 真实照片样本：从 scikit-image 的 wheel 里解压 `skimage/data/*.png|jpg`（astronaut、chelsea 猫、coffee、rocket 等），
  只解压不安装：`pip download --no-deps scikit-image` 后用 zipfile 取出。
- 用户真实图库的副本：见 4.1（推荐用于界面验收）。
- 需要真实 GPU 的测试 `tests/test_ai.py::test_real_siglip2_on_gpu` 在没有 CUDA 或模型时自动跳过。
