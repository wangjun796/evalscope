# Arrow Viewer（本地网页版 .arrow 查看器）

参考 parquetbay.com 的纯本地思路实现：单文件 Python + 内嵌 HTML，仅依赖 pyarrow（离线包 venv 已含），数据不出本机。

## 启动（内网 Windows）

```bat
cd evalscope-offline
.venv\Scripts\activate
python tools\arrow_viewer.py
```

浏览器打开 `http://127.0.0.1:8765`。也可带参数直接预载：

```bat
python tools\arrow_viewer.py offline\datasets\AI-ModelScope_gsm8k-17b55cba7ab892bd0fa18ad24199135b
```

## 支持打开

- HF `save_to_disk` 数据集目录（自动合并 `data-*.arrow` 分卷），如 `offline/datasets/*`
- 单个 `.arrow` 文件（IPC stream / file 两种容器都支持），或拖拽上传
- 顺带支持 `.parquet` / `.csv` / `.jsonl` / `.json`

## 功能

- Schema 面板：列名、类型、空值数
- 分页表格（50/200/500 行可调），长文本截断、点击弹窗看完整单元格
- 子串搜索：全列或指定列
- 导出当前数据集为 CSV / JSONL / JSON
- 默认只绑定 127.0.0.1，无外网请求

## 端口/地址

`--port 9000 --host 0.0.0.0`（后者允许局域网其它机器访问，注意内网安全）。
