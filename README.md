# 🧳 AI 旅行规划助手

HKU MSBA 7035 课程项目 — AI 驱动的旅行行程规划 Agent。输入你的旅行需求，自动生成多日行程、地图路线、天气预报和酒店推荐。

---

## 效果预览

- 支持北京、上海、成都、西安、香港、东京等 **12 座城市**
- 自然语言输入（中英文均可）
- 输出：Markdown 行程报告 + 高德地图可视化 + 酒店推荐
- 支持多轮对话修改行程（"把第二天改成轻松一点"）

---

## 运行前准备

### 1. 确认 Python 版本

需要 **Python 3.10 或更高版本**。

在终端输入以下命令检查：

```bash
python --version
```

如果显示 `Python 3.10.x` 或更高就没问题。如果没有安装，去 [python.org](https://www.python.org/downloads/) 下载安装。

---

### 2. 下载项目代码

**方式一：用 Git 克隆（推荐）**

```bash
git clone https://github.com/你的用户名/7035project.git
cd 7035project/Travel_agent_7035
```

**方式二：直接下载 ZIP**

点击 GitHub 页面右上角绿色的 `Code` 按钮 → `Download ZIP`，解压后进入 `Travel_agent_7035` 文件夹。

---

### 3. 安装依赖

在 `Travel_agent_7035` 目录下，运行：

```bash
pip install -r requirements.txt
```

> 如果安装很慢，可以加国内镜像：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

---

### 4. 配置 API Key

项目需要 Azure OpenAI 的 API Key 才能运行。

**第一步：复制配置模板**

```bash
cp .env.example .env
```

Windows 用户也可以手动复制 `.env.example` 文件，重命名为 `.env`。

**第二步：填入 API Key**

用记事本或任意文本编辑器打开 `.env` 文件，填入以下内容（联系项目负责人获取 Key）：

```
FOUNDRY_PROJECT_RESOURCE=...
FOUNDRY_PROJECT_API_KEY=...
FOUNDRY_PROJECT_DEPLOYMENT=gpt-5-mini
# 如果你已经拿到完整 endpoint，也可以直接填下面这一项（可选）
FOUNDRY_PROJECT_ENDPOINT=https://...
AMAP_API_KEY=...
TAVILY_API_KEY=...
DEFAULT_CITY=Hong Kong
```

> **注意**：`.env` 文件包含密钥，**不要分享给他人，不要上传到 GitHub**。

---

### 5. 初始化 RAG 知识库（首次运行必须）

这一步把旅行笔记数据载入向量数据库，只需运行一次：

```bash
cd 1-rag_pipeline_delivery
python -m rag.ingest
cd ..
```

> 预计需要 3～5 分钟，会联网调用 OpenAI 生成向量。完成后看到 `✅ Ingestion complete` 表示成功。

---

## 启动程序

在 `Travel_agent_7035` 目录下运行：

```bash
uvicorn backend.server:app --reload
```

看到以下输出说明启动成功：

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

然后打开浏览器，访问：

**http://localhost:8000**

---

## 使用方法

打开页面后，在对话框输入你的旅行需求，例如：

- `我想去成都玩 3 天，预算中等，喜欢吃火锅和看熊猫`
- `帮我规划北京 5 日游，亲子出行，要去故宫和长城`
- `上海周末两天，文艺青年路线，不要太赶`

系统会自动：
1. 规划每日行程
2. 在地图上标注路线
3. 推荐附近酒店
4. 显示天气和预计费用

支持追问修改：
- `第二天改轻松一点`
- `加上豫园`
- `酒店预算控制在 500 以内`

---

## 常见问题

**Q：启动时报 `ModuleNotFoundError`**

```bash
pip install -r requirements.txt
```

**Q：报 `AZURE_OPENAI_API_KEY not set` 或类似错误**

检查 `.env` 文件是否存在，且 Key 已正确填写（没有多余空格或引号）。

**Q：地图没有显示**

高德地图需要 `AMAP_API_KEY`，确认 `.env` 里已填入。

**Q：酒店信息显示"模拟数据"**

酒店数据通过爬虫获取，本地默认关闭（`ALLOW_MOCK_DATA=true`）。这是正常的，不影响行程规划。

**Q：Windows 下 `uvicorn` 命令找不到**

```bash
python -m uvicorn backend.server:app --reload
```

---

## 项目结构（了解即可）

```
Travel_agent_7035/
├── 0-data/              旅行笔记原始数据
├── 1-rag_pipeline_delivery/  RAG 知识库入库工具
├── 2-rag-retrival/      检索服务
├── 3-travel_planner/    AI Agent 核心逻辑
├── 4-cost/              天气/酒店/费用模块
├── 6-UI/                前端页面
├── backend/             FastAPI 后端入口
├── .env.example         环境变量模板（复制为 .env 后填写）
└── requirements.txt     Python 依赖列表
```

---

## 联系

如遇问题请联系项目负责人，或在群里反馈。
