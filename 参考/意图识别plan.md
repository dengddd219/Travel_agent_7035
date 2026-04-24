关于这个项目是否需要意图识别
需要，但这个项目已有一套"轻量意图识别"机制，只是没有显式地叫这个名字。

当前的实现方式是：用正则 + alias表 在 agent.py:_extract_user_profile() 里做的——提取城市、天数、travel_type、budget、pace、interests 等"槽位"，本质就是意图识别+槽位填充的一体化过程。多轮对话里用 _extract_profile_updates() 做增量更新。

4点优化方向的分析与落地建议
优化1：RAG召回Few-shot样例，动态注入prompt
当前项目的gap： 知识库（ChromaDB + BM25）里存的全是小红书旅行笔记，没有"意图样例"。get_strategy_context() 召回的是POI推荐内容，不是意图识别的参考案例。

如何落地：

在 1-rag_pipeline_delivery/ 的数据里新增一个意图样例集合，每条文档包含：历史提问 / 最新提问 / 思考过程 / travel_type / budget_level / pace / 槽位值
2-rag-retrival/search_notes.py 的 search_notes() 已支持 category 过滤字段，可以加一个 category="intent_example" 的检索路径
在 agent.py 里，_extract_user_profile() 之前先RAG召回样例，拼进system prompt里，让LLM做意图+槽位一次输出
收益： 当前纯正则的提取对复杂表达（"不要太赶，主要就是吃吃喝喝"）识别弱，有了Few-shot样例兜底，准确率显著提升。

优化2：多轮对话拼接历史query后再做RAG检索
当前项目的gap： continue_conversation() 里只用最新的 user_request 去做 _extract_profile_updates()，然后把更新后的profile传给 _build_strategy_queries() 去RAG。但RAG的query是从profile重新构造的，丢失了用户原话的上下文信号。

如何落地：

在 agent.py:513 的 _extract_profile_updates() 之后，构造一个 context_query = 历史N轮用户原话 + 最新query 拼接字符串
用这个 context_query 去 search_notes() 召回，而不是只用当前query
turn_history 字段（agent.py:85）已经在 ConversationState 里存了，数据源是现成的
收益： 比如第1轮说"去香港"，第2轮说"我想吃东西"——单独"我想吃东西"召回的是模糊内容，拼上"去香港 + 我想吃东西"才能召回香港美食相关案例。

优化3：知识库加tag字段，命中后直接返回，跳过LLM调用
当前项目的gap： 所有请求都走完整的LLM工具调用循环（≤8轮），即使是简单的"香港天气怎么样"也会触发LLM推理。

如何落地：

在 1-rag_pipeline_delivery/ 的文档metadata里加 response_type 字段："direct_answer" 或 "intent_guided"
search_notes.py 召回结果里暴露这个tag
在 backend/server.py 的 /api/chat 入口处，先做一次快速RAG检索，如果命中 direct_answer 类型且置信度高，直接把知识库内容作为回答返回，不进入 TravelPlanningAgent 的LLM循环
收益： 常见FAQ类问题（签证、季节、货币）响应速度从3-5秒降到<1秒。

优化4：意图切换时主动清空历史会话，保持context干净
当前项目的gap： ConversationState.turn_history 和 preference_memory 一直累积，没有意图切换检测。如果用户从"规划香港行程"突然切换到"给我推荐上海的火锅"，旧的 preference_memory（香港、leisure、must_visit等）会干扰新的RAG检索和profile提取。

如何落地：

在 continue_conversation() 里，先对比 新提取的city/travel_type 和 state.preference_memory 里的值
如果城市变了，或者travel_type发生了根本性切换（food→theme），判定为"意图切换"
触发 preference_memory = {} + turn_history = [] 重置，相当于用新 start_conversation() 的行为处理这一轮
可以保留一个 intent_switch_log 字段记录切换历史，供调试用
收益： 解决"意图残留污染"问题，新意图的RAG召回和LLM推理都在干净的context下进行，不会出现"用户问上海美食，结果还在按香港行程规划"的问题。