#!/usr/bin/env python3
"""
Server status reporting and chart link listing utilities.

Provides:
- Scanning of outputs/html/ directory for accessible charts
- Human-readable status reports with chart URLs and metadata
- CLI interface for status queries
"""

from pathlib import Path
from datetime import datetime
import json
import argparse
import sys
from typing import List, Dict, Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = PROJECT_ROOT / "outputs" / ".server_status.json"


def get_chart_links(html_dir: str = "outputs/html", port: int | None = None) -> List[Dict[str, Any]]:
    """
    Scan html_dir for all .html files and generate accessible chart links.
    
    Args:
        html_dir: Directory containing HTML chart files (default: outputs/html)
        port: Server port number. If None, read from outputs/.server_status.json
    
    Returns:
        List of dictionaries with chart metadata, sorted by modification time (newest first)
        
    Each dict contains:
        - filename: Chart file name
        - url: Full localhost URL
        - path: Absolute file path
        - size_bytes: File size in bytes
        - created: Creation timestamp (ISO format)
        - modified: Modification timestamp (ISO format)
    """
    # Determine port
    if port is None:
        if STATUS_FILE.exists():
            try:
                status_data = json.loads(STATUS_FILE.read_text())
                port = status_data.get("port", 8100)
            except (json.JSONDecodeError, OSError):
                port = 8100
        else:
            port = 8100
    
    # Scan HTML directory
    html_path = Path(html_dir)
    if not html_path.is_absolute():
        html_path = PROJECT_ROOT / html_path
    if not html_path.exists():
        return []
    
    charts = []
    
    try:
        for file in html_path.glob("*.html"):
            try:
                stat = file.stat()
                # Build URL relative to project root so the path matches the
                # server's document root.  e.g. outputs/html/bar_chart.html
                rel_path = str(file.relative_to(PROJECT_ROOT)).replace('\\', '/')
                charts.append({
                    "filename": file.name,
                    "url": f"http://127.0.0.1:{port}/{rel_path}",
                    "path": str(file.resolve()),
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except (OSError, PermissionError):
                # Skip files we can't read
                continue
    except PermissionError:
        # Can't access directory
        return []
    
    # Sort by modification time (newest first)
    charts.sort(key=lambda x: x["modified"], reverse=True)
    
    return charts


def format_status_report(status_dict: Dict[str, Any], chart_links: List[Dict[str, Any]] | None = None) -> str:
    """
    Format server status for human-readable output.
    
    Args:
        status_dict: Status dictionary from server_cli.get_status()
        chart_links: Optional list of chart links from get_chart_links()
    
    Returns:
        Formatted multi-line status report string
    """
    lines = []
    
    # Server status section
    status_text = status_dict.get("status", "未知")
    if status_dict.get("running", False):
        status_text = "运行中"
    else:
        status_text = "已停止"
    
    lines.append(f"服务状态: {status_text}")
    
    if "port" in status_dict:
        lines.append(f"端口: {status_dict['port']}")
    
    if "start_time" in status_dict:
        start_time = status_dict["start_time"]
        if isinstance(start_time, str):
            # Parse ISO format
            try:
                start_dt = datetime.fromisoformat(start_time)
                lines.append(f"启动时间: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            except ValueError:
                lines.append(f"启动时间: {start_time}")
        
        # Calculate runtime if we have start time
        if status_dict.get("running", False):
            try:
                if isinstance(start_time, str):
                    start_dt = datetime.fromisoformat(start_time)
                else:
                    start_dt = start_time
                
                elapsed = datetime.now() - start_dt
                hours = elapsed.seconds // 3600
                minutes = (elapsed.seconds % 3600) // 60
                seconds = elapsed.seconds % 60
                lines.append(f"运行时长: {hours:02d}:{minutes:02d}:{seconds:02d}")
            except (ValueError, TypeError):
                pass
    
    # Chart links section
    if chart_links and len(chart_links) > 0:
        lines.append("")  # Empty line separator
        lines.append(f"可访问图表 ({len(chart_links)}):")
        
        for i, chart in enumerate(chart_links, 1):
            size_kb = chart["size_bytes"] / 1024
            if size_kb >= 1024:
                size_str = f"{size_kb / 1024:.2f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"
            
            # Parse and format modification time
            try:
                mod_dt = datetime.fromisoformat(chart["modified"])
                mod_str = mod_dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                mod_str = chart["modified"]
            
            lines.append(f"{i}. {chart['filename']}")
            lines.append(f"   URL: {chart['url']}")
            lines.append(f"   大小: {size_str}")
            lines.append(f"   修改时间: {mod_str}")
            lines.append("")  # Empty line between charts
    
    return "\n".join(lines)


def main():
    """CLI interface for server status queries."""
    parser = argparse.ArgumentParser(
        description="Server status reporting and chart link listing"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Links subcommand
    links_parser = subparsers.add_parser("links", help="List accessible chart links")
    links_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port (reads from .server_status.json if not specified)"
    )
    links_parser.add_argument(
        "--html-dir",
        type=str,
        default="outputs/html",
        help="Directory containing HTML chart files"
    )
    links_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format instead of text"
    )
    
    # Report subcommand
    report_parser = subparsers.add_parser("report", help="Generate full status report")
    report_parser.add_argument(
        "--html-dir",
        type=str,
        default="outputs/html",
        help="Directory containing HTML chart files"
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "links":
        charts = get_chart_links(html_dir=args.html_dir, port=args.port)
        
        if args.json:
            print(json.dumps(charts, indent=2, ensure_ascii=False))
        else:
            if len(charts) == 0:
                print("未找到图表文件")
            else:
                print(f"找到 {len(charts)} 个图表:")
                for i, chart in enumerate(charts, 1):
                    print(f"{i}. {chart['filename']}")
                    print(f"   URL: {chart['url']}")
    
    elif args.command == "report":
        # Try to read server status
        status_dict = {}
        
        if STATUS_FILE.exists():
            try:
                status_dict = json.loads(STATUS_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                status_dict = {"status": "未知", "running": False}
        else:
            status_dict = {"status": "未启动", "running": False}
        
        # Get chart links
        charts = get_chart_links(html_dir=args.html_dir, port=status_dict.get("port"))
        
        # Format and print report
        report = format_status_report(status_dict, charts)
        print(report)


if __name__ == "__main__":
    main()
