# 第三阶段：语义缓存、Embedding 与基础 RAG

本阶段目标：理解项目里和“向量”相关的两条路径：

1. Redis 语义缓存：判断用户问题是否和历史问题语义相似，命中后直接返回旧答案。
2. FAISS 基础 RAG：把 PDF 文本切成片段，生成 embedding，查询时召回相似片段。

对应代码：

- `deepseek_agent/llm_backend/app/services/redis_semantic_cache.py`
- `deepseek_agent/llm_backend/app/services/embedding_service.py`
- `deepseek_agent/llm_backend/app/services/deepseek_service.py`
- `deepseek_agent/llm_backend/main.py`

## 1. 先区分：语义缓存不是知识库检索

很多人会把“向量相似度”都叫 RAG，但这个项目里要分清：

```text
语义缓存：
  问题 A -> 答案 A
  问题 B 和问题 A 很像 -> 直接复用答案 A

知识库检索：
  问题 Q -> 从文档片段中找证据 -> 基于证据生成答案
```

两者都用 embedding，但目的不同。

| 项目           | 输入     | 检索对象                   | 输出               |
| -------------- | -------- | -------------------------- | ------------------ |
| Redis 语义缓存 | 用户问题 | 历史问题向量               | 历史回答           |
| FAISS 基础 RAG | 用户问题 | 文档 chunk 向量            | 相关文档片段       |
| GraphRAG       | 用户问题 | 实体、关系、社区、文本单元 | 图增强上下文和回答 |

## 2. Redis 语义缓存的入口

看 `deepseek_service.py`：

```python
cache = RedisSemanticCache(prefix="deepseek", user_id=user_id)

cached_response = await cache.lookup(messages)
if cached_response:
    async for chunk in self._stream_cached_response(cached_response):
        yield chunk
    return
```

如果缓存命中，就不调用 DeepSeek API。

如果没命中：

```python
response = await self.client.chat.completions.create(...)
...
await cache.update(messages, complete_response)
```

缓存插入点：

```text
用户消息
  -> lookup
    -> 命中：返回缓存
    -> 未命中：调用模型
      -> update 写入缓存
```

## 3. Redis key 设计

看 `redis_semantic_cache.py`。

初始化：

```python
self.prefix = f"{prefix}:{user_id}" if user_id else prefix
```

这表示每个用户有独立缓存空间。

同一个问题会生成三类 key：

```python
def _get_vector_key(self, message: str) -> str:
    message_hash = hashlib.md5(message.encode()).hexdigest()
    return f"{self.prefix}:vec:{message_hash}"

def _get_response_key(self, message: str) -> str:
    message_hash = hashlib.md5(message.encode()).hexdigest()
    return f"{self.prefix}:resp:{message_hash}"

def _get_metadata_key(self, message: str) -> str:
    message_hash = hashlib.md5(message.encode()).hexdigest()
    return f"{self.prefix}:meta:{message_hash}"
```

例如用户 12 问：

```text
小米智能门锁怎么重置？
```

可能产生：

```text
deepseek:12:vec:xxxx
deepseek:12:resp:xxxx
deepseek:12:meta:xxxx
```

分别存：

- 问题向量
- 模型回答
- 创建时间、访问次数、最后访问时间

## 4. Embedding 从哪里来

Redis 缓存使用 Ollama 的 embedding 接口：

```python
async with session.post(
    f"{settings.OLLAMA_BASE_URL}/api/embed",
    json={
        "model": self.model_name,
        "input": text
    }
) as response:
    result = await response.json()
    return result["embeddings"][0]
```

配置来自：

```python
self.model_name = model_name or settings.OLLAMA_EMBEDDING_MODEL
```

所以即使普通聊天走 DeepSeek，embedding 也可以走本地 Ollama。

这是一种常见工程折中：

- 生成回答：用效果更好的在线大模型。
- 生成向量：用本地 embedding 模型，成本低、延迟可控。

## 5. 相似度如何计算

`lookup` 中核心逻辑：

```python
similarity = np.dot(current_vector, cached_vector) / (
    np.linalg.norm(current_vector) * np.linalg.norm(cached_vector)
)
```

这是余弦相似度：

```text
cosine_similarity = A · B / (|A| * |B|)
```

它衡量两个向量方向是否接近。方向越接近，语义越相似。

如果超过阈值：

```python
if max_similarity >= self.score_threshold and most_similar_key:
    ...
    return cached_response.decode('utf-8')
```

阈值来自配置：

```python
REDIS_CACHE_THRESHOLD: float = 0.8
```

举例：

```text
问题 A：小米智能门锁怎么恢复出厂设置？
问题 B：小米门锁如何重置？
```

如果 embedding 相似度大于 `0.8`，系统会复用问题 A 的答案。

## 6. 为什么要有清理任务

初始化时：

```python
asyncio.create_task(self._auto_cleanup())
```

清理逻辑：

```python
if len(all_keys) > self.max_cache_size:
    cache_items.sort(key=lambda x: x[1])
    items_to_remove = len(all_keys) - self.max_cache_size
    for key, _ in cache_items[:items_to_remove]:
        await self._remove_cache_item(hash_id)
```

它按 `last_access` 删除最久没访问的缓存。

这类似 LRU 思路，避免 Redis 无限增长。

## 7. 语义缓存的风险

语义缓存会省钱，但它有业务风险：

```text
问题 A：小米门锁 A 型号怎么重置？
问题 B：小米门锁 B 型号怎么重置？
```

如果两个问题相似度高，但型号不同、答案不同，缓存可能返回错误答案。

所以语义缓存适合：

- 闲聊
- 通用售后说明
- 高重复 FAQ

不太适合：

- 订单状态
- 实时库存
- 价格
- 用户个人信息

当前代码没有针对问题类型区分是否允许缓存，后续可以结合 Router 类型做控制，比如只缓存 `general-query`，谨慎缓存 `graphrag-query`。

## 8. 基础 RAG：`EmbeddingService`

看 `embedding_service.py`。

初始化：

```python
self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
self.index_dir = Path("indexes")
self.dimension = 384
```

这里用的是 SentenceTransformer 本地模型，向量维度 384。

创建 FAISS 索引：

```python
def _create_index(self) -> faiss.IndexFlatL2:
    return faiss.IndexFlatL2(self.dimension)
```

`IndexFlatL2` 是最朴素的向量索引：

- 不训练
- 不压缩
- 暴力计算 L2 距离
- 数据量小时简单稳定

## 9. PDF 如何变成向量

`create_embeddings`：

```python
with open(file_path, 'rb') as f:
    pdf_reader = PyPDF2.PdfReader(f)
    for page in pdf_reader.pages:
        text_chunks.append(page.extract_text())
```

当前实现是“按页切分”，不是结构感知分块。

然后生成向量：

```python
vectors = self.model.encode(text_chunks)
vectors = vectors.astype('float32')
index.add(vectors)
```

再保存文档映射：

```python
documents[str(i)] = {
    "text": text,
    "metadata": {
        "page": i + 1,
        "source": file_path
    }
}
```

最后保存：

```python
faiss.write_index(index, str(index_path))
json.dump(documents, f, ensure_ascii=False, indent=2)
```

基础 RAG 索引结构：

```text
PDF
  -> 每页提取文本
  -> SentenceTransformer 生成向量
  -> FAISS 保存向量
  -> JSON 保存 page/source/text
```

## 10. 查询时如何召回

`search` 方法：

```python
query_vector = self.model.encode([query], convert_to_tensor=False)
query_vector = query_vector.astype('float32')

distances, indices = self.current_index.search(query_vector, top_k)
```

FAISS 返回：

- `indices`：最相似文档片段编号。
- `distances`：L2 距离。

然后从 `current_documents` 取原文：

```python
results.append({
    "score": float(distances[0][i]),
    "content": self.current_documents[idx_str]["text"],
    "metadata": self.current_documents[idx_str]["metadata"]
})
```

这一步只完成“召回”，还没有做“生成回答”。

完整 RAG 应该是：

```text
query
  -> search top_k chunks
  -> 把 chunks 塞进 Prompt
  -> LLM 基于 chunks 生成答案
```

当前 `EmbeddingService` 只实现到了搜索相关片段。

## 11. 基础 RAG 和 GraphRAG 的区别

`EmbeddingService` 是传统向量 RAG：

```text
文本 chunk -> embedding -> 相似度召回
```

GraphRAG 是图增强 RAG：

```text
文档
  -> 实体抽取
  -> 关系抽取
  -> 社区发现
  -> 文本单元
  -> embedding
  -> Local / Global / Drift / Basic Search
```

传统 RAG 更简单，适合：

- 根据说明书片段回答具体问题
- FAQ 查询
- 小规模文档问答

GraphRAG 更适合：

- 多跳问题
- 跨文档总结
- 需要实体关系推理的问题
- 长文档集合的全局归纳

## 12. 本阶段你要真正理解的概念

### Embedding

Embedding 是把文本变成数字向量。语义相近的文本，向量方向通常更接近。

### 向量索引

向量索引用来快速找相似向量。FAISS 是常用向量检索库。

### Top-K 召回

给一个 query，找最相似的 K 个文档片段。

### 缓存命中

缓存命中返回的是历史答案，不一定有新的证据。

### RAG

RAG 返回答案前先检索知识，再把检索结果作为上下文交给模型。

## 13. 当前实现的不足

1. `EmbeddingService` 按页切分 PDF，粒度比较粗，容易出现一页内容过长或多主题混杂。
2. 没有看到 `EmbeddingService` 和 `/chat-rag` 的完整闭环实现，`main.py` 中引用了 `RAGChatService`，但当前扫描范围内没有对应类。
3. Redis 语义缓存没有区分实时问题和非实时问题，可能误缓存价格、库存、订单状态类答案。
4. Redis 使用 `keys(pattern)` 扫描全部 key，缓存量大时会影响性能，生产环境更适合 `SCAN`。
5. DeepSeek 缓存保存的是 JSON dump 后的片段拼接，可能影响最终保存文本的可读性。

## 14. 本阶段自测问题

1. 为什么语义缓存可以减少 API 调用成本？
2. 为什么语义缓存可能导致订单、库存、价格类问题出错？
3. `EmbeddingService` 里 FAISS 保存的是什么？
4. `documents.json` 保存的是什么？
5. 为什么基础 RAG 需要“召回 + 生成”两步？
