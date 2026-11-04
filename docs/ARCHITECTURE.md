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
     并作为封面），`.xmp` 为 `sidecar`；视频不在这一步与照片配对（实况照片在写入元数据后配对，见 ADR-017）；
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
- 全屏浏览显示 2048px 预览，可用滚轮以鼠标为中心缩放、拖动平移（`viewer/zoom.ts` 纯函数 + `ZoomableImage`）；
  第一次放大时加载全尺寸图：未编辑的 JPEG/PNG 直接用原文件，其余（HEIC、RAW、编辑过的照片）用
  `thumbnail?variant=full`——按编辑配方全尺寸显影、带原图 ICC，按需生成并缓存在缩略图目录（`<digest>[_e<hash>]_f1.jpg`）。
  全尺寸图每张 2–6 MB，总量超过 2 GB 时删除最久未用的（每次打开会刷新修改时间，每次新生成后清理）。
- 原文件和实况片段的 URL 只带内容版本（`rendition_version` 中 `-` 之前的部分，前端 `contentVersion`）：
  编辑只改变缩略图，保存编辑不会让 webview 重新下载视频。
  视频直接播放原文件（`/original` 支持 Range）。
- 地图使用 MapLibre；照片在前端用 Supercluster 聚合，气泡用 HTML 标记显示缩略图，因此离线
  底图不需要字体文件。离线底图来自 `world-atlas`（Natural Earth 1:50m 国界，按需加载）。
- 底图样式是设置项 `map_style`（`dark` 默认 / `liberty` / `bright` / `positron`）：在线时就是 OpenFreeMap
  同名样式（同一域名，CSP 不变）；离线时 `dark` 用深色国界图，其余用浅色国界图。设置页和地图页左下角都能切换；
  切换时用 `map.setStyle()` 原地换底图，视野和照片标记（HTML 元素，不在样式图层里）都保留。
- MapLibre 的 Web Worker 以原始源码（`?raw`）通过 `blob:` URL 启动：MapLibre 默认按自身模块
  路径寻找 worker，打包后会失效；CSP 中对应放开 `worker-src blob:`。
- CSP 中新增 `media-src`（视频）和 `https://tiles.openfreemap.org`（仅在线地图使用）。

## 17. 本地 AI 引擎（ADR-014，Phase 4）

- 首选模型 **SigLIP2 so400m/14 @384**（`google/siglip2-so400m-patch14-384`）：多语言，中文查询无需翻译；
  RTX 4070 SUPER 上 fp16 约占 3.4 GB 显存，首次加载约 13 秒。也可选 SigLIP2 base（更快更小）。
- **OpenCLIP** 作为生态与对照：同一 `Encoder` 接口下的第二个后端，并提供 `lumen.ai.bench` 对照工具。
  小样本测试中，英文查询两者相当，中文查询 OpenCLIP ViT-B/32 的 R@1 只有 0.44（SigLIP2 为 1.0）。
- 依赖可选：`pip install -e .[ai]`（PyTorch CUDA 版从 PyTorch 官方源安装）。未安装时其余功能照常，
  AI 相关接口返回 `ai_not_ready`。
- 模型在进程内按需加载（GPU 可用时 fp16），空闲 `ai_idle_unload_s`（默认 600 秒）后卸载以释放显存。
- 模型文件放在 HuggingFace 标准缓存中，与其他工具共用，不在应用数据目录里重复保存。

## 18. 向量化、搜索与标签（ADR-015）

- 后台任务 `ai_index_assets`：读取已缓存的 400px 缩略图（不再解码原图/RAW），批量编码，
  向量（float16、已归一化）存入 `embeddings(asset_id, model_id)`；入库新文件后自动追加；
  封面内容（指纹）或标签词表版本变化时重算。
- 搜索：内存中的精确余弦检索（10 万张 × 1152 维 ≈ 230 MB），写入后失效重载；可与所有筛选条件叠加。
- **相关度阈值**：SigLIP 的 sigmoid 概率对中文查询几乎都接近 0，不可用作阈值；余弦相似度区分清楚
  （真实匹配约 0.10–0.13，无关照片约 0.03–0.06），因此以余弦 0.075 作为"明显相关"，其余结果
  按需展开（`relevant_count`）。阈值来自少量样本，后续用真实照片库校准。
- **自动标签**：约 50 个中文场景/主体标签，每个用多条英文提示词的平均向量。绝对概率同样不可用，
  改为对全部标签做 softmax（使用模型自身的 logit scale），占比 ≥ 0.25 才打标签（最多 3 个）。
  标签以 `source='ai'` 和置信度写入 `media_tags`；重新标注只替换 AI 标签，不动用户和导入的标签。

## 19. 云端分析（ADR-016）

- 供应商：DeepSeek（OpenAI 兼容的 Chat Completions 接口，标准库实现，无额外依赖）。默认模型
  `deepseek-flash`：据第三方资料，DeepSeek 自 2026 年 8 月起在该模型上支持图片输入（每张图约 384 token），
  官方文档未能直接核实，因此提供"测试连接"实际检测，并在模型拒绝图片时提供"仅文字"降级
  （发送拍摄参数和本地 AI 标签，结果明确标注不是基于画面）。模型 ID 和 API 地址可在设置中修改。
- 隐私：默认关闭；API 密钥存 Windows 凭据管理器（`keyring`）；每次请求先调用 `/preview`
  显示目标主机、模型、缩略图和随附字段，用户确认后前端才调用 `/analyze`（后端要求 `confirmed: true`）；
  图片为缩小副本（长边 640–1024 px）；GPS 默认不发送，需逐次勾选。
- 缓存：按 供应商/模型/提示词版本/语言/选项/照片指纹 计算 `cache_key`，相同请求直接返回结果，不再上传。
- 结果为 Markdown（前端用 react-markdown 渲染，不允许原始 HTML）；"AI 选片"要求先输出一行 JSON
  （最佳与排名），解析后在界面上标出最佳照片。

## 20. 实况照片（ADR-017）

- iPhone 实况照片由一张静态照片（HEIC/JPG）和一段约 1.5–3 秒的 `.MOV` 组成，两者写有相同的
  `ContentIdentifier`（照片在 MakerNotes，视频在 QuickTime Keys）。导入时读取该值存入
  `media_metadata.content_identifier`（迁移 0006）。
- **配对规则**（`library/live.py`）：同一目录内的照片与 `.MOV`，
  两者都有 `ContentIdentifier` 时以是否相等为准；任一方缺少时，要求同名且视频不超过 4 秒。
  "照片"导出会改名并带原版/编辑版（如 `SWDK1197.JPG` ↔ `GYFF2926.MOV`、`SWDKE1197.JPG` ↔ `GYFFE2926.MOV`，
  四个文件同一个 ID）：不同名时只配"同为原版"或"同为编辑版"的一对，与导入顺序无关。
- 配对发生在每批结果写入之后（需要两边的元数据），无论照片或视频谁先导入都会配上。视频成为照片资产的
  `companion`（不新增 `file_role`），资产类型仍为 `photo`，封面与拍摄时间仍以照片为准。
  视频原先若是独立资产：星级（用户设置的优先、取较高者）、收藏、备注、用户/导入标签和位置合并到照片资产，
  AI 标签不合并（它描述的是封面），然后删除该视频资产（向量等随之级联删除）。
- 是否为实况由"存在 `.mov` 的 `companion` 文件"推导，列表返回 `is_live`，详情返回 `motion_file_id`；
  视频片段由 `GET /assets/{id}/motion` 提供（与 `/original` 一样支持 Range 和 `?token=`）。
- 片段为 HEVC，不转码，直接由 WebView2 播放（需系统的 HEVC 视频扩展）；播放失败时只显示静态照片。
- 已有数据：迁移 0006 把 MOV/HEIC/JPG 重新标为待处理，只重读元数据（指纹与缩略图保留），由同一配对逻辑处理。

## 21. 非破坏性编辑（ADR-018，Phase 5）

- **编辑配方**（`develop/recipe.py`）：一张照片的全部调整是一份带版本号的 JSON：
  曝光（EV）、对比度、高光、阴影、白色/黑色色阶、色温、色调、自然饱和度、饱和度、清晰度、锐化、暗角，
  以及几何（顺时针 90° 旋转次数、水平翻转、拉直角度、裁剪框）。几何按"旋转 → 翻转 → 拉直 → 裁剪"的顺序应用，
  裁剪框是相对于旋转、拉直后画面的比例坐标，所以与分辨率无关（预览与将来的全尺寸导出一致）。
  默认值等于"未编辑"；内容哈希对浮点取 4 位小数，"全部为默认"的配方哈希为空串。
- **存储**（迁移 0007）：`edit_history` 只追加，每行一份配方及其哈希；`media_assets.current_edit_id`
  指向生效的一步（`NULL` 为原图）。撤销/重做/点历史只移动指针；在撤销后保存新的一步会删掉被撤销的步骤
  （线性历史，与常见编辑器一致）；每张照片最多保留 100 步。"全部重置"也是一步（配方为默认，显示原图）。
- **显影源文件**：资产的 `primary` 文件（RAW+JPEG 时为 RAW，实况照片为静态照片），不可用时退回封面；
  视频和原文件不可用的照片返回 409 `develop_unavailable`。原文件只读，编辑结果只存在数据库和缓存里。
- **编辑后的缩略图**：`renditions/` 下按"源文件指纹 + 配方哈希"命名（`<digest>_e<hash>_t1.jpg`），
  首次请求时渲染；`rendition_version` 变为 `<指纹>-<哈希前 8 位>`，所以照片墙、时间轴、地图的 URL 随编辑变化。
  撤销回某一步时直接复用该步的缓存。列表与详情返回 `is_edited`，照片墙显示"已编辑"标记。
  编辑过的照片不提供 1:1 原图查看（原图是未编辑的）。AI 向量与云端分析仍基于原图。

## 22. 显影渲染（ADR-019）

- **全部在后端渲染**（`develop/engine.py`，numpy float32 + OpenCV），前端只显示结果：屏幕上看到的与将来导出的
  出自同一份代码，不会因 WebGL 与 numpy 两套实现而不一致。代价是每次调整约 100 ms（1600 px、全部滑块启用；
  只有一两项时更快），前端保持"同时最多一个请求、返回后渲染最新配方"，拖动时不会积压。
- **解码只做一次**：按（路径、修改时间、大小、目标尺寸）缓存最近 6 张解码后的底图（只读数组）。
  JPEG 用 libjpeg 缩小解码；HEIC 经 pillow-heif 解码后缩放；RAW 用 LibRaw 去马赛克（相机白平衡、16 位，
  目标尺寸足够小时用半尺寸解码）。HDR 增益图不参与，按 SDR 处理。
- **调整在编码（sRGB）空间中进行**：按 2.2 幂律，线性光中的增益 g 等价于编码值乘 g^(1/2.2)，
  因此曝光、白平衡与黑白色阶合并为每通道一次仿射运算，无需与线性空间来回转换。
  阴影/高光用模糊后的亮度作局部遮罩（在缩小的图上模糊，速度与半径无关）；清晰度为中间调的局部对比度；
  对比度为以中灰为支点的 S 曲线混合；自然饱和度对低饱和颜色作用更强；暗角按画面椭圆半径平滑过渡。
  拉直时自动放大，保证四角不出现空白。
- **接口**：`POST /assets/{id}/develop/preview` 接受未保存的配方和长边尺寸（256–2560），返回 JPEG，
  `X-Histogram` 头带 64 档 RGB 直方图（前端用 SVG 绘制，不需要 canvas）；CORS 暴露该头。
  保存由前端在停止调整约 0.6 秒后（松开滑块后 0.15 秒）发出，离开显影或切换照片时立即保存未保存的修改。
- 依赖：新增 `opencv-python-headless`（SPEC 技术栈中已列出 OpenCV）。

## 23. 导出与批量调整（ADR-020）

- **导出是后台任务**（`export_assets`，`library/exports.py`）：把每张照片按其当前编辑配方全尺寸显影
  （不进底图缓存，避免大图占满内存；指定长边时只按裁剪后够用的尺寸解码），再缩放、写成新的 JPEG。
  原文件只读；导出文件名沿用原文件名（RAW+JPEG 取 RAW 的名字），**已存在的文件绝不覆盖**——
  先用 `O_EXCL` 占用一个空闲名称（`IMG_0001 (2).jpg`），写入同目录临时文件后再替换占位。
  视频和原文件不可用的照片跳过；单张失败记录后继续，全部失败才算任务失败。
- **颜色**：显影在原图的色彩空间里进行（iPhone 为 Display P3），导出时写入原图的 ICC 配置文件；RAW 显影为 sRGB。
- **元数据**：默认用 ExifTool 从原图复制 EXIF/XMP/IPTC（`-TagsFromFile … -all:all`），并修正方向为 1、
  图像尺寸、删除内嵌缩略图；**GPS 默认删除**，每次导出时单独勾选才保留（不记住该选项）。
- **进度与续传**：每张照片后写一次进度；应用重启后任务从已完成的位置继续，不会重复导出。
  任务结果写入 `tasks.result`（迁移 0008，JSON），`GET /exports/{id}` 返回进度和结果
  （导出数量、跳过数量、失败列表）。导出任务不与其他导出合并（`enqueue(unique=False)`）。
- **批量调整**：`POST /edits/batch` 接受一份配方和要采用的字段列表，对每张照片在其当前编辑上覆盖这些字段并
  新增一步历史（已相同则不变）。"拷贝/粘贴设置"只带色调、色彩、细节、效果，不带旋转、翻转、裁剪；
  预设（内置 8 个，定义在前端 `presets.ts`）只设置它列出的值，其余调整保留。

## 24. 视频基础处理（ADR-021）

- **视频配方**（`VideoRecipe`，与照片配方同存 `edit_history`，以 `"kind": "video"` 区分）：保留的起止时间（毫秒，
  终点为空表示到结尾）、额外的顺时针 90° 旋转次数、是否静音。原文件只读，`is_edited`、`rendition_version`
  与照片一致；编辑后的缩略图是原缩略图按旋转转过的副本（只有剪辑或静音时直接用原缩略图）。
  接口：`GET/PUT /assets/{id}/video-edit`（终点超过时长视为"到结尾"，起点超过时长报 400）。
- **播放**：前端 `TrimmedVideo` 只播放保留部分、静音、用 CSS 旋转画面（竖向时交换宽高）；原生控件会随画面旋转，
  所以使用自己的播放/拖动条（浏览模式只覆盖保留部分，编辑模式覆盖全片并标出保留部分）。
- **导出**（同一个导出任务和对话框）：
  - "保持原画质"：`-c copy`，容器与原文件相同，几乎瞬间完成；切点对齐到关键帧（可能早几百毫秒）；
    旋转写入显示矩阵（原有旋转再加上编辑的旋转，`-display_rotation`）。
  - "转为 H.264"：重新编码为 8 位 4:2:0 的 MP4（CRF 20，AAC 192k），切点精确，旋转由 `transpose` 完成。
  - 只取第一路视频和第一路音频（iPhone 文件里的空间音频与数据轨不带走）；元数据用 `-map_metadata 0` 并保留
    QuickTime 键（品牌、型号、拍摄时间），GPS 默认清除（`location`、`com.apple.quicktime.location.ISO6709`）。
  - ffmpeg 无 stdin（`-nostdin`），用 `Popen` 运行，取消或退出应用时会被结束，临时文件删除。
  - 用户库里的视频都是 SDR（bt709）HEVC，因此没有做 HDR 到 SDR 的色调映射；HDR 视频转 H.264 会偏灰（待需要时再做）。
- **导出当前帧**：`POST /assets/{id}/frame-export` 把指定时间的画面（按编辑旋转）存成新 JPEG
  （`<原名>_<分-秒>.jpg`，不覆盖），文件夹沿用上次导出的位置。

## 25. 作品集与旅行（ADR-022）

- **表**（迁移 0009）：`collections`（名称、类型 `album`/`trip`、简介、地点、起止日期、可选封面）与
  `collection_items`（资产、整数位置、说明）。作品集只引用资产：删除作品集不碰照片，删除资产时条目级联删除；
  实况照片配对时，视频资产所在的作品集改由配对后的照片资产占据原位置（`live._merge_user_data`）。
- **顺序**：追加到末尾；`PUT /collections/{id}/order` 必须给出全部条目（整体重排、重新编号），
  前端用 HTML5 拖放，松手后一次提交。封面未设置时用第一项；被移出的封面自动清除。
- **旅行建议**（`library/trips.py`，纯函数）："家"是有位置照片最多的 0.1° 网格；离家超过 50 公里的照片开始一段旅行，
  期间没有位置的照片也算在内，相邻两张间隔超过 48 小时或回到家附近的照片结束旅行；至少 5 项才建议；
  结尾没有位置的照片不计入。与已有旅行作品集日期重叠的不再建议。建议带上照片最多的城市和国家
  （第 26 节），以“地点 · 日期”命名并填入作品集的地点；没有地名时以日期命名。在用户库的副本上找到 3 段旅行（布列塔尼、法国西部、马特洪峰）。
- **导出与故事**：作品集按自身顺序导出，默认"按顺序编号文件名"（`numbered`：`001_IMG_0001.jpg`）；
  "生成旅行故事"沿用 Phase 4 的云端分析（`story`，前 30 项，逐次确认上传内容）。

## 26. 离线地名（ADR-023）

- **数据**：GeoNames（CC BY 4.0）的人口 1000 以上的地点（约 16 万）、省/大区和国家，只保留中文
  （`zh-CN` > `zh-Hans` > `zh`）和法文名称，英文用 GeoNames 的国际名称。`python -m lumen.geo.build <目录>`
  下载原始数据（`cities1000.zip`、`alternateNamesV2.zip` 约 200 MB 等，只在生成时用）并写出
  `backend/lumen/geo/data/places.tsv.gz`（约 3.6 MB，随程序发布，第一行是数据版本）。运行时完全不联网。
- **去掉以城市命名的城区**："Paris 15 Vaugirard" 这类名字以 25 公里内更大城市开头的地点不收录，
  这些照片归到城市本身。
- **查找**（`geo/places.py`）：没有边界数据，所以按"覆盖半径"选地点：距离除以随人口增长的半径
  （1 000 人约 1.5 公里，200 万人约 19 公里），取最小者；大城市胜过旁边的村子，郊区城镇在自己中心附近仍用自己的名字。
  全部地点的单位向量（float64，float32 下几公里的余弦会被舍入成 1）常驻内存，约 0.4 秒加载，每 700 个点约 1 秒。
- **表**（迁移 0010）：`media_places`（每个有位置的资产一行）保存城市/省/国家的三种语言名称、距离、
  数据版本和所依据的 `media_locations.updated_at`；搜索视图加入全部名称，"巴黎""Paris""Italie"都能搜到。
- **任务** `geo_locate_assets`：导入结束后、以及启动时发现有未命名/位置已变/数据版本不同的资产时排队；
  删除了位置的资产同时删除地名。
- **接口**：资产详情 `place`；筛选 `country`（ISO 代码）/ `place_id`；统计 `places`（国家 → 城市）；
  地图点 `p` + `places`；旅行建议 `cities`/`countries`。前端按界面语言显示（`lib/places.ts`）。

## 27. 数据库备份与恢复（ADR-024）

- **备份**（`services/backups.py`）：用 SQLite 在线备份 API 把 `lumen.db` 复制成一个独立文件，应用照常运行。
  先写 `*.partial`，`PRAGMA quick_check` 通过后再改名，所以不会留下写了一半的备份。内容是全部用户数据
  （评分、标签、备注、编辑、作品集、AI 向量与标签、地名、设置）；缩略图缓存可重建，不备份；
  云端 API 密钥在 Windows 凭据管理器里，不在数据库中。
- **文件名**（本地时间，精确到毫秒，按名称排序即按时间）：`lumen-backup-*`（手动）、`lumen-auto-*`（自动）、
  `lumen-before-restore-*`（恢复前自动另存）；迁移器升级前写的 `lumen-v000N-*` 也列出来，可以恢复。
- **设置**：`backup_auto`（默认开）、`backup_interval_days`（默认 7）、`backup_keep`（默认 10，只删除最旧的
  **自动**备份，其他种类从不删除）、`backup_folder`（默认 `<数据目录>ackups`，建议换到另一块硬盘；
  传空字符串恢复默认）。启动时（以及开启自动备份或更换文件夹时）如果距上一次自动备份已满间隔、且库里有资产，
  就排队 `db_backup` 任务；文件夹不可用时任务失败、不重试，设置页显示"找不到文件夹"。
- **恢复**：可以选列表里的备份，或任意 `.db` 文件（换电脑时）。先只读打开做 `integrity_check`、确认是 LUMEN 数据库、
  用迁移器的 `check_compatible` 拒绝更新版本或被改过的迁移；然后暂停后台任务（`TaskRunner.paused()`，正在运行的
  任务放回队列；15 秒内停不下来就返回 409）、另存一份"恢复前"备份、用备份 API 把备份内容逐页写回正在使用的数据库
  （不重启进程，其他连接之后看到新内容）、运行迁移把旧版本升级到当前版本，再清空内存中的 AI 向量缓存、
  按需排队地名任务。备份相关的四个设置保持恢复前的值（不随备份回退）。前端成功后让全部查询失效重新获取。
- **在资源管理器中显示**：`core/reveal.py` 用 `explorer /select,` 打开（stdin 为 DEVNULL），只接受列表里的备份名。
- 接口：`GET/POST /backups`、`POST /backups/restore`（`name` 或 `path`）、`POST /backups/reveal`。
