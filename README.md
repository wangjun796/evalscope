# EvalScope 数据集缓存包

`evalscope-datasets.7z`（5.4MB）包含 7 个 benchmark 的离线处理后缓存（gsm8k、mmlu、ceval、cmmlu、humaneval、truthful_qa、agieval），来自 `offline-bundle` 分支的 `offline/datasets/`。

## 用法

解压到已有离线包的 `offline` 目录（覆盖/合并 `datasets/` 子目录），或全新使用时放到任意目录，评测时：

```bash
evalscope eval --eval-type openai_api --api-url http://<ASCEND_IP>:8000/v1/chat/completions \
  --model qwen3.8 --datasets gsm8k mmlu ceval cmmlu humaneval truthful_qa agieval \
  --dataset-dir <解压后所在目录>
```

`--dataset-dir` 指向**包含 `datasets/` 的那一层目录**。缓存目录名为 `<dataset_id>-<hash>`，不要改名。

> 若你的整包 7z 分卷 `evalscope-offline.7z.002` 是 64,553,858 字节，那是旧版（只含 gsm8k/mmlu）；新版为 74,018,166 字节，请重新下载两个分卷。
