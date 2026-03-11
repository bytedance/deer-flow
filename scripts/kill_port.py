# scripts/kill_port.py
import subprocess
import sys
 
def kill_process_on_port(port):
    """Kill process using the specified port on Windows."""
    try:
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            shell=True
        )
        
        pids = set()
        for line in result.stdout.split('\n'):
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if len(parts) >= 5:
                    pids.add(parts[-1])
        
        for pid in pids:
            subprocess.run(
                ['taskkill', '/PID', pid, '/F'],
                capture_output=True,
                shell=True
            )
            
    except Exception:
        pass
 
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    kill_process_on_port(port)