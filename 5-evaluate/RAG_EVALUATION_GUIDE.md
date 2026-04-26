# RAG 评估工具迁移指南

本文档是一份**可迁移的 RAG 评估工具包**，你可以将以下代码直接复制到任意 RAG 项目中使用，无需依赖本项目的其他模块。

---

## 快速概览

| 能力 | 工具 | 依赖 |
|------|------|------|
| 命中率 (Hit Rate) | `CustomEvaluator` | 纯 Python，无需 LLM |
| 平均倒数排名 (MRR) | `CustomEvaluator` | 纯 Python，无需 LLM |
| 答案忠实度 (Faithfulness) | `RagasEvaluator` | `ragas`, `openai` |
| 答案相关性 (Answer Relevancy) | `RagasEvaluator` | `ragas`, `openai` |
| 上下文精度 (Context Precision) | `RagasEvaluator` | `ragas`, `openai` + ground_truth |
| 批量评估 | `EvalRunner` | 以上任意评估器 |
| 多后端并行 | `CompositeEvaluator` | 以上任意组合 |

---

## 第一步：安装依赖

```bash
# 基础（仅 IR 指标，无需 LLM）
pip install python

# 完整（含 Ragas LLM-as-Judge）
pip install ragas datasets openai langchain-openai nest-asyncio
```

---

## 第二步：复制核心代码

### 1. 抽象基类（必须）

新建文件 `evaluator/base_evaluator.py`：

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseEvaluator(ABC):
    """所有评估器的抽象基类，实现此接口可无缝替换评估后端。"""

    @abstractmethod
    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """评估检索与生成质量。

        Args:
            query: 用户问题字符串。
            retrieved_chunks: 检索到的文本片段列表。
                每个元素可以是：
                - str：直接文本
                - dict：含 "id"/"chunk_id"/"text"/"content" 等字段
                - 任意对象：需有 .id 和 .text 属性
            generated_answer: LLM 生成的回答（Ragas 评估必须提供）。
            ground_truth: 参考答案或期望 chunk id 列表（context_precision 需要）。
            **kwargs: 评估器特定参数。

        Returns:
            指标名 -> 浮点分数的字典，值域 [0.0, 1.0]。
        """
        pass

    def validate_query(self, query: str) -> None:
        if not isinstance(query, str):
            raise ValueError(f"Query must be a string, got {type(query).__name__}")
        if not query.strip():
            raise ValueError("Query cannot be empty or whitespace-only")

    def validate_retrieved_chunks(self, retrieved_chunks: List[Any]) -> None:
        if not isinstance(retrieved_chunks, list):
            raise ValueError("retrieved_chunks must be a list")
        if not retrieved_chunks:
            raise ValueError("retrieved_chunks cannot be empty")


class NoneEvaluator(BaseEvaluator):
    """禁用评估时的空实现，返回空指标字典。"""

    def evaluate(self, query, retrieved_chunks, generated_answer=None,
                 ground_truth=None, **kwargs) -> Dict[str, float]:
        self.validate_query(query)
        self.validate_retrieved_chunks(retrieved_chunks)
        return {}
```

---

### 2. 轻量 IR 评估器（无需 LLM）

新建文件 `evaluator/custom_evaluator.py`：

```python
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Sequence
from evaluator.base_evaluator import BaseEvaluator  # 根据你的项目路径调整


class CustomEvaluator(BaseEvaluator):
    """轻量级 IR 评估器，计算 hit_rate 和 MRR，无需调用 LLM。

    适用场景：
    - 快速回归测试（CI/CD 门禁）
    - 检索策略 A/B 测试
    - 无 LLM API 的离线环境

    用法示例::

        evaluator = CustomEvaluator(metrics=["hit_rate", "mrr"])
        metrics = evaluator.evaluate(
            query="What is RAG?",
            retrieved_chunks=[
                {"id": "chunk_001", "text": "RAG is ..."},
                {"id": "chunk_002", "text": "..."},
            ],
            ground_truth=["chunk_001"],  # 期望命中的 chunk id
        )
        # metrics == {"hit_rate": 1.0, "mrr": 1.0}
    """

    SUPPORTED_METRICS = {"hit_rate", "mrr"}
    # 支持的 id 字段名，按优先级排列
    _ID_FIELDS = ("id", "chunk_id", "document_id", "doc_id")

    def __init__(
        self,
        metrics: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> None:
        normalized = [str(m).strip().lower() for m in (metrics or [])]
        if not normalized:
            normalized = ["hit_rate", "mrr"]

        unsupported = [m for m in normalized if m not in self.SUPPORTED_METRICS]
        if unsupported:
            raise ValueError(
                f"Unsupported metrics: {', '.join(unsupported)}. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_METRICS))}"
            )
        self.metrics = normalized

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        self.validate_query(query)
        self.validate_retrieved_chunks(retrieved_chunks)

        retrieved_ids = self._extract_ids(retrieved_chunks, label="retrieved_chunks")
        ground_truth_ids = self._extract_ground_truth_ids(ground_truth)

        results: Dict[str, float] = {}
        if "hit_rate" in self.metrics:
            results["hit_rate"] = self._compute_hit_rate(retrieved_ids, ground_truth_ids)
        if "mrr" in self.metrics:
            results["mrr"] = self._compute_mrr(retrieved_ids, ground_truth_ids)
        return results

    def _extract_ground_truth_ids(self, ground_truth: Optional[Any]) -> List[str]:
        """从多种格式的 ground_truth 中提取 id 列表。

        支持格式：
        - None → 返回空列表
        - "chunk_001" → ["chunk_001"]
        - ["chunk_001", "chunk_002"] → 直接作为 id 列表
        - {"ids": ["chunk_001"]} → 提取 ids 字段
        - [{"id": "chunk_001"}] → 提取每个元素的 id 字段
        """
        if ground_truth is None:
            return []
        if isinstance(ground_truth, str):
            return [ground_truth]
        if isinstance(ground_truth, dict):
            if "ids" in ground_truth and isinstance(ground_truth["ids"], list):
                return self._extract_ids(ground_truth["ids"], label="ground_truth.ids")
            return self._extract_ids([ground_truth], label="ground_truth")
        if isinstance(ground_truth, list):
            return self._extract_ids(ground_truth, label="ground_truth")
        raise ValueError(
            f"Unsupported ground_truth type: {type(ground_truth).__name__}. "
            "Expected str, dict, list, or None."
        )

    def _extract_ids(self, items: Iterable[Any], label: str) -> List[str]:
        """从元素列表中提取 id 字符串。"""
        ids: List[str] = []
        for index, item in enumerate(items):
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                for field in self._ID_FIELDS:
                    if field in item:
                        ids.append(str(item[field]))
                        break
                else:
                    raise ValueError(
                        f"Missing id field in {label}[{index}]. "
                        f"Expected one of: {', '.join(self._ID_FIELDS)}"
                    )
            elif hasattr(item, "id"):
                ids.append(str(getattr(item, "id")))
            else:
                raise ValueError(
                    f"Cannot extract id from {label}[{index}] of type {type(item).__name__}"
                )
        return ids

    def _compute_hit_rate(
        self, retrieved_ids: Sequence[str], ground_truth_ids: Sequence[str]
    ) -> float:
        """命中率（二值）：检索结果中任意一个 id 在期望列表中 → 1.0，否则 0.0。"""
        if not ground_truth_ids:
            return 0.0
        return 1.0 if any(i in ground_truth_ids for i in retrieved_ids) else 0.0

    def _compute_mrr(
        self, retrieved_ids: Sequence[str], ground_truth_ids: Sequence[str]
    ) -> float:
        """平均倒数排名：第一个命中 chunk 的排名倒数，公式 1.0 / rank。"""
        if not ground_truth_ids:
            return 0.0
        for rank, item in enumerate(retrieved_ids, start=1):
            if item in ground_truth_ids:
                return 1.0 / rank
        return 0.0
```

---

### 3. Ragas LLM-as-Judge 评估器

新建文件 `evaluator/ragas_evaluator.py`：

```python
from __future__ import annotations
import ast
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Sequence

import nest_asyncio
nest_asyncio.apply()

from evaluator.base_evaluator import BaseEvaluator  # 根据你的项目路径调整

logger = logging.getLogger(__name__)

FAITHFULNESS = "faithfulness"
ANSWER_RELEVANCY = "answer_relevancy"
CONTEXT_PRECISION = "context_precision"
SUPPORTED_METRICS = {FAITHFULNESS, ANSWER_RELEVANCY, CONTEXT_PRECISION}


class RagasEvaluator(BaseEvaluator):
    """使用 Ragas 框架进行 LLM-as-Judge 评估。

    三个核心指标（均为 0.0~1.0 分）：
    - faithfulness：答案与检索上下文的事实一致性（衡量幻觉）
    - answer_relevancy：答案与问题的相关程度
    - context_precision：检索片段是否相关、排序是否合理（需要 ground_truth）

    依赖安装::

        pip install ragas datasets openai langchain-openai nest-asyncio

    环境变量配置（任选其一）::

        export EVAL_API_KEY=sk-xxx          # 评估用 LLM 的 API Key
        export EVAL_BASE_URL=https://...    # 可选，自定义 API 地址（兼容 OpenAI 格式）
        export OPENAI_API_KEY=sk-xxx        # 备选，若未设置 EVAL_API_KEY

    用法示例::

        evaluator = RagasEvaluator(
            api_key="sk-xxx",
            llm_model="gpt-4o-mini",
            metrics=["faithfulness", "answer_relevancy"],
        )
        metrics = evaluator.evaluate(
            query="What is RAG?",
            retrieved_chunks=[{"text": "RAG is Retrieval-Augmented Generation..."}],
            generated_answer="RAG stands for Retrieval-Augmented Generation.",
        )
        # metrics == {"faithfulness": 0.95, "answer_relevancy": 0.88}
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
        metrics: Optional[Sequence[str]] = None,
        fast_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        """初始化 RagasEvaluator。

        Args:
            api_key: LLM API Key。优先级低于环境变量 EVAL_API_KEY。
            base_url: API 地址。优先级低于环境变量 EVAL_BASE_URL。
                      兼容所有 OpenAI 格式的第三方接口（如 Azure、Qwen、DeepSeek 等）。
            llm_model: 用于评估的 LLM 模型名，默认 "gpt-4o-mini"。
            embedding_model: 用于 answer_relevancy 的 Embedding 模型，默认 "text-embedding-3-small"。
            metrics: 要计算的指标名列表。默认计算所有支持的指标。
            fast_mode: 快速模式，仅计算 faithfulness，截断上下文，降低 token 消耗。
        """
        try:
            import ragas  # noqa: F401
        except ImportError:
            raise ImportError(
                "需要安装 ragas：pip install ragas datasets"
            )

        # API 配置（优先使用环境变量）
        self._api_key = os.getenv("EVAL_API_KEY") or api_key or os.getenv("OPENAI_API_KEY")
        self._base_url = os.getenv("EVAL_BASE_URL") or base_url or "https://api.openai.com/v1"
        self._llm_model = llm_model
        self._embedding_model = embedding_model
        self.fast_mode = fast_mode

        normalized = [m.strip().lower() for m in (metrics or [])]
        if not normalized:
            normalized = sorted(SUPPORTED_METRICS)

        unsupported = [m for m in normalized if m not in SUPPORTED_METRICS]
        if unsupported:
            raise ValueError(
                f"Unsupported metrics: {', '.join(unsupported)}. "
                f"Supported: {', '.join(sorted(SUPPORTED_METRICS))}"
            )

        self._metric_names = normalized
        if fast_mode and len(self._metric_names) > 1:
            self._metric_names = [FAITHFULNESS] if FAITHFULNESS in self._metric_names else [self._metric_names[0]]

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        self.validate_query(query)
        self.validate_retrieved_chunks(retrieved_chunks)

        if not generated_answer or not generated_answer.strip():
            generated_answer = "No answer generated."
        generated_answer = self._sanitize_answer(generated_answer)
        if self.fast_mode and len(generated_answer) > 800:
            generated_answer = generated_answer[:800] + "..."

        max_chunks = 3 if self.fast_mode else 5
        if len(retrieved_chunks) > max_chunks:
            retrieved_chunks = retrieved_chunks[:max_chunks]

        contexts = self._extract_texts(retrieved_chunks)
        if not contexts or all(not c.strip() for c in contexts):
            contexts = ["No context available."]

        try:
            return self._run_ragas(query.strip(), contexts, generated_answer, ground_truth)
        except Exception as exc:
            logger.error("Ragas evaluation failed: %s", exc, exc_info=True)
            return {self._metric_name_str(m): 0.5 for m in self._metric_names}

    def _run_ragas(self, query, contexts, answer, ground_truth) -> Dict[str, float]:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy, context_precision
        from ragas.run_config import RunConfig
        from datasets import Dataset

        if not self._api_key:
            raise ValueError(
                "未找到 API Key。请设置环境变量 EVAL_API_KEY 或 OPENAI_API_KEY，"
                "或在初始化时传入 api_key 参数。"
            )

        llm, embeddings = self._build_wrappers()

        # 处理 ground_truth
        has_gt = ground_truth is not None and (
            (isinstance(ground_truth, str) and ground_truth.strip()) or
            (isinstance(ground_truth, (list, dict)) and ground_truth)
        )
        dummy_gt = answer.strip()

        data = {
            "question": [query],
            "answer": [answer],
            "contexts": [contexts],
            "ground_truth": [ground_truth if has_gt and isinstance(ground_truth, str) else dummy_gt],
            "ground_truths": [[ground_truth] if has_gt and isinstance(ground_truth, str) else [dummy_gt]],
        }
        dataset = Dataset.from_dict(data)

        # 无 ground_truth 时移除 context_precision
        metrics_to_run = list(self._metric_names)
        if not has_gt and CONTEXT_PRECISION in metrics_to_run:
            metrics_to_run.remove(CONTEXT_PRECISION)

        metric_map = {
            FAITHFULNESS: faithfulness,
            ANSWER_RELEVANCY: answer_relevancy,
            CONTEXT_PRECISION: context_precision,
        }
        selected = [metric_map[m] for m in metrics_to_run if m in metric_map]

        timeout = 120 if self.fast_mode else 300
        try:
            result = evaluate(
                dataset=dataset,
                metrics=selected,
                llm=llm,
                embeddings=embeddings,
                run_config=RunConfig(timeout=timeout),
            )
        except Exception as exc:
            logger.error("Ragas evaluate() failed: %s", exc)
            return {self._metric_name_str(m): 0.5 for m in self._metric_names}

        # 防御性分数提取：解析 str(result) 规避 Ragas 内部 KeyError
        scores = {self._metric_name_str(m): 0.5 for m in self._metric_names}
        try:
            res_str = str(result)
            d_start, d_end = res_str.find("{"), res_str.rfind("}")
            if d_start != -1 and d_end != -1:
                parsed = ast.literal_eval(res_str[d_start:d_end + 1])
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        if k in scores and isinstance(v, (int, float)):
                            if not math.isnan(v) and not math.isinf(v):
                                scores[k] = float(v)
        except Exception as e:
            logger.warning("Score extraction fallback due to: %s", e)

        return scores

    def _build_wrappers(self):
        """构建 Ragas 所需的 LLM 和 Embedding 包装器。"""
        from ragas.llms import llm_factory
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from openai import AsyncOpenAI
        from langchain_openai import OpenAIEmbeddings

        timeout = 30.0 if self.fast_mode else 60.0
        client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=timeout,
            max_retries=2 if self.fast_mode else 3,
        )
        ragas_llm = llm_factory(model=self._llm_model, client=client)
        ragas_embeddings = LangchainEmbeddingsWrapper(
            OpenAIEmbeddings(
                model=self._embedding_model,
                api_key=self._api_key,
                base_url=self._base_url,
            )
        )
        return ragas_llm, ragas_embeddings

    def _sanitize_answer(self, answer: str) -> str:
        answer = " ".join(answer.split())
        if len(answer) > 2000:
            cut = answer[:2000].rfind(".")
            answer = answer[:cut + 1] if cut > 1600 else answer[:2000] + "..."
        return answer.strip() or "No answer generated."

    def _extract_texts(self, chunks: List[Any]) -> List[str]:
        """从各种格式的 chunk 中提取文本，并按句子边界截断到 1000 字符。"""
        MAX_CHARS = 1000

        def truncate(text: str) -> str:
            if len(text) <= MAX_CHARS:
                return text.strip()
            parts = re.split(r"\n+", text)
            kept, total = [], 0
            for part in parts:
                for s in re.split(r"(?<=[。！？.!?])\s*", part.strip()):
                    s = s.strip()
                    if not s:
                        continue
                    if total + len(s) > MAX_CHARS:
                        return " ".join(kept) or text[:MAX_CHARS]
                    kept.append(s)
                    total += len(s) + 1
            return " ".join(kept) or text[:MAX_CHARS]

        texts = []
        for chunk in chunks:
            if isinstance(chunk, str):
                raw = chunk
            elif isinstance(chunk, dict):
                raw = str(chunk.get("text") or chunk.get("content") or chunk.get("page_content") or "")
            elif hasattr(chunk, "text"):
                raw = str(getattr(chunk, "text", ""))
            else:
                raw = str(chunk)

            if raw.strip():
                texts.append(truncate(raw))

        return texts or ["No context available."]

    def _metric_name_str(self, metric: str) -> str:
        return {
            FAITHFULNESS: "faithfulness",
            ANSWER_RELEVANCY: "answer_relevancy",
            CONTEXT_PRECISION: "context_precision",
        }.get(metric, metric.lower())
```

---

### 4. 组合评估器（可选，多后端并行）

新建文件 `evaluator/composite_evaluator.py`：

```python
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Sequence
from evaluator.base_evaluator import BaseEvaluator  # 根据你的项目路径调整

logger = logging.getLogger(__name__)


class CompositeEvaluator(BaseEvaluator):
    """将多个评估器组合为一个，并行运行后合并所有指标。

    特性：
    - 部分失败容错：某个子评估器失败时继续运行其他的
    - 同名指标后者覆盖前者（并记录 warning）
    - 全部子评估器失败时抛出 RuntimeError

    用法示例::

        composite = CompositeEvaluator(evaluators=[
            CustomEvaluator(metrics=["hit_rate", "mrr"]),
            RagasEvaluator(metrics=["faithfulness"]),
        ])
        metrics = composite.evaluate(
            query="test",
            retrieved_chunks=[...],
            generated_answer="...",
            ground_truth=["chunk_001"],
        )
        # metrics == {"hit_rate": 1.0, "mrr": 1.0, "faithfulness": 0.92}
    """

    def __init__(
        self,
        evaluators: Sequence[BaseEvaluator],
        **kwargs: Any,
    ) -> None:
        if not evaluators:
            raise ValueError("CompositeEvaluator 至少需要一个子评估器。")
        self._evaluators: List[BaseEvaluator] = list(evaluators)
        logger.info(
            "CompositeEvaluator 初始化，共 %d 个评估器: %s",
            len(self._evaluators),
            [type(e).__name__ for e in self._evaluators],
        )

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        self.validate_query(query)
        self.validate_retrieved_chunks(retrieved_chunks)

        merged: Dict[str, float] = {}
        errors: List[str] = []

        for ev in self._evaluators:
            name = type(ev).__name__
            try:
                metrics = ev.evaluate(
                    query=query,
                    retrieved_chunks=retrieved_chunks,
                    generated_answer=generated_answer,
                    ground_truth=ground_truth,
                    **kwargs,
                )
                for key, value in metrics.items():
                    if key in merged:
                        logger.warning("指标 '%s' 被 %s 覆盖", key, name)
                    merged[key] = value
            except Exception as exc:
                msg = f"{name} 失败: {exc}"
                logger.warning(msg)
                errors.append(msg)

        if not merged and errors:
            raise RuntimeError("所有子评估器均失败：\n" + "\n".join(errors))

        return merged
```

---

### 5. 批量评估执行器

新建文件 `evaluator/eval_runner.py`：

```python
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from evaluator.base_evaluator import BaseEvaluator  # 根据你的项目路径调整

logger = logging.getLogger(__name__)


@dataclass
class GoldenTestCase:
    """单条 Golden Test 用例。"""
    query: str
    expected_chunk_ids: List[str] = field(default_factory=list)
    expected_sources: List[str] = field(default_factory=list)
    reference_answer: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenTestCase":
        return cls(
            query=data["query"],
            expected_chunk_ids=data.get("expected_chunk_ids", []),
            expected_sources=data.get("expected_sources", []),
            reference_answer=data.get("reference_answer"),
        )


@dataclass
class QueryResult:
    """单条查询的评估结果。"""
    query: str
    retrieved_chunk_ids: List[str] = field(default_factory=list)
    generated_answer: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class EvalReport:
    """批量评估汇总报告。"""
    query_results: List[QueryResult] = field(default_factory=list)
    aggregate_metrics: Dict[str, float] = field(default_factory=dict)
    total_elapsed_ms: float = 0.0
    evaluator_name: str = ""
    test_set_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluator_name": self.evaluator_name,
            "test_set_path": self.test_set_path,
            "total_elapsed_ms": round(self.total_elapsed_ms, 1),
            "aggregate_metrics": {k: round(v, 4) for k, v in self.aggregate_metrics.items()},
            "query_count": len(self.query_results),
            "query_results": [
                {
                    "query": qr.query,
                    "retrieved_chunk_ids": qr.retrieved_chunk_ids,
                    "generated_answer": qr.generated_answer,
                    "metrics": {k: round(v, 4) for k, v in qr.metrics.items()},
                    "elapsed_ms": round(qr.elapsed_ms, 1),
                }
                for qr in self.query_results
            ],
        }


def load_test_set(path: str | Path) -> List[GoldenTestCase]:
    """从 JSON 文件加载 Golden Test Set。

    文件格式::

        {
          "test_cases": [
            {
              "query": "What is RAG?",
              "expected_chunk_ids": ["chunk_001"],
              "expected_sources": ["doc.pdf"],
              "reference_answer": "RAG stands for..."
            }
          ]
        }
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Golden test set 文件不存在: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "test_cases" not in data:
        raise ValueError("文件格式错误：缺少 'test_cases' 键。")

    return [GoldenTestCase.from_dict(tc) for tc in data["test_cases"]]


class EvalRunner:
    """批量评估执行器。

    可对接任意检索函数和生成函数，只需实现标准接口即可。

    用法示例::

        def my_retrieve(query: str, top_k: int) -> list:
            # 返回 chunk 列表，每个 chunk 是 dict 或带 id/text 属性的对象
            return vector_store.search(query, top_k)

        def my_generate(query: str, chunks: list) -> str:
            # 用你的 LLM 生成回答
            return llm.generate(query, chunks)

        runner = EvalRunner(
            retriever=my_retrieve,
            answer_generator=my_generate,
            evaluator=RagasEvaluator(api_key="sk-xxx"),
        )
        report = runner.run("tests/golden_test_set.json", top_k=5)
        print(report.aggregate_metrics)
        # {"faithfulness": 0.91, "answer_relevancy": 0.87}
    """

    def __init__(
        self,
        evaluator: BaseEvaluator,
        retriever: Optional[Callable] = None,
        answer_generator: Optional[Callable] = None,
    ) -> None:
        """初始化 EvalRunner。

        Args:
            evaluator: 评估器实例（必须）。
            retriever: 检索函数，签名 (query: str, top_k: int) -> List[chunk]。
                       若为 None，则跳过检索，直接用空列表。
            answer_generator: 生成函数，签名 (query: str, chunks: list) -> str。
                              若为 None，则拼接 chunk 文本作为占位答案。
        """
        self.evaluator = evaluator
        self.retriever = retriever
        self.answer_generator = answer_generator

    def run(
        self,
        test_set_path: str | Path,
        top_k: int = 10,
    ) -> EvalReport:
        """运行批量评估。

        Args:
            test_set_path: golden_test_set.json 的路径。
            top_k: 每个 query 检索的 chunk 数量。

        Returns:
            EvalReport，含 per-query 明细和宏平均指标。
        """
        test_cases = load_test_set(test_set_path)
        if not test_cases:
            raise ValueError("Golden test set 为空。")

        report = EvalReport(
            evaluator_name=type(self.evaluator).__name__,
            test_set_path=str(test_set_path),
        )
        t0 = time.monotonic()

        for idx, tc in enumerate(test_cases):
            print(f"\n[{idx + 1}/{len(test_cases)}] {tc.query}")
            qr = self._evaluate_single(tc, top_k)
            report.query_results.append(qr)
            print(f"    -> metrics: {qr.metrics}")

        report.total_elapsed_ms = (time.monotonic() - t0) * 1000.0
        report.aggregate_metrics = self._aggregate(report.query_results)
        print(f"\n=== 评估完成 ===\n汇总指标: {report.aggregate_metrics}")
        return report

    def _evaluate_single(self, tc: GoldenTestCase, top_k: int) -> QueryResult:
        t0 = time.monotonic()
        qr = QueryResult(query=tc.query)

        # 1. 检索
        chunks = self._retrieve(tc.query, top_k)
        qr.retrieved_chunk_ids = [self._get_id(c) for c in chunks]

        # 2. 生成回答
        answer = self._generate(tc.query, chunks)
        qr.generated_answer = answer

        # 3. 构建 ground_truth
        ground_truth = {"ids": tc.expected_chunk_ids} if tc.expected_chunk_ids else None
        if tc.reference_answer:
            ground_truth = tc.reference_answer  # Ragas 优先使用文本

        # 4. 评估
        try:
            qr.metrics = self.evaluator.evaluate(
                query=tc.query,
                retrieved_chunks=chunks if chunks else [{"id": "empty", "text": "no result"}],
                generated_answer=answer,
                ground_truth=ground_truth,
            )
        except Exception as exc:
            logger.warning("评估失败 '%s': %s", tc.query[:40], exc)

        qr.elapsed_ms = (time.monotonic() - t0) * 1000.0
        return qr

    def _retrieve(self, query: str, top_k: int) -> list:
        if self.retriever is None:
            logger.warning("未配置检索器，返回空结果。")
            return []
        try:
            return self.retriever(query, top_k)
        except Exception as exc:
            logger.warning("检索失败: %s", exc)
            return []

    def _generate(self, query: str, chunks: list) -> str:
        if self.answer_generator is not None:
            try:
                return self.answer_generator(query, chunks)
            except Exception as exc:
                logger.warning("生成失败: %s", exc)

        # 默认兜底：拼接前 3 个 chunk 的文本
        texts = []
        for c in chunks[:3]:
            if isinstance(c, str):
                texts.append(c)
            elif isinstance(c, dict):
                texts.append(str(c.get("text") or c.get("content") or ""))
            elif hasattr(c, "text"):
                texts.append(str(getattr(c, "text")))
        return " ".join(texts) or "No answer generated."

    def _get_id(self, chunk: Any) -> str:
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, dict):
            for key in ("id", "chunk_id"):
                if key in chunk:
                    return str(chunk[key])
        if hasattr(chunk, "chunk_id"):
            return str(getattr(chunk, "chunk_id"))
        if hasattr(chunk, "id"):
            return str(getattr(chunk, "id"))
        return str(chunk)

    @staticmethod
    def _aggregate(results: List[QueryResult]) -> Dict[str, float]:
        all_keys = set()
        for qr in results:
            all_keys.update(qr.metrics.keys())
        return {
            key: sum(qr.metrics[key] for qr in results if key in qr.metrics)
                 / max(1, sum(1 for qr in results if key in qr.metrics))
            for key in sorted(all_keys)
        }
```

---

## 第三步：准备 Golden Test Set

新建文件 `tests/golden_test_set.json`：

```json
{
  "test_cases": [
    {
      "query": "What is RAG?",
      "expected_chunk_ids": ["chunk_001"],
      "expected_sources": ["intro.pdf"],
      "reference_answer": "RAG stands for Retrieval-Augmented Generation, a technique that combines retrieval with LLM generation."
    },
    {
      "query": "How does vector search work?",
      "expected_chunk_ids": ["chunk_042"],
      "expected_sources": ["technical.pdf"],
      "reference_answer": "Vector search computes similarity between query and document embeddings using cosine similarity or dot product."
    }
  ]
}
```

字段说明：

| 字段 | 是否必须 | 用途 |
|------|----------|------|
| `query` | 是 | 测试问题 |
| `expected_chunk_ids` | hit_rate/MRR 需要 | 期望命中的 chunk id |
| `expected_sources` | 可选 | 期望命中的来源文件名（参考用）|
| `reference_answer` | context_precision 需要 | 参考答案文本 |

---

## 第四步：接入你的 RAG 系统

```python
import os
from evaluator.custom_evaluator import CustomEvaluator
from evaluator.ragas_evaluator import RagasEvaluator
from evaluator.composite_evaluator import CompositeEvaluator
from evaluator.eval_runner import EvalRunner

# ── 替换这两个函数为你自己的检索和生成逻辑 ──────────────────────

def my_retrieve(query: str, top_k: int) -> list:
    """接入你的向量库检索。返回含 id 和 text 字段的 dict 列表。"""
    # 示例（替换为实际代码）：
    # results = chroma_client.query(query_texts=[query], n_results=top_k)
    # return [{"id": r["id"], "text": r["document"]} for r in results]
    raise NotImplementedError("请实现检索函数")

def my_generate(query: str, chunks: list) -> str:
    """接入你的 LLM 生成。"""
    # 示例（替换为实际代码）：
    # context = "\n".join(c["text"] for c in chunks)
    # return openai_client.chat(query, context)
    raise NotImplementedError("请实现生成函数")

# ── 选择评估模式 ──────────────────────────────────────────────────

# 模式 1：仅 IR 指标（无需 LLM，最快）
evaluator = CustomEvaluator(metrics=["hit_rate", "mrr"])

# 模式 2：仅 Ragas LLM-as-Judge
evaluator = RagasEvaluator(
    api_key=os.getenv("OPENAI_API_KEY"),
    llm_model="gpt-4o-mini",
    metrics=["faithfulness", "answer_relevancy"],
)

# 模式 3：两者组合（最全面）
evaluator = CompositeEvaluator(evaluators=[
    CustomEvaluator(metrics=["hit_rate", "mrr"]),
    RagasEvaluator(
        api_key=os.getenv("OPENAI_API_KEY"),
        metrics=["faithfulness", "answer_relevancy"],
    ),
])

# ── 运行批量评估 ──────────────────────────────────────────────────

runner = EvalRunner(
    evaluator=evaluator,
    retriever=my_retrieve,
    answer_generator=my_generate,
)

report = runner.run("tests/golden_test_set.json", top_k=5)

# 打印汇总指标
print("汇总指标：", report.aggregate_metrics)

# 导出 JSON 报告
import json
with open("eval_report.json", "w") as f:
    json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
```

---

## 第五步：单次快速验证（无需完整 pipeline）

```python
from evaluator.custom_evaluator import CustomEvaluator
from evaluator.ragas_evaluator import RagasEvaluator

# 验证 IR 指标
evaluator = CustomEvaluator()
print(evaluator.evaluate(
    query="What is RAG?",
    retrieved_chunks=[
        {"id": "chunk_001", "text": "RAG is ..."},
        {"id": "chunk_002", "text": "..."},
    ],
    ground_truth=["chunk_001"],
))
# {"hit_rate": 1.0, "mrr": 1.0}

# 验证 Ragas（需要 API Key）
import os
os.environ["EVAL_API_KEY"] = "sk-xxx"

evaluator = RagasEvaluator(metrics=["faithfulness"])
print(evaluator.evaluate(
    query="What is RAG?",
    retrieved_chunks=[{"text": "RAG stands for Retrieval-Augmented Generation."}],
    generated_answer="RAG is a technique that combines retrieval with generation.",
))
# {"faithfulness": 0.95}
```

---

## 参考：指标说明与目标阈值

| 指标 | 含义 | 建议目标 | 所需输入 |
|------|------|----------|----------|
| `hit_rate` | 期望 chunk 是否被检索到 | ≥ 0.90 | `expected_chunk_ids` |
| `mrr` | 期望 chunk 的排名倒数 | ≥ 0.80 | `expected_chunk_ids` |
| `faithfulness` | 答案是否忠实于上下文（衡量幻觉） | ≥ 0.90 | `retrieved_chunks` + `generated_answer` |
| `answer_relevancy` | 答案是否切题 | ≥ 0.85 | `query` + `generated_answer` |
| `context_precision` | 检索结果是否相关且排序合理 | ≥ 0.85 | 以上全部 + `reference_answer` |

> `context_precision` 需要 `reference_answer`（即 ground_truth 文本），否则会自动跳过。

---

## 常见问题

**Q：Ragas 报错 `KeyError: 0`？**  
A：已在 `_run_ragas()` 中通过解析 `str(result)` 绕过此 Ragas 内部 bug，无需手动处理。

**Q：不想用 OpenAI，能用国产模型做裁判吗？**  
A：可以。设置兼容 OpenAI 格式的 `EVAL_BASE_URL` 即可，例如：
```bash
export EVAL_API_KEY=your-key
export EVAL_BASE_URL=https://api.deepseek.com/v1  # DeepSeek
# 或
export EVAL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # Qwen
```
然后在初始化时指定 `llm_model="deepseek-chat"` 或 `llm_model="qwen-max"`。

**Q：`expected_chunk_ids` 为空时，hit_rate 和 MRR 会是多少？**  
A：返回 0.0。建议在 golden test set 中填写真实的 chunk id，或改用 Ragas 指标。

**Q：fast_mode 适合什么场景？**  
A：适合 CI/CD 快速验证，只跑 `faithfulness` 一个指标，截断 chunk 和答案，大幅降低 token 消耗和耗时。
```python
evaluator = RagasEvaluator(fast_mode=True, api_key="sk-xxx")
```
