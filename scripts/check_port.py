# scripts/check_port.py
import socket
import sys
import time
 
def is_port_ready(port, max_retries=15, retry_interval=1):
    """Check if a service is ready with retries."""
    for attempt in range(max_retries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.connect(("127.0.0.1", port))
                return True  # Connected successfully
            except (ConnectionRefusedError, socket.timeout, OSError):
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
                continue
    return False
 
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python check_port.py <port>")
        sys.exit(1)
    
    port = int(sys.argv[1])
    
    if is_port_ready(port):
        sys.exit(0)
    else:
        sys.exit(1)