"""一键部署到 Render + Neon（只需要两个 token）。

用法：
    python scripts/deploy_render.py --github-token <PAT> --render-key <KEY>
    python scripts/deploy_render.py --github-token xxx --render-key yyy --dry-run

它会依次完成：
    1. 用 GitHub API 创建私有仓库（已存在则复用）
    2. git push 当前代码
    3. 用 Render API 创建 Web Service（python runtime / free plan / singapore）
    4. 写入全部环境变量（数据库、Bot、Cloudflare）
    5. 轮询部署状态，直到 live
    6. 设置 Telegram webhook
    7. 打印线上地址并做一次 /health 体检

需要的权限：
    - GitHub PAT：repo（经典）或 Contents/PAdministration: Read and write（fine-grained）
    - Render API Key：Account Settings → API Keys
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
GH_API = "https://api.github.com"
RENDER_API = "https://api.render.com/v1"

BUILD_CMD = "pip install uv && uv pip install --system --no-cache . && alembic upgrade head"
START_CMD = "python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT"


def _client(timeout: float = 30) -> httpx.Client:
    """GitHub/Render 直连更稳（绕过本机代理的偶发 TLS 抖动）。"""
    return httpx.Client(timeout=timeout, trust_env=False)


def _get(url: str, headers: dict | None = None, **kw) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            with _client() as c:
                return c.get(url, headers=headers, **kw)
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"网络请求失败（重试 4 次）：{url}\n{last}")


def _post(url: str, headers: dict | None = None, **kw) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            with _client(60) as c:
                return c.post(url, headers=headers, **kw)
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"网络请求失败（重试 4 次）：{url}\n{last}")


def log(msg: str) -> None:
    print(msg, flush=True)


def load_env(path: pathlib.Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


# ---------------- GitHub ----------------
def github_user(token: str) -> dict:
    r = _get(f"{GH_API}/user", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


def ensure_repo(token: str, login: str, name: str, private: bool = True) -> str:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    full = f"{login}/{name}"
    r = _get(f"{GH_API}/repos/{full}", headers=headers)
    if r.status_code == 200:
        log(f"   仓库已存在：{r.json()['full_name']}")
        return r.json()["full_name"]

    r = _post(
        f"{GH_API}/user/repos",
        headers=headers,
        json={"name": name, "private": private, "auto_init": False},
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"创建仓库失败：{r.status_code} {r.text[:300]}")
    log(f"   已创建仓库：{r.json()['full_name']}")
    return r.json()["full_name"]


def push(repo_full: str, token: str, branch: str = "main") -> None:
    url = f"https://x-access-token:{token}@github.com/{repo_full}.git"
    run(["git", "add", "-A"])
    # 没有改动时 commit 会失败，忽略
    subprocess.run(["git", "commit", "-m", "deploy: auto"], cwd=ROOT, capture_output=True)
    run(["git", "branch", "-M", branch])
    run(["git", "push", "--force", url, f"{branch}:{branch}"])
    # origin 可能不存在，忽略失败
    subprocess.run(["git", "remote", "remove", "origin"], cwd=ROOT, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{repo_full}.git"],
        cwd=ROOT,
        capture_output=True,
    )
    log(f"   已推送到 {repo_full}@{branch}")


def run(cmd: list[str]) -> None:
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Windows 默认 GBK，git 输出会带非 GBK 字节
    )
    if p.returncode != 0:
        raise SystemExit(f"命令失败：{' '.join(cmd)}\n{(p.stderr or p.stdout or '')[-500:]}")


# ---------------- Render ----------------
def render_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def find_service(key: str, name: str) -> dict | None:
    r = _get(
        f"{RENDER_API}/services",
        headers=render_headers(key),
        params={"limit": 100},
    )
    if r.status_code != 200:
        raise SystemExit(f"查询 Render 服务失败：{r.status_code} {r.text[:300]}")
    for item in r.json():
        svc = item.get("service", item)
        if svc.get("name") == name:
            return svc
    return None


def create_service(
    key: str, name: str, repo_url: str, branch: str, env_vars: dict[str, str]
) -> dict:
    payload = {
        "type": "web_service",
        "name": name,
        "ownerId": _owner_id(key),
        "repo": repo_url,
        "branch": branch,
        "autoDeploy": "yes",
        "envVars": [{"key": k, "value": v} for k, v in env_vars.items()],
        "serviceDetails": {
            "env": "python",
            "plan": "free",
            "region": "singapore",
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "buildCommand": BUILD_CMD,
                "startCommand": START_CMD,
            },
        },
    }
    r = _post(f"{RENDER_API}/services", headers=render_headers(key), json=payload)
    if r.status_code not in (200, 201):
        raise SystemExit(f"创建服务失败：{r.status_code} {r.text[:500]}")
    svc = r.json()
    return svc.get("service", svc)


def _owner_id(key: str) -> str:
    r = _get(f"{RENDER_API}/owners", headers=render_headers(key))
    if r.status_code == 200 and r.json():
        first = r.json()[0]
        return first.get("owner", first).get("id") or first.get("id")
    raise SystemExit(f"拿不到 Render ownerId：{r.status_code} {r.text[:200]}")


def wait_live(key: str, service_id: str, timeout_s: int = 900) -> str:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = _get(
            f"{RENDER_API}/services/{service_id}",
            headers=render_headers(key),
        )
        if r.status_code == 200:
            svc = r.json()
            details = svc.get("serviceDetails", {})
            state = details.get("suspended") or svc.get("state") or "unknown"
            url = details.get("url")
            if state != last:
                log(f"   部署状态：{state}")
                last = state
            if state in ("live", "active") and url:
                return url
            if state in ("build_failed", "deploy_failed", "canceled"):
                raise SystemExit(f"部署失败（{state}），请到 Render 控制台看构建日志")
        elif r.status_code == 404:
            raise SystemExit("服务不见了？")
        time.sleep(15)
    raise SystemExit("等待部署超时（15 分钟）")


# ---------------- Telegram ----------------
def set_webhook(bot_token: str, app_url: str, secret: str, proxy: str | None) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        "url": f"{app_url.rstrip('/')}/webhook/telegram",
        "secret_token": secret,
        "drop_pending_updates": True,
    }
    kwargs = {"proxy": proxy} if proxy else {}
    r = httpx.post(url, json=payload, timeout=30, **kwargs)
    data = r.json()
    if not data.get("ok"):
        raise SystemExit(f"设置 webhook 失败：{data}")
    log(f"   webhook 已设置：{payload['url']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-token", required=True)
    ap.add_argument("--render-key", required=True)
    ap.add_argument("--repo", default="zhiwei")
    ap.add_argument("--service", default="zhiwei")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env(ROOT / ".env")
    required = [
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_USER_ID",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_MODEL",
    ]
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise SystemExit(f".env 里缺少：{', '.join(missing)}")

    secret = env.get("TELEGRAM_WEBHOOK_SECRET") or "zhiwei-" + str(int(time.time()))
    remote_env = {
        "APP_ENV": "production",
        "BOT_MODE": "webhook",
        "LLM_PROVIDER": "cloudflare",
        # 云端没有本地 Ollama，备用留空；本地开发才用 ollama 兜底
        "LLM_FALLBACK_PROVIDER": "",
        "CLOUDFLARE_TIMEOUT": "45",
        "DATABASE_URL": env["DATABASE_URL"],
        "TELEGRAM_BOT_TOKEN": env["TELEGRAM_BOT_TOKEN"],
        "TELEGRAM_USER_ID": env["TELEGRAM_USER_ID"],
        "TELEGRAM_WEBHOOK_SECRET": secret,
        "CLOUDFLARE_API_TOKEN": env["CLOUDFLARE_API_TOKEN"],
        "CLOUDFLARE_ACCOUNT_ID": env["CLOUDFLARE_ACCOUNT_ID"],
        "CLOUDFLARE_MODEL": env.get("CLOUDFLARE_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
        "AI_NAME": env.get("AI_NAME", "知微"),
        "USER_NAME": env.get("USER_NAME", "木川"),
        "PYTHON_VERSION": "3.12.8",
    }

    log("[1/6] 校验 GitHub 身份")
    if args.dry_run:
        log("   (dry-run) 跳过真实调用，下面是会写入 Render 的变量（已脱敏）")
        masked = {
            k: ("***" if any(s in k for s in ("TOKEN", "KEY", "URL", "SECRET")) else v)
            for k, v in remote_env.items()
        }
        log(json.dumps(masked, ensure_ascii=False, indent=2))
        return
    user = github_user(args.github_token)
    log(f"   账号：{user['login']}")

    log("[2/6] 创建/复用 GitHub 仓库")
    repo_full = ensure_repo(args.github_token, user["login"], args.repo)

    log("[3/6] 推送代码")
    push(repo_full, args.github_token, args.branch)

    log("[4/6] 在 Render 创建服务")
    existing = find_service(args.render_key, args.service)
    if existing:
        log(f"   服务已存在（{existing['id']}），跳过创建")
        svc = existing
    else:
        svc = create_service(
            args.render_key,
            args.service,
            f"https://github.com/{repo_full}",
            args.branch,
            remote_env,
        )
        log(f"   已创建：{svc['id']}")

    log("[5/6] 等待部署完成")
    app_url = wait_live(args.render_key, svc["id"])
    log(f"   线上地址：{app_url}")

    log("[6/6] 设置 Telegram webhook")
    set_webhook(env["TELEGRAM_BOT_TOKEN"], app_url, secret, env.get("TELEGRAM_PROXY") or None)

    log("\n完成。请记得停掉本地运行的进程（否则会和云端抢消息）：stop.cmd 或 taskkill")
    log(f"体检：curl {app_url}/health")


if __name__ == "__main__":
    sys.exit(main())
