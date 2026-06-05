"""
DeerFlow Production Engine CLI

Command-line interface for the DeerFlow Production Engine.
Provides interactive chat and session management.

Author: heart-scalpel
License: MIT
"""

import sys
from engine import DeerFlowProductionEngine


def safe_input(prompt):
    """
    Safely read input with UTF-8 encoding.

    Args:
        prompt: The input prompt to display.

    Returns:
        str: The input line, stripped of trailing newline.
    """
    try:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    while True:
        try:
            return input(prompt).rstrip('\n')
        except UnicodeDecodeError:
            print("\n[Error] Input encoding error. Please use UTF-8. | 输入编码错误，请使用UTF-8\n")
        except EOFError:
            return ""


def multi_line_input(prompt):
    """
    Read multi-line input from the user.

    Args:
        prompt: The prompt to display before entering multi-line mode.

    Returns:
        str: The combined multi-line input.
    """
    print(prompt)
    print("Enter !end to finish multi-line input | 输入 !end 结束多行输入\n")
    lines = []
    while True:
        try:
            line = input()
            if line.strip().lower() == '!end':
                break
            lines.append(line)
        except UnicodeDecodeError:
            print("\n[Error] Input encoding error. Please use UTF-8. | 输入编码错误，请使用UTF-8\n")
        except EOFError:
            break
    return '\n'.join(lines)


def main():
    """Main entry point for the DeerFlow Production Engine CLI."""
    engine = DeerFlowProductionEngine()

    print("=" * 70)
    print("DeerFlow Production Engine - Local Test Mode")
    print("DeerFlow 生产引擎 - 本地测试模式")
    print("=" * 70)
    print("Type !help to see all available commands | 输入 !help 查看所有可用命令")
    print("Type !multi to enter multi-line input mode | 输入 !multi 进入多行输入模式")
    print("=" * 70)
    print()

    while True:
        try:
            if engine.current_session_id is None:
                engine.create_session()

            prompt = f"[{engine.current_session_id[:8]}] You: "
            user_input = safe_input(prompt).strip()

            if not user_input:
                continue

            if user_input.lower() == '!multi':
                user_input = multi_line_input(f"\n[{engine.current_session_id[:8]}] Multi-line Input Mode | 多行输入模式")
                if not user_input.strip():
                    print("\n[Info] Empty input ignored | 空输入已忽略\n")
                    continue
                print()

            if user_input.lower() == "!exit":
                break

            if user_input.lower() == "!help":
                print("\n[Available Commands | 可用命令]")
                print("  Session Management | 会话管理:")
                print("    !new [id] [title]  Create new session | 创建新会话")
                print("    !switch <id>       Switch to session | 切换会话")
                print("    !delete session <id> Delete session | 删除会话")
                print("    !rename <title>    Rename current session | 重命名当前会话")
                print("    !archive <id>      Archive session | 归档会话")
                print("    !archives          List archived sessions | 查看归档会话")
                print("    !restore <id>      Restore session from archive | 从归档恢复会话")
                print("    !sessions          List all sessions | 列出所有会话")
                print("    !export            Export current session to Markdown | 导出当前会话为Markdown")
                print("    !export_all        Export all checkpoints to Markdown | 导出全部检查点为Markdown")
                print("    !search <keyword>  Search all sessions | 搜索所有会话")
                print("  Debugging | 诊断流程:")
                print("    !steps             Show current session steps | 查看当前会话步骤")
                print("    !steps_all         Show all checkpoints (de‑duplicated) | 查看全部检查点（去重）")
                print("  Input | 输入:")
                print("    !multi             Enter multi-line input mode | 进入多行输入模式")
                print("  System | 系统:")
                print("    !help              Show this help message | 显示帮助信息")
                print("    !exit              Exit the system | 退出系统")
                print()
                continue

            if user_input.lower().startswith("!new"):
                parts = user_input.split(maxsplit=2)
                sid = parts[1] if len(parts) > 1 else None
                title = parts[2] if len(parts) > 2 else None
                engine.create_session(sid, title)
                continue

            if user_input.lower().startswith("!switch"):
                parts = user_input.split()
                if len(parts) < 2:
                    print("[Error] Usage: !switch <session_id> | 用法: !switch <会话ID>")
                    continue
                engine.switch_session(parts[1])
                continue

            if user_input.lower().startswith("!delete session"):
                parts = user_input.split()
                if len(parts) < 3:
                    print("[Error] Usage: !delete session <session_id> | 用法: !delete session <会话ID>")
                    continue
                engine.delete_session(parts[2])
                continue

            if user_input.lower().startswith("!rename"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("[Error] Usage: !rename <new_title> | 用法: !rename <新标题>")
                    continue
                engine.rename_session(engine.current_session_id, parts[1])
                continue

            if user_input.lower() == "!sessions":
                engine.list_sessions()
                continue

            if user_input.lower() == "!archives":
                engine.list_archives()
                continue

            if user_input.lower().startswith("!archive"):
                parts = user_input.split()
                if len(parts) < 2:
                    print("[Error] Usage: !archive <session_id> | 用法: !archive <会话ID>")
                    continue
                engine.archive_session(parts[1])
                continue

            if user_input.lower().startswith("!restore"):
                parts = user_input.split()
                if len(parts) < 2:
                    print("[Error] Usage: !restore <session_id> | 用法: !restore <会话ID>")
                    continue
                engine.restore_archive(parts[1])
                continue

            if user_input.lower() == "!export":
                engine.export_session_markdown()
                continue

            if user_input.lower() == "!export_all":
                engine.export_all_checkpoints()
                continue

            if user_input.lower().startswith("!search"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print("[Error] Usage: !search <keyword> | 用法: !search <关键词>")
                    continue
                engine.search_sessions(parts[1])
                continue

            if user_input.lower() == "!steps":
                steps = engine.get_session_steps()
                print("\n[Step List | 步骤列表]")
                for step in steps:
                    preview = step["user_input"][:60] + "..." if len(step["user_input"]) > 60 else step["user_input"]
                    print(f"  {step['step']}. {preview}")
                print()
                continue

            if user_input.lower() == "!steps_all":
                cps = engine.get_all_checkpoint_steps()
                print(f"\n[All Checkpoints | 全部检查点] Total: {len(cps)}\n")
                if not cps:
                    print("  No checkpoints found. | 未找到检查点。\n")
                    continue
                for idx, cp in enumerate(cps, 1):
                    ts_display = str(cp["ts"]) if cp["ts"] is not None else "N/A"
                    new_flag = "✓ New content | 有新内容" if cp["has_new_content"] else "✗ No new content | 无新增"
                    print(f"  [{idx}] {cp['checkpoint_id'][:8]}... | ts:{ts_display} | {new_flag}")
                print()
                continue

            # Normal chat interaction
            print("AI: ", end="", flush=True)
            for chunk in engine.chat(user_input):
                print(chunk, end="", flush=True)
            print("\n")

        except KeyboardInterrupt:
            engine.shutdown()
            break
        except Exception as e:
            print(f"\n\n[Error | 错误] {str(e)}")
            print()


if __name__ == "__main__":
    main()
