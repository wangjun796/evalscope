# EvalScope 内网离线测试包

本分支（`offline-bundle`）打包了在内网 Windows x64 + Python 3.11 机器上离线运行 EvalScope 所需的全部依赖与数据集。评测端通过 HTTP 调用昇腾服务器上的 vLLM（OpenAI 兼容 API），昇腾侧无需安装任何 EvalScope 依赖。

## 目录内容

| 路径 | 说明 |
| --- | --- |
| `offline/wheels/` | 全部 Python 依赖的 wheel/sdist（win_amd64 + cp311，含 evalscope 本体 wheel，已内置 Web 面板前端） |
| `offline/datasets/` | 预生成的数据集处理后缓存（gsm8k、mmlu、ceval、cmmlu、humaneval、truthful_qa、agieval），目录名含内容哈希，**不要改名或移动内部文件** |
| `offline/install_windows.bat` | Windows 一键离线安装脚本 |
| `offline/example_eval_vllm.yaml` | 评测配置示例 |

## 1. 拉取与拷贝

```bash
git clone -b offline-bundle https://github.com/wangjun796/evalscope.git
```

将整个目录拷贝到内网机器（约 170MB + 仓库代码）。

## 2. 内网安装（Windows x64, Python 3.11）

```bat
cd evalscope\offline
install_windows.bat
```

脚本会在 `offline\.venv` 创建虚拟环境并离线安装 `evalscope[perf,app,service]`。之后使用：

```bat
offline\.venv\Scripts\activate
```

安装校验（不依赖网络）：

```bash
evalscope eval --model mock --eval-type mock_llm --datasets gsm8k --limit 1 --dataset-dir offline
```

> 注：jieba、rouge-score、oss2 等纯 Python 包以 sdist 提供，安装时会本地构建，需要 setuptools/wheel（已随包提供）。

## 3. 对昇腾 vLLM 发起评测

确认 vLLM 服务地址（例如 `http://<ASCEND_IP>:8000/v1/chat/completions`）与 `--served-model-name` 后，修改 `example_eval_vllm.yaml` 中的 `api_url`、`model`、`dataset_dir`（指向 `offline` 目录本身，缓存位于其下的 `datasets/`），然后：

```bash
python -c "import yaml; from evalscope import TaskConfig, run_task; run_task(TaskConfig(**yaml.safe_load(open('offline/example_eval_vllm.yaml', encoding='utf-8'))))"
```

命令行方式亦可（数据集缓存仍走 `--dataset-dir`）：

```bash
evalscope eval --eval-type openai_api --api-url http://<ASCEND_IP>:8000/v1/chat/completions \
  --model qwen3.8 --datasets gsm8k --limit 5 --dataset-dir offline
```

结果输出在 `outputs/<时间戳>/`（reports/predictions/reviews）。

## 4. 压测（evalscope perf）

perf 统计 token 需要本地 tokenizer。请在昇腾服务器上拷贝模型目录中的 `tokenizer.json`、`tokenizer_config.json`、`vocab` 等文件到内网机器，然后：

```bash
evalscope perf --url http://<ASCEND_IP>:8000/v1/completions --model qwen3.8 \
  --api openai --tokenizer-path D:\models\qwen3.8-tokenizer \
  --number 50 --parallel 8
```

128K 长上下文压测可用 `--max-prompt-length 131072` / `--min-prompt-length` 控制输入长度。

## 5. Web 面板

```bash
evalscope service --host 127.0.0.1 --port 7000
```

浏览器打开 `http://127.0.0.1:7000` 查看评测任务与报告。

## 已知限制

- 数据集缓存按 `dataset_id + split + subset + revision + hub` 哈希定位；若通过 `dataset_args` 改变 revision/subset 等参数，会要求重新联网下载。当前缓存（ModelScope 源、默认 revision、默认 subset/split）：
  - `gsm8k`（test + few-shot train）
  - `mmlu`（全部 57 学科，test + dev）
  - `ceval`（全部 52 学科，val + dev）
  - `cmmlu`（全部 67 学科，test + dev）
  - `humaneval`（openai_humaneval，test；判分需本机执行模型生成的代码，Python 环境即可，无需联网）
  - `truthful_qa`（默认 `multiple_choice` 子集；如改用 `gen2` 需重新联网）
  - `agieval`（全部子集，test + dev；文章类子集含 PDF 附件）
- 文中常见的 **GAOKAO-Bench 在本仓库版本中不是独立 benchmark**，高考题能力请用已缓存的 `agieval`（含 Gaokao 2013-2024 真题子集）或 `cmmlu`/`ceval` 覆盖中文学科知识。
- mmlu 正式全量评测约 14k 题，对 128K 上下文服务属长任务，建议用 `subset_list` 分学科运行。
- 新增其它 benchmark 需在联网机器上先跑一次（`--dataset-dir offline`）以生成缓存，再同步 `offline/datasets/` 进内网。
