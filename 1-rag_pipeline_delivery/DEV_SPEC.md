#### 5.4.1 离线数据摄取流 (Ingestion Flow)

```
原始文档 (PDF / Markdown .md) [new3.6]
      │
      ▼
┌─────────────────┐     未变更则跳过
│ File Integrity  │───────────────────────────► 结束
│   (SHA256)      │
└────────┬────────┘
         │ 新文件/已变更
         ▼
┌─────────────────┐
│     Loader      │  按扩展名选择：.pdf→PdfLoader / .md→MarkdownLoader [new3.6]
│ (Pdf / MD)      │
└────────┬────────┘
         │ Document (text + metadata.images)
         ▼
┌─────────────────┐
│    Splitter     │  按语义边界切分，保留图片引用
│ (Recursive)     │
└────────┬────────┘
         │ Chunks[] (with image_refs)
         ▼
┌──────────────────────────────────────────────┐
│   Transform Pipeline (Enrichment)           │
│                                              │
│  ┌──────────────┐  ┌──────────────┐         │
│  │ ChunkRefiner │  │MetadataEnrich│         │
│  │  智能重组去噪 │  │ Title/Summary│         │
│  └──────┬───────┘  └──────┬───────┘         │
│         │                 │                │
│         ▼                 ▼                │
│    ┌──────────────┐  ┌──────────────┐      │
│    │ImageCaptioner│  │DocIntentClass│      │
│    │ 图片描述生成 │  │ 文档级意图标注│      │
│    └──────────────┘  └──────────────┘      │
│                                              │
└────────┬────────────────────────────────────┘
         │ Enriched Chunks[] (summary/tags/captions + doc_intent)
         ▼
┌─────────────────┐
│   Embedding     │  Dense (语义向量) + Sparse (BM25) 双路编码
│  (Dual Path)    │
└────────┬────────┘
         │ Vectors + Chunks + Metadata(doc_intent)
         ▼
┌─────────────────────────────────────────────────────────────┐
│    Upsert & Storage                                        │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │ Vector Store   │  │   BM25 Index  │  │  Image Storage │ │
│  │ (Chroma, by    │  │ (data/db/bm25│  │ (data/images)  │ │
│  │  collection)   │  │   /{collection})│ │                │ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
│         │                         │                         │
│         └──────────────┬──────────┴───────────┬─────────────┘
│                        ▼                      │
│         文档级意图视图 (Document Library by Intent)        │
│                        │                                  │
│   data/documents_by_intent/{intent}/{collection}/         │
│   （原始文件按 returns/fabric_care/styling/... 归档）       │
└─────────────────────────────────────────────────────────────┘
```

#### 5.4.2 在线查询流 (Query Flow)

```
用户查询 (via MCP Client)
      │
      ▼
┌─────────────────┐
│  MCP Server     │  JSON-RPC 解析，工具路由
│ (Stdio Transport)│
└────────┬────────┘
         │ query + params
         ▼
┌─────────────────┐
│ Query Processor │  关键词提取 + 同义词扩展 + Metadata 解析
│                 │
└────────┬────────┘
         │ processed_query + filters
         ▼
┌─────────────────────────────────────────────┐
│              Hybrid Search                  │
│  ┌─────────────┐          ┌─────────────┐   │
│  │Dense Retrieval│  并行   │Sparse Retrieval│   │
│  │ (Embedding)  │◄───────►│  (BM25)     │   │
│  └──────┬──────┘          └──────┬──────┘   │
│         │                        │          │
│         └────────┬───────────────┘          │
│                  ▼                          │
│         ┌─────────────┐                     │
│         │   Fusion    │  RRF 融合           │
│         │   (RRF)     │                     │
│         └──────┬──────┘                     │
└────────────────┼────────────────────────────┘
                 │ Top-M 候选
                 ▼
┌─────────────────┐
│    Reranker     │  CrossEncoder / LLM / None
│   (Optional)    │
└────────┬────────┘
         │ Top-K 精排结果
         ▼
┌─────────────────┐
│ Response Builder│  引用生成 + 图片 Base64 编码 + MCP 格式化
│                 │
└────────┬────────┘
         │ MCP Response (TextContent + ImageContent)
         ▼
返回给 MCP Client (Copilot / Claude Desktop)