import os
import subprocess
import shutil
from pathlib import Path

# ==================== 配置 ====================
APP_NAME = "GameTranslator"
MAIN_SCRIPT = "main.py"
CUR_DIR = Path(__file__).parent
VENV_PYTHON = CUR_DIR / ".venv" / "Scripts" / "python.exe"
DIST_DIR = CUR_DIR / "dist"
BUILD_DIR = CUR_DIR / "build"
MODELS_SRC = CUR_DIR / "ocr_models"

def run_command(cmd):
    print(f">> 运行命令: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"❌ 命令失败，退出码: {result.returncode}")
        exit(1)

def build():
    # 1. 清理旧目录
    if DIST_DIR.exists(): shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists(): shutil.rmtree(BUILD_DIR)

    # 2. 检查环境
    if not VENV_PYTHON.exists():
        print("❌ 找不到虚拟环境中的 python.exe")
        return

    # 3. 运行 PyInstaller
    # 增加 --collect-all 以确保所有 C++ 库被包含
    pyinstaller_cmd = (
        f'"{VENV_PYTHON}" -m PyInstaller --noconsole --name {APP_NAME} '
        f'--add-data "terminology.json;." '
        f'--add-data "translation_cache.json;." '
        f'--add-data "app_settings.json;." '
        f'--hidden-import=paddlex.inference.pipelines.ocr.pipeline '
        f'--collect-all paddleocr '
        f'--collect-all paddlex '
        f'--collect-all pyclipper '
        f'--collect-all shapely '
        f'--collect-all imgaug '
        f'--collect-all skimage '
        f'"{MAIN_SCRIPT}"'
    )
    
    run_command(pyinstaller_cmd)

    # 4. 拷贝模型文件夹
    target_dist_app = DIST_DIR / APP_NAME
    dest_models = target_dist_app / "ocr_models" if target_dist_app.is_dir() else DIST_DIR / "ocr_models"
    
    if MODELS_SRC.exists():
        print(f">> 正在同步本地模型库...")
        if dest_models.exists(): shutil.rmtree(dest_models)
        shutil.copytree(MODELS_SRC, dest_models)

    print("\n✅ 打包结束！请尝试运行。")

if __name__ == "__main__":
    build()
