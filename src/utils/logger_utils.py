import logging
from datetime import datetime
from pathlib import Path

def configure_logging(log_root='logs'):
    log_root = Path(log_root)
    log_root.mkdir(exist_ok=True, parents=True)
    log_filename = datetime.now().strftime(f"log_%Y-%m-%d_%H-%M.log")
    log_filename = log_root / log_filename
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),  # 将日志写入文件
            logging.StreamHandler()  # 同时输出到终端
        ]
    )

def enable_debug_logging():
    """Enable debug level logging for more detailed execution information."""
    logging.getLogger("src").setLevel(logging.DEBUG)