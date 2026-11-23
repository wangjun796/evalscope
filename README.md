# EvalScope 离线测试包（7z 分卷）

适用于内网 Windows x64 + Python 3.11 机器，解压后直接安装测试，无需联网、无需 git clone 代码仓库。

## 下载

把本分支的两个分卷下载到同一目录（GitHub 页面可逐个点击 Download，或整分支 zip）：

- `evalscope-offline.7z.001`
- `evalscope-offline.7z.002`

## 解压

两个分卷必须在同一目录，用 7-Zip 对 `.001` 右键 Extract Here，或命令行：

```bat
7z x evalscope-offline.7z.001
```

得到 `evalscope-offline\` 目录。

## 测试

进入该目录，按其中的 `README.md` 操作：

1. 运行 `install_windows.bat`（离线安装 evalscope 到 `.venv`）
2. `.venv\Scripts\activate`
3. 修改 `example_eval_vllm.yaml` 指向昇腾 vLLM 地址后发起评测

包内容：全部 win_amd64/cp311 依赖 wheel（含 evalscope 本体与 Web 面板）、gsm8k + mmlu 数据集缓存、安装脚本与使用说明。
