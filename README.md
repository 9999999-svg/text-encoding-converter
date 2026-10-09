# 文本编码转换器

免费开源的批量文本编码转换工具。把 GBK、GB18030、UTF-8 或 UTF-16 等编码的文件转换到新目录，保留子目录、原文件和原有换行。先预览检查，再进行转换；解码和编码都严格校验，不替换或忽略无法转换的文字。

## Windows EXE

[下载 Windows EXE](https://github.com/9999999-svg/text-encoding-converter/releases/download/v1.0.0/TextEncodingConverter.exe) · [下载 Python 源码 ZIP](https://github.com/9999999-svg/text-encoding-converter/archive/refs/heads/main.zip) · [查看源码](text_encoding_converter.py)

双击运行。

1. 选择源文件夹，指定一个尚不存在、位于源目录外的新输出目录。
2. 根据文件来源明确选择源编码和目标编码。默认 GBK → UTF-8 BOM，适合部分中文 CSV 的转换。
3. 点击“预览检查”。确认结果后，点击“转换到新目录”。预览有错误时不会允许整批写入。

GUI 预览最多 1000 项，操作仍处理全部选择的文件。原目录不会被改写；输出目录已存在时拒绝启动，避免覆盖其他资料。

## Python 和命令行

仅使用 Python 标准库，无需 pip 运行依赖。命令行不加 `--write` 时只预览，不创建输出目录。

```powershell
python text_encoding_converter.py
python text_encoding_converter.py "D:\旧资料" "D:\UTF8资料" --from gbk --to utf-8-sig
python text_encoding_converter.py "D:\旧资料" "D:\UTF8资料" --from gbk --to utf-8-sig --write
TextEncodingConverter.exe "D:\文本" "D:\新文本" --from utf-8 --to gb18030 --extensions .txt,.srt --write
TextEncodingConverter.exe --help
```

支持：`utf-8`、`utf-8-sig`（UTF-8 BOM）、`gbk`、`gb18030`、`utf-16`（带 BOM）、`utf-16-le`、`utf-16-be`、`ascii`。UTF-8 BOM 输入请选择 `utf-8-sig`，避免把 BOM 当作正文再额外添加。工具不猜测编码；多种编码可能成功解码相同字节，预览成功也不证明源编码选对了，应检查转换后的实际文字。

默认递归选择 `.txt,.csv,.md,.json,.srt,.log`，其他文件不复制；可自定义扩展名。跳过文件和目录链接、联接及其他重解析点，明确显示。解码后含 NUL 的文件拒绝处理，避免误转换二进制。输出保持文字及换行，不保证字节、时间戳或权限与原文件相同；改写编码声明不在处理范围内，例如代码文件中的编码声明需自行核对。

单个输入文件限制 50 MiB，逐文件处理；需转换更大文本时应使用流式工具。预览后文件内容发生变化时，该文件会拒绝写入；其他已成功写出的文件保留，结果显示错误。中断或系统异常可能在新目录留下已完成文件或 `.encoding-*.tmp` 临时文件，应检查后清理，不直接复用该目录重试。

退出码：0 所选普通文件全部可转换或已转换；1 输入/编码/读写错误；2 有跳过项目或命令行格式错误；130 用户中断。

## 构建

构建环境：Windows x64、Python 3.14.6、PyInstaller 6.21.0。EXE 未签名。依赖体积和卸载见 [DEPENDENCIES.md](DEPENDENCIES.md)。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe build.py
```

自有代码和文档 MIT，第三方许可见 `licenses/` 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 自愿赞助

功能、源码和下载全部免费；赞助完全自愿。

<img src="assets/donate-wechat.png" alt="自愿微信赞助二维码" width="280">
