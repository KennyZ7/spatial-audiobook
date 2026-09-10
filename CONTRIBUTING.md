# 私密协作与本地运行

仓库为 KennyZ7/spatial-audiobook。协作者接受 GitHub 邀请后即可克隆；这不是公网运行的网站。

## 首次安装

需要 Python 3.12，Windows 推荐使用 Python 官方安装包并启用 Python Launcher。

```powershell
git clone https://github.com/KennyZ7/spatial-audiobook.git
cd spatial-audiobook
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
.venv/Scripts/python.exe scripts/import_example.py
.venv/Scripts/python.exe -m uvicorn studio.app:app --host 127.0.0.1 --port 8765
```

若没有 `py -3.12`，可用 `scripts/setup.ps1 -Python '你的python.exe完整路径'`，或设置 `SPATIAL_PYTHON`。安装需要联网获取 PyPI 依赖、SADIE II 和 Kenney 音效，不调用模型 API。

macOS / Linux 可依次运行 `python3.12 -m venv .venv`、`.venv/bin/python -m pip install -r requirements.lock.txt`、`.venv/bin/python scripts/setup_assets.py`、`.venv/bin/python scripts/setup_recorded.py`、`.venv/bin/python scripts/import_example.py`，最后用该 Python 执行上述 uvicorn 命令。Windows 系统语音演示脚本不适用于其他平台；跨平台流程尚未实机验证。

访问 http://127.0.0.1:8765 。导入示例包含已有干声，可免费重新渲染；仅试听已提供的 mix.wav 或查看 timeline.html 不需要安装或 API。生成新台词需在界面配置自己的 DeepSeek / MiniMax 密钥并核对费率。

## 检查与协作

```powershell
.venv/Scripts/python.exe -m pytest -q
git switch -c feature/your-change
```

浏览器检查为可选：安装 Node.js 与 Playwright，执行 `npm install --no-save playwright`，然后 `node scripts/check_reports.cjs`（需要 Edge）。也可用 `PLAYWRIGHT_MODULE` 指定模块路径、`REPORT_FILE` 指定报告。`scripts/browser_check.cjs` 会触发本机免费渲染并写入明确标注的自动化反馈，只在测试数据环境执行。

通过 Pull Request 交流修改，描述问题、变化及测试。不要提交 data、密钥、日志、原始申报书或学号、联系方式。发布前复核 Git 暂存清单。不要为了协作共享 API Key。

`scripts/seed_demo.py` 会覆盖 demo_suspense 工程。`scripts/enhance_surround.py` 针对原作者场景 ID；共享副本已有增强结果，不必再运行它。启动脚本若发现服务已运行只会打开网页；更新后端后应在终端停止旧 uvicorn 并重新启动。

## 示例来源

示例文本为项目原创悬疑短场景，干声和混音仅用于本项目协作演示，不授予第三方音色克隆权利。Kenney 素材及派生脚步为 CC0，来源与许可随素材目录保留；SADIE II 通过安装脚本获取，许可见 THIRD_PARTY.md。仓库未额外授予项目源码的开源许可。
