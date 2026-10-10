from __future__ import annotations

from argparse import ArgumentParser

from terminal_client import ApiClient, ApiError, TerminalApp


def main() -> int:
    parser = ArgumentParser(description="浊流之上文字测试客户端")
    parser.add_argument("--url", default="http://127.0.0.1:8100", help="后端基础地址")
    parser.add_argument(
        "--account-id",
        default="terminal-local",
        help="开发沙盒账号；生产环境不会使用该参数",
    )
    parser.add_argument(
        "--command-mode", action="store_true",
        help="启用开发用原始命令模式；默认使用玩家菜单模式",
    )
    args = parser.parse_args()

    api = ApiClient(args.url, args.account_id)
    try:
        health = api.health()
        api.require_compatible_backend(health)
    except ApiError as exc:
        print(f"无法使用游戏后端 [{exc.code}]：{exc.message}")
        if exc.code == "BACKEND_RESTART_REQUIRED":
            print("请在原后端窗口按 Ctrl+C，再从 code/backend 重新运行：python run_server.py")
        else:
            print("请先在 code/backend 下运行：python run_server.py")
        return 1
    return TerminalApp(api, menu_mode=not args.command_mode).run()


if __name__ == "__main__":
    raise SystemExit(main())
