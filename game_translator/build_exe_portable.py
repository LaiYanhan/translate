import os
import subprocess
import sys
from pathlib import Path

# 强制终端使用 UTF-8，防止打包时日志包含特殊字符报错
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def build():
    # 1. 确定路径
    base_dir = Path(__file__).parent.absolute()
    venv_python = base_dir / ".venv" / "Scripts" / "python.exe"
    pyinstaller_exe = base_dir / ".venv" / "Scripts" / "pyinstaller.exe"
    
    if not venv_python.exists():
        print("[!] 错误: 未找到 .venv 虚拟环境，请先确保当前目录下存在 .venv 文件夹。")
        return

    # 2. 确保安装了 PyInstaller
    print("[*] 正在检查并安装 PyInstaller...")
    subprocess.run([str(venv_python), "-m", "pip", "install", "pyinstaller"], check=True)

    # 3. 准备打包命令
    # --- 数据文件包含策略 ---
    # 我们要把术语、缓存、预设文件夹、以及本地模型文件夹(models)都包含进去
    add_data_list = [
        ("terminology.json", "."),
        ("translation_cache.json", "."),
        ("app_settings.json", "."),
        ("presets", "presets"),
        ("models", "models"),
    ]
    
    cmd = [
        str(pyinstaller_exe),
        "--name", "GameTranslator_Portable",
        "--noconsole",
        "--onedir",
        "--clean",
        "--noconfirm",
        "--noupx",
        # 核心：收集所有 Paddle 相关库的数据和插件，确保 Pipeline 注册成功
        "--collect-all", "paddleocr",
        "--collect-all", "paddlex",
        "--collect-all", "paddle",
        # 兼容性：某些环境下需要版本元数据
        "--copy-metadata", "paddleocr",
        "--copy-metadata", "paddlex",
        "main.py"
    ]

    # 动态把刚才定义的那些文件/文件夹加进去
    for src, dst in add_data_list:
        if (base_dir / src).exists():
            # Windows 下 PyInstaller 的分隔符是分号 ;
            cmd.extend(["--add-data", f"{src};{dst}"])

    # 4. 执行打包
    print("\n[+] 正在开始打包 (这可能需要几分钟，请不要关闭)...")
    try:
        subprocess.run(cmd, check=True)
        print("\n[*] 打包成功！")
        print(f"[*] 你的绿色版工具包在: {base_dir / 'dist' / 'GameTranslator_Portable'}")
        print("[*] 你可以直接把该文件夹拷贝到任意电脑使用。")
    except subprocess.CalledProcessError as e:
        print(f"\n[!] 打包失败: {e}")

if __name__ == "__main__":
    build()
