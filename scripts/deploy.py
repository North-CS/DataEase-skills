import sys
import os
import json
import subprocess

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

# Add local path for engine import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from engine import DataEaseChartEngine

# --- Configuration from Environment ---
def load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_dotenv()

ACCESS_KEY = os.environ.get("DATAEASE_ACCESS_KEY")
SECRET_KEY = os.environ.get("DATAEASE_SECRET_KEY")
BASE_URL   = os.environ.get("DATAEASE_BASE_URL")

# Screenshot configuration - auto-detect OpenClaw workspace for MEDIA: display
def _default_output_dir():
    """优先使用 OpenClaw workspace 目录，否则用 skill 本地 output 目录"""
    # 1. 环境变量显式指定
    env_dir = os.environ.get("DATAEASE_OUTPUT_DIR")
    if env_dir:
        return env_dir
    # 2. 自动检测 OpenClaw workspace
    home = os.path.expanduser("~")
    workspace_dir = os.path.join(home, ".openclaw", "workspace", "dataease-output")
    if os.path.isdir(os.path.join(home, ".openclaw", "workspace")):
        os.makedirs(workspace_dir, exist_ok=True)
        return workspace_dir
    # 3. 回退到 skill 本地 output
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

OUTPUT_DIR = _default_output_dir()
DEFAULT_PIXEL = "1920*1080"

def capture_dashboard(dashboard_id, output_format="jpeg"):
    """调用 capture_dashboard.py 进行截图"""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    capture_script = os.path.join(scripts_dir, "capture_dashboard.py")

    if not os.path.exists(capture_script):
        return None, "Screenshot script not found"

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # capture_dashboard.py 使用相同的 BASE_URL（不含 /de2api 后缀）
    capture_base_url = BASE_URL.rstrip("/")

    # 调用截图脚本
    result_format = "0" if output_format == "jpeg" else "1"  # 0=jpeg, 1=pdf
    cmd = [
        sys.executable, capture_script,
        "capture",
        "--resource-id", str(dashboard_id),
        "--busi-type", "dashboard",
        "--output-dir", OUTPUT_DIR,
        "--result-format", result_format,
        "--base-url", capture_base_url,
        "--pixel", DEFAULT_PIXEL
    ]
    org_id = os.environ.get("DATAEASE_ORG_ID", "").strip()
    if org_id:
        cmd.extend(["--org-id", org_id])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
        )
        if result.returncode == 0:
            output = json.loads(result.stdout)
            if output.get("ok"):
                return output.get("saved_file"), None
            else:
                return None, output.get("error", "Unknown capture error")
        else:
            return None, result.stderr or "Capture failed"
    except subprocess.TimeoutExpired:
        return None, "Capture timeout"
    except Exception as e:
        return None, str(e)

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python deploy.py <type> <title> <dataset_name_or_id> <x_fields> <y_fields> [--no-screenshot]")
        print("Example: python deploy.py line 'Skill Test' '电商用户购买行为' '访问平台' '访问次数'")
        return

    if not all([ACCESS_KEY, SECRET_KEY, BASE_URL]):
        print("Error: Missing required environment variables.")
        print("Please set DATAEASE_ACCESS_KEY, DATAEASE_SECRET_KEY, and DATAEASE_BASE_URL.")
        sys.exit(1)

    if len(sys.argv) < 6:
        print("Usage: python3 deploy.py <type> <title> <dataset_name_or_id> <x_fields> <y_fields> [--no-screenshot]")
        print("Example: python3 deploy.py line 'Skill Test' '电商用户购买行为' '访问平台' '访问次数'")
        sys.exit(1)

    chart_type = sys.argv[1]
    title = sys.argv[2]
    dataset_id = sys.argv[3]
    x_axis = [f.strip() for f in sys.argv[4].split(',') if f.strip()]
    y_axis = [f.strip() for f in sys.argv[5].split(',') if f.strip()]

    # 检查是否禁用截图
    no_screenshot = "--no-screenshot" in sys.argv

    engine = DataEaseChartEngine(BASE_URL, ACCESS_KEY, SECRET_KEY)

    try:
        did, url = engine.deploy(chart_type, title, dataset_id, x_axis, y_axis)
        print(f"\n✅ Successfully deployed!")
        print(f"Dashboard ID: {did}")
        print(f"URL: {url}")

        # 自动截图
        if not no_screenshot:
            print("\n📸 Capturing screenshot...")
            screenshot_path, error = capture_dashboard(did)
            if screenshot_path:
                print(f"Screenshot saved: {screenshot_path}")
                # 输出 JSON 结果供 Agent 解析
                result = {
                    "ok": True,
                    "dashboard_id": str(did),
                    "url": url,
                    "screenshot": screenshot_path,
                    "title": title
                }
                print(f"\n__RESULT_JSON__\n{json.dumps(result, ensure_ascii=False)}\n__END_JSON__")
            else:
                print(f"⚠️ Screenshot failed: {error}")
                result = {
                    "ok": True,
                    "dashboard_id": str(did),
                    "url": url,
                    "screenshot": None,
                    "screenshot_error": error,
                    "title": title
                }
                print(f"\n__RESULT_JSON__\n{json.dumps(result, ensure_ascii=False)}\n__END_JSON__")

    except Exception as e:
        print(f"\n❌ Deployment failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
