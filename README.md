# Voxlush Gen

体素资产生成器：Python 后端、React 面板、Docker 隔离执行，支持主题任务、归档、导出和备份恢复。示例配置为离线模式，可启动面板和本地诊断。

## 安装

需要 Python 3.12、Node.js 20.19+ 和可用的 Docker。

```sh
git clone https://github.com/BorderRegion/Voxlush_Gen.git
cd Voxlush_Gen
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cd frontend
npm ci
npm run build
cd ..
python sandbox/build_image.py
```

## 启动

在仓库根目录生成一份配置，数据目录放在仓库外：

```sh
python - <<'PYCONFIG'
import json
from pathlib import Path

config = json.loads(Path("configs/campaign.example.json").read_text())
config["data_root"] = str(Path.home() / ".local/share/voxlush")
config["frontend_dist"] = str(Path("frontend/dist").resolve())
Path("/tmp/voxlush.json").write_text(json.dumps(config, indent=2) + "\n")
PYCONFIG
voxlush --config /tmp/voxlush.json doctor
voxlush --config /tmp/voxlush.json serve
```

打开 <http://127.0.0.1:8740/>，按 Ctrl-C 停止。新终端先执行 `. .venv/bin/activate`。

在线生成需要配置 `author`、`visual` 端点、请求/费用预算与并发上限，并启用 `allow_live`。API 密钥通过端点的 `api_key_env` 环境变量提供；示例配置不会发送模型请求，模型质量资格尚未验证。

## 常用命令

服务运行时，可在面板控制活动，或在另一个终端执行：

```sh
voxlush --config /tmp/voxlush.json campaign create demo "Demo" 10 --request-limit 1 --api-cap 0
voxlush --config /tmp/voxlush.json campaign start demo
voxlush --config /tmp/voxlush.json campaign pause demo
voxlush --config /tmp/voxlush.json campaign resume demo
voxlush --config /tmp/voxlush.json campaign drain demo
```

此活动仅供离线操作演示，`--api-cap 0` 禁止模型调用。导出或备份前先 drain、等待任务收尾并停止服务：

```sh
voxlush --config /tmp/voxlush.json export --campaign demo --output /path/to/release
voxlush verify-release /path/to/release
voxlush --config /tmp/voxlush.json backup --output /path/to/backup
voxlush restore --source /path/to/backup --destination /path/to/new-data-root
```

恢复目标必须是不存在的新目录。运行数据、密钥、日志和备份不要提交到 Git。
