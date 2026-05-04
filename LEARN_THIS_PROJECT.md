# Repo Agent 入门路线

如果命令行不熟，先从这三个双击文件开始：

- `start_studio.bat`: 打开网页版本
- `run_demo.bat`: 跑一个固定问答演示
- `run_eval.bat`: 跑项目评估，看到 Top-1 / Top-3 / MRR

## 先记住一句话

Repo Agent 是一个代码仓库搜索和定位工具。它会读取代码，找出函数、接口、调用关系，然后根据你的问题推荐最相关的代码位置。

## 只看四个核心文件

1. `repo_agent/parsers.py`
   - 负责读懂代码结构。
   - 例如识别 `app.post('/api/chat', handleAgentStreamRequest)`。

2. `repo_agent/indexer.py`
   - 负责切代码、建索引、打分、排序。
   - 例如把“聊天流式接口”扩展成 `chat`、`stream`、`api`、`route`。

3. `repo_agent/agent.py`
   - 负责把检索结果整理成中文答案。
   - 例如输出“结论、证据链、关系扩展、关键代码摘录”。

4. `repo_agent/server.py` 和 `web/app.js`
   - 负责网页界面。

## 推荐学习顺序

第一遍只双击 `run_demo.bat`，看输出。

第二遍打开 `examples/simple_agent_app/server.js`，找到输出里提到的函数。

第三遍看 `repo_agent/parsers.py`，理解它怎么识别路由和 handler。

第四遍看 `repo_agent/indexer.py`，理解为什么某段代码分数最高。

第五遍看 `repo_agent/agent.py`，理解答案是怎么拼出来的。

## 面试版讲法

这个项目实现了一个代码仓库理解与 Bug 定位 Agent。系统先解析源码，抽取函数、路由、handler、import 和调用关系，再把代码切成 chunk 建索引。用户提问后，系统结合关键词匹配、语义投影和图关系扩展找出最相关的代码位置，最后输出带证据链的答案和 Top-K 评估指标。
