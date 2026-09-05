# 开发与构建

## 环境

产品面向 Windows 10/11 x64。建议 Python 3.11 x64；源码声明支持 Python 3.10–3.12。Windows 实际打印依赖 pywin32 和已安装的打印机驱动。macOS 可运行隔离测试，不代表存在 macOS 正式发行版。

```powershell
py -3.11 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[windows,test]"
.\.venv-win\Scripts\python.exe run.py
.\.venv-win\Scripts\python.exe -m pytest -q
```

## 目录

| 文件/目录 | 职责 |
| --- | --- |
| `run.py` | 启动入口与渲染环境初始化 |
| `src/uom_printer/ui/main_window.py` | 页面、监听、查询与登记流程协调 |
| `uom_web.py` | UOM 浏览器会话、网页请求、超时和回调管理 |
| `dji_web.py` / `dji_service.py` | DJI 查询页面、产品目录和参数读取 |
| `registration.py` | 登记字段和机型候选处理 |
| `model_catalog.py` | 本地双来源型号库和匹配 |
| `pipeline.py` | 导入、识别、渲染和打印编排 |
| `uom_service.py` | 二维码解码、UOM 数据解析 |
| `layout_template.py` / `label_renderer.py` | 毫米级模板、二维码和文字绘制 |
| `ui/layout_editor.py` / `ui/paper_selector.py` | 编辑器与纸张选择 |
| `printing.py` | Windows GDI/Spooler 打印 |
| `settings.py` / `paths.py` / `history.py` | 设置、用户目录和 SQLite 历史 |
| `tests/` | 离线自动化回归测试 |
| `scripts/` / `windows/` | 图标、构建裁剪、校验和、安装器配置 |

表中省略前缀的 Python 模块位于 `src/uom_printer/`。

## 流程边界

DJI 查询得到的机型在 UOM 人脸成功前只参与本地准备。官方认证通过后才继续读取登记字段、处理附件与准备提交。最终提交和注销需要用户确认。

处理异步操作时保留请求代次、独立超时和完成回调；刷新、重置、返回之后忽略旧请求结果。提交成功但响应丢失不能等同于提交失败，必须提示核对结果。

型号库更新只有在来源完整且校验通过时替换旧库。自动匹配不能把“最接近”当成“确定”；有歧义的型号保持人工候选确认。

## 构建安装包

在 Windows 执行 `build_windows.bat`。脚本安装依赖、运行测试、生成图标，使用 PyInstaller `onedir` 打包，再由 Inno Setup 6 生成安装程序。构建可能下载 Python/Inno Setup，请保持联网。

输出为 `release/UOM自动打印-Setup-v1.2.56.exe`，并生成 `release/安装包-SHA256.txt`。

安装版包含 Python、Qt WebEngine 和应用依赖。用户只需安装打印机驱动，不需要安装开发环境。已有正式 Release 使用该版本原安装包；重新构建由于依赖版本和时间不同，不保证二进制哈希相同。

更新代码版本时同步 `pyproject.toml`、`src/uom_printer/__init__.py`、`build_windows.bat`、`windows/installer.iss` 和 `windows/version_info.txt`。发布前在 Windows 验证安装、覆盖升级、登录、实机打印和不同缩放比例。

## 本次发布验证

本次开源整理保留 v1.2.56 运行代码和测试原样；安装包与原正式归档逐字节一致。离线测试用于验证本地业务和界面状态，不能替代当前 UOM/DJI 在线服务和真实打印机验收。
