# 浊流之上 · 严肃游戏 1.0 运行基线

本分支从 `浊流之上0.5` 的 `eaea2dc160eaed318abd8c73fa4e6ce930749381` 提取运行文件，使用独立提交历史。保留网页/终端客户端、后端、三个剧本包、数据迁移、运行图片、五首 BGM、依赖清单与前端锁文件。

本次是运行文件整理；2026-10-10 问题反馈中的五项新需求尚未在本基线实施。

## 环境与安装

- Python 3.11 或更高；Node.js 22.13 或更高，建议 Node.js 24。
- 在此分支根目录执行以下命令。首次安装依赖需要访问 Python/npm 软件源。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r code/backend/requirements.txt
cd code/frontend/web
npm ci
cd ../../..
```

GitHub 保存 `requirements.txt`、`pyproject.toml`、`package.json` 与 `package-lock.json`；本机依赖目录由上述命令安装。

## 启动网页游戏

在第一个终端，从分支根目录启动后端：

```powershell
.\.venv\Scripts\python.exe code/backend/run_server.py --host 127.0.0.1 --port 8100
```

在第二个终端启动网页：

```powershell
cd code/frontend/web
npm run dev -- --port 3001
```

浏览器打开 http://127.0.0.1:3001 。后端默认使用 SQLite，首次运行自动创建 `code/backend/data/serious_game.db`。终端版可运行根目录 `BEGIN.BAT`。

NPC 对话等 AI 功能需要有效的 OpenAI 兼容服务、模型和 API Key；可在游戏内配置个人模型，或参照 `code/backend/.env.example` 在本地创建 `.env`。服务器默认无模型时，程序会明确提示配置。密钥、玩家存档、私人模型设置不包含在本分支中。

网页默认连接 `http://127.0.0.1:8100`。需分离部署时，设置服务器环境变量 `GAME_BACKEND_URL`；Cloudflare 环境参照 `code/frontend/web/.dev.vars.example`。正式公网部署还需要配置服务端账号认证、数据库及环境安全设置。

## 构建与运行

```powershell
cd code/frontend/web
npm run typecheck
npm run build
$env:PORT = '3001'
$env:HOSTNAME = '127.0.0.1'
npm start
```

后端需要同时运行。生产构建产物在本机生成，图片与音乐由 `public/` 一同打包；运行不需要原始美术工作目录。静态资源与剧本包保持配套，后端启动时会检查场景资源。

完整开发历史、自动化测试和验收记录保留在 `浊流之上0.5`。只下载本运行基线：

```powershell
git clone --single-branch --branch "严肃游戏1.0" https://github.com/cypf420/serious_game.git
```
