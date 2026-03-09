# 🎮 Game Translator - 游戏实时翻译工具

一款基于 PaddleOCR + LLM 的 Windows 游戏实时翻译工具，支持热键截图、OCR 识别、AI 翻译、透明字幕覆盖显示。

---

## 📁 项目结构

```
game_translator/
├── main.py                 # 主入口 + 主控制窗口
├── config.py               # 全局配置
├── screen_capture.py       # 截图模块（全屏/窗口/框选）
├── ocr_engine.py           # PaddleOCR 引擎封装（GPU/CPU 自动切换）
├── ocr_postprocess.py      # OCR 文本合并算法
├── subtitle_detector.py    # 字幕区域自动检测
├── translator.py           # LLM 翻译接口
├── prompt_builder.py       # Prompt 构建（含术语注入）
├── translation_cache.py    # 翻译缓存（字典 + JSON 持久化）
├── terminology_manager.py  # 术语管理（数据 + UI）
├── overlay_renderer.py     # 透明字幕覆盖层渲染
├── hotkey_listener.py      # 全局热键监听
├── terminology.json        # 术语表
├── translation_cache.json  # 翻译缓存
├── requirements.txt        # Python 依赖
└── README.md
```

---

## ⚙️ 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| Python | 3.13.x |
| GPU（可选）| NVIDIA CUDA 支持，自动回退 CPU |

---

## 🚀 安装步骤

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

> **注意**：`paddlepaddle-gpu` 需要 NVIDIA 驱动和 CUDA。  
> 若无 GPU，可改用 `paddlepaddle`（CPU 版）：
> ```bash
> pip install paddlepaddle
> ```

### 2. 配置 LLM API

在系统环境变量中设置（PowerShell）：

```powershell
$env:LLM_API_KEY  = "sk-xxxxxxxxxxxxxxxx"
$env:LLM_API_URL  = "https://api.openai.com/v1/chat/completions"
$env:LLM_MODEL    = "gpt-4o-mini"
```

或在 `config.py` 中直接修改默认值。

> ✅ 支持所有 OpenAI 兼容 API（DeepSeek、Qwen、本地 Ollama 等）。

---

## 🖥️ 使用方法

### 启动程序

```bash
cd game_translator
python main.py
```

### 主窗口功能

| 按钮 | 功能 |
|------|------|
| 🖥 全屏 | 截取整个屏幕 |
| 🪟 指定窗口 | 选择游戏程序窗口 |
| ✂ 框选区域 | 拖动鼠标框选翻译区域 |
| ▶ 启动监听 | 注册热键，开始监听 |
| ⚡ 立即翻译 | 不用热键，直接触发一次翻译 |
| 📖 术语管理 | 打开术语编辑窗口 |
| ⌨ 修改热键 | 自定义快捷键 |

### 默认热键

`Ctrl + Shift + T`

### 翻译流程

```
按下热键 → 截图 → OCR识别 → 字幕区域检测 → 文本合并 → LLM翻译 → 透明字幕显示（3秒自动消失）
```

---

## 🔧 配置说明（config.py）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `HOTKEY` | 触发热键 | `ctrl+shift+t` |
| `OCR_USE_GPU` | 优先使用 GPU | `True` |
| `AUTO_DETECT_SUBTITLE_REGION` | 自动检测字幕区域 | `True` |
| `SUBTITLE_BOTTOM_RATIO` | 底部区域比例 | `0.40`（底部 40%）|
| `SUBTITLE_DURATION` | 字幕显示时长（秒）| `3` |
| `MERGE_Y_THRESHOLD` | 同行 y 坐标阈值 | `15`（像素）|
| `MERGE_X_GAP_THRESHOLD` | 同行 x 间距阈值 | `50`（像素）|
| `LLM_TIMEOUT` | API 超时 | `15`（秒）|

---

## 📖 术语管理

1. 点击主窗口 **📖 术语管理**
2. 在表格中增删改术语
3. 点击 **Save** 保存到 `terminology.json`
4. 术语会自动注入到翻译 Prompt 中

---

## 💾 翻译缓存

- 缓存文件：`translation_cache.json`
- 每次翻译后自动写入缓存（异步）
- 下次遇到相同文本直接读取缓存，不再调用 LLM

---

## 📦 EXE 打包

### 安装 PyInstaller

```bash
pip install pyinstaller
```

### 打包命令

```bash
cd game_translator
pyinstaller -F -w main.py ^
    --add-data "terminology.json;." ^
    --add-data "translation_cache.json;." ^
    --hidden-import=paddleocr ^
    --hidden-import=paddle ^
    --hidden-import=cv2 ^
    --hidden-import=PyQt6 ^
    --name GameTranslator
```

> 生成的 EXE 位于 `dist/GameTranslator.exe`

### PaddleOCR 模型说明

PaddleOCR 首次运行时会自动下载模型到：  
`C:\Users\<用户>\.paddleocr\`

打包时需将模型文件夹一并包含，或在目标机器首次联网运行以下代码预下载：

```python
from paddleocr import PaddleOCR
PaddleOCR(use_angle_cls=True, lang="en", use_gpu=False)
```

### GPU 依赖注意事项

- 目标机器需安装 NVIDIA 驱动和对应 CUDA 版本
- 若无 GPU，程序自动切换 CPU 模式，无需任何修改

---

## 🧩 模块说明

| 模块 | 职责 |
|------|------|
| `ocr_engine.py` | PaddleOCR 单例，GPU/CPU 自动检测 |
| `ocr_postprocess.py` | 将碎片文字合并为完整句子 |
| `subtitle_detector.py` | 检测屏幕底部字幕密集区域，缩小 OCR 范围 |
| `translation_cache.py` | 线程安全缓存，异步持久化 |
| `prompt_builder.py` | 构建翻译 Prompt，注入术语规则 |
| `translator.py` | 缓存优先的 LLM 翻译接口 |
| `overlay_renderer.py` | 无边框全屏透明覆盖层，点击穿透 |
| `hotkey_listener.py` | 全局热键注册/注销，线程安全 |
| `terminology_manager.py` | 术语 JSON 读写 + PyQt6 可视化编辑 |

---

## ❓ 常见问题

**Q: OCR 识别不准确？**  
A: 调整 `MERGE_Y_THRESHOLD` / `MERGE_X_GAP_THRESHOLD`，或关闭 `AUTO_DETECT_SUBTITLE_REGION` 改为全屏 OCR。

**Q: 热键不生效？**  
A: 以管理员权限运行 `python main.py`（部分游戏需要管理员权限捕获键盘事件）。

**Q: 翻译 API 报错？**  
A: 检查 `LLM_API_KEY`、`LLM_API_URL`、`LLM_MODEL` 是否正确配置。

**Q: GPU 无法使用？**  
A: 确认安装了 `paddlepaddle-gpu` 且 CUDA 版本与 PaddlePaddle 匹配。详见 [PaddlePaddle 官网](https://www.paddlepaddle.org.cn/install/quick)。

---

## 📝 License

MIT License
