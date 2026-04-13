# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "apscheduler>=3.11.2",
#     "aiosqlite>=0.22.1",
#     "fastapi>=0.135.1",
#     "httpx>=0.28.1",
#     "maafw>=5.9.2",
#     "numpy",
#     "pillow",
#     "plyer>=2.1.0",
#     "sqlalchemy>=2.0.48",
#     "uvicorn>=0.42.0",
#     "websockets>=16.0",
#     "pyjson5>=2.0.0",
# ]
# ///
"""
MAARoco MWU Web GUI 一键启动脚本

用法:
    uv run tools/serve.py [--port 55666] [--host 0.0.0.0]

自动完成:
1. 克隆 MWU 源码到 deps/mwu
2. 构建前端 (需要 pnpm + Node.js)
3. 链接本项目资源
4. 启动 FastAPI 服务
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MWU_DIR = ROOT / "deps" / "mwu"


def run(cmd: list[str], **kwargs):
    print(f"  $ {' '.join(cmd)}")
    subprocess.check_call(cmd, **kwargs)


def ensure_mwu():
    """克隆或更新 MWU 源码"""
    if (MWU_DIR / ".git").exists():
        print("==> Updating MWU...")
        run(["git", "pull", "--ff-only"], cwd=MWU_DIR)
    else:
        MWU_DIR.parent.mkdir(parents=True, exist_ok=True)
        print("==> Cloning MWU...")
        run(["git", "clone", "--depth", "1",
             "https://github.com/ravizhan/MWU.git", str(MWU_DIR)])


def ensure_frontend():
    """构建前端到 MWU_DIR/page/"""
    page_dir = MWU_DIR / "page"
    if page_dir.exists() and (page_dir / "index.html").exists():
        print("==> Frontend already built, skipping")
        return

    front_dir = MWU_DIR / "front"
    if not front_dir.exists():
        sys.exit("Error: front/ not found in MWU repo")

    print("==> Building frontend...")

    pnpm = shutil.which("pnpm")
    if not pnpm:
        # 尝试用 npm 装 pnpm
        npm = shutil.which("npm")
        if not npm:
            sys.exit(
                "Error: Node.js not found. Install it first:\n"
                "  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -\n"
                "  sudo apt install -y nodejs\n"
                "  npm install -g pnpm"
            )
        print("  Installing pnpm...")
        run([npm, "install", "-g", "pnpm"])
        pnpm = shutil.which("pnpm")
        if not pnpm:
            sys.exit("Error: pnpm install failed")

    run([pnpm, "install"], cwd=front_dir)
    run([pnpm, "run", "build"], cwd=front_dir)

    if not (page_dir / "index.html").exists():
        sys.exit("Error: Frontend build failed, page/index.html not found")
    print("==> Frontend built successfully")


def setup_resources():
    """在 MWU 目录中链接本项目资源"""
    print("==> Setting up resources...")
    assets = ROOT / "assets"

    links = {
        "resource": assets / "resource",
        "agent": ROOT / "agent",
    }

    for name, src in links.items():
        dest = MWU_DIR / name
        if dest.exists() or dest.is_symlink():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        if not src.exists():
            print(f"  Warning: {src} not found, skipping")
            continue
        try:
            os.symlink(src, dest, target_is_directory=True)
            print(f"  Linked {name} -> {src}")
        except OSError:
            shutil.copytree(src, dest)
            print(f"  Copied {name} -> {dest}")

    # interface.json 需要修改，必须复制
    intf_src = assets / "interface.json"
    intf_dest = MWU_DIR / "interface.json"
    if intf_dest.exists() or intf_dest.is_symlink():
        intf_dest.unlink()
    shutil.copy2(intf_src, intf_dest)
    with open(intf_dest, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["agent"] = {
        "child_exec": sys.executable,
        "child_args": ["-u", "./agent/main.py"],
        "timeout": -1,
    }
    with open(intf_dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print("  Updated interface.json with agent config")

    # MaaAgentBinary
    mab_dest = MWU_DIR / "MaaAgentBinary"
    if not (mab_dest.exists() or mab_dest.is_symlink()):
        try:
            import maa
            maa_pkg = Path(maa.__file__).parent
            for candidate in [maa_pkg / "bin" / "MaaAgentBinary",
                              maa_pkg.parent / "MaaAgentBinary"]:
                if candidate.exists():
                    try:
                        os.symlink(candidate, mab_dest, target_is_directory=True)
                    except OSError:
                        shutil.copytree(candidate, mab_dest)
                    print(f"  Linked MaaAgentBinary")
                    break
        except Exception:
            print("  Warning: MaaAgentBinary not found")


def start_server(host: str, port: int):
    print(f"\n==> Starting MWU on http://{host}:{port}\n")
    os.chdir(MWU_DIR)
    sys.path.insert(0, str(MWU_DIR))
    import uvicorn
    uvicorn.run("main:app", host=host, port=port)


def main():
    parser = argparse.ArgumentParser(description="MAARoco MWU Web GUI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=55666)
    args = parser.parse_args()

    ensure_mwu()
    ensure_frontend()
    setup_resources()
    start_server(args.host, args.port)


if __name__ == "__main__":
    main()
