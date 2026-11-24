# Arrow Viewer 独立包（自带 pyarrow，离线可用）

参考 parquetbay.com 的纯本地思路：单文件 Python + 内嵌 HTML，数据不出本机。

## 最快用法（推荐）

```bat
run_viewer.bat
```

脚本自动处理依赖，无需先激活 venv：

1. 优先使用旁边的 `..\.venv`（即 install_windows.bat 建的 evalscope 环境）
2. 其次系统 Python（若已装 pyarrow）
3. 都没有 → 自动在本目录建 `.venv` 并从 `wheels\pyarrow-*.whl` 离线安装

浏览器打开 `http://127.0.0.1:8765`。

## 也可以手动跑

```bat
.venv\Scripts\activate          :: 或任何装有 pyarrow 的环境
python arrow_viewer.py offline\datasets\AI-ModelScope_gsm8k-17b55cba7ab892bd0fa18ad24199135b
```

## 支持打开

- HF `save_to_disk` 数据集目录（自动合并 `data-*.arrow` 分卷）
- 单个 `.arrow`（IPC stream/file 均可），或拖拽上传
- `.parquet` / `.csv` / `.jsonl` / `.json`

## 功能

Schema 面板、分页表格、长文本弹窗、子串搜索（全列/指定列）、导出 CSV/JSONL/JSON。

## 端口

默认 8765，仅绑 127.0.0.1；`run_viewer.bat --port 9000` 可改端口。
