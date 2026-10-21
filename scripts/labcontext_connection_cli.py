"""CLI management for connection profiles; adding a profile never activates it."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError

from labcontext_connections import ConnectionError, ConnectionStore, safe_name


HANDOFF_PROMPT = """请仅通过 LabContext 继续我的项目：先调用 list_workspaces，展示可用来源并让我选择项目；
再读取该项目的 workspace_overview 和 research_context（如有），整理研究目标、已确认结论、
最新进展、证据位置、未解决问题和下一步。区分事实、推断与待确认项，不执行代码、不修改文件、
不自动启动付费分析。不要假定你拥有旧 ChatGPT 账号的聊天记录或记忆。"""


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("connections", help="prepare, verify and reconnect ChatGPT access without restarting projects")
    commands = parser.add_subparsers(dest="connection_command", required=True)
    commands.add_parser("list", help="show profiles without secrets")
    commands.add_parser("snapshot", help="save current profile references; does not copy credentials")
    commands.add_parser("export", help="print a secret-free recovery checklist and project handoff prompt")
    add = commands.add_parser("add", help="register an existing Tunnel profile without activating it")
    add.add_argument("id")
    add.add_argument("--label", default="备用接入")
    add.add_argument("--profile", required=True)
    add.add_argument("--secret-file", required=True)
    add.add_argument("--health-url", default="http://127.0.0.1:8080")
    for name in ("check", "use"):
        command = commands.add_parser(name)
        command.add_argument("id")
    commands.add_parser("reconnect", help="reconnect only the currently managed Tunnel")


def connections_command(args: argparse.Namespace, values: dict[str, str], router_url: str) -> int:
    store = ConnectionStore(values)
    command = args.connection_command
    if command == "snapshot":
        print(json.dumps(store.snapshot(), ensure_ascii=False, indent=2))
        print("已保存接入配置引用，未复制密钥、未切换账号或重启进程。")
        return 0
    if command == "add":
        store.add({"id": args.id, "label": args.label, "profile": args.profile, "healthUrl": args.health_url,
                   "credentialMode": "file", "secretFile": args.secret_file})
        print(f"已登记 {safe_name(args.id)}，当前接入未改变。之后运行 labcontext connections check {args.id}。")
        return 0
    if command in {"list", "export"}:
        public = store.public()
        if command == "export":
            public.pop("operation", None)
            public.update({"containsCredentials": False, "projectHandoffPrompt": HANDOFF_PROMPT,
                           "recoverySteps": ["保留 Provider、工作区和 SSH；此清单不含凭据，不能单独恢复登录。",
                                             "在本机准备新 Tunnel profile 和权限为 0600 的专用凭据文件。",
                                             "登记配置，执行 connections check，再显式执行 connections use。",
                                             "在新 ChatGPT 账号安装插件，实际调用 list_workspaces，再用非敏感示例调用 inspect_path 核对结果。"]})
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return 0
    if command == "check":
        profile = store.get(args.id)
        import os
        environment = store.environment(profile, {**os.environ, **values})
        try:
            result = subprocess.run([values.get("LABCONTEXT_TUNNEL_CLIENT", "tunnel-client"), "doctor", "--profile", profile["profile"], "--explain"],
                                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=12, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConnectionError("Tunnel 诊断无法完成；请检查本机程序和网络，当前接入未改变。") from exc
        if result.returncode:
            raise ConnectionError("Tunnel 诊断未通过；请检查 profile、凭据和工作区权限，当前接入未改变。")
        print("Tunnel 本机诊断通过；尚未证明目标 ChatGPT 账号具有插件访问权限。当前接入未改变。")
        return 0
    target = args.id if command == "use" else store.catalog()["activeId"]
    request = Request(router_url + "/api/connections/action",
                      data=json.dumps({"action": "switch" if command == "use" else "reconnect", "connectionId": target}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            job = json.loads(response.read(16_384))
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            with opener.open(router_url + "/api/connections", timeout=3) as response:
                status = json.loads(response.read(128 * 1024))["operation"]
            if status.get("jobId") != job.get("jobId"):
                raise ConnectionError("操作记录已变化，请运行 labcontext connections list 查看结果；不重复提交。")
            if status.get("phase") in {"succeeded", "failed"}:
                print(status["summary"])
                if status.get("reasonCode"):
                    print("原因代码：" + status["reasonCode"])
                return 0 if status["phase"] == "succeeded" else 2
            time.sleep(0.5)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read(16_384)).get("error", "本机 Router 拒绝了接入操作。")
        except (ValueError, OSError):
            detail = "本机 Router 拒绝了接入操作，请更新本机组件并运行 labcontext connections list。"
        raise ConnectionError(str(detail)) from exc
    except ConnectionError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise ConnectionError("本机接入操作无法确认，请运行 labcontext connections list 或启动 labcontext；不要重复提交。") from exc
    raise ConnectionError("等待 Tunnel 操作超时，请运行 labcontext connections list 查看结果；不会重建 Provider 或 SSH。")
