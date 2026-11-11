# 第三方组件说明

MIT 许可证仅覆盖本项目原创代码和图标，不替代依赖组件的许可。
完整随包许可与声明位于 `THIRD_PARTY_LICENSES/`；固定版本见 `requirements.txt`。

| 组件 | 主要许可 | 上游与源码 |
| --- | --- | --- |
| Python 3.12 | PSF | https://www.python.org/downloads/source/ |
| PySide6 / Shiboken6 / Qt 6.12 | LGPLv3 / GPLv3，组件许可见随包文本 | https://code.qt.io/pyside/pyside-setup.git/ · https://code.qt.io/qt/ |
| RapidOCR 与随包 OCR 模型 | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime |
| OpenCV | Apache-2.0 及第三方声明 | https://github.com/opencv/opencv-python |
| NumPy | BSD-3-Clause 及第三方声明 | https://github.com/numpy/numpy |
| Pillow | HPND 等，见随包文本 | https://github.com/python-pillow/Pillow |
| PyInstaller 引导器 | GPL-2.0-or-later，含分发例外 | https://github.com/pyinstaller/pyinstaller |

其他传递依赖与构建工具的许可也一并保留在许可目录中。

## Qt / PySide6 的替换与重新构建

本项目使用 Qt Widgets 和 SVG。Qt / PySide6 库通过动态库加载，单文件 EXE 在运行时解压这些库。本项目不限制为修改、调试 LGPL 组件而进行的逆向工程。

如需替换 Qt / PySide6，可克隆本仓库，在虚拟环境中安装或自行编译兼容的修改版 PySide6 / Shiboken6 / Qt，再运行 `python app.py`，或使用 `build.ps1` 重新生成 EXE。应用的完整可修改源码、资源、依赖版本和构建脚本均随仓库公开，无需私人数据或密钥。上游源码按对应版本标签获取；本项目未修改第三方组件源码。

`assets/ocr-self-test.png` 与 `assets/ocr-failure-test.png` 是本项目绘制的合成文字测试图，不是游戏截图。
