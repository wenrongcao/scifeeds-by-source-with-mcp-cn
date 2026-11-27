# SciFeeds 按来源汇总：技能 + MCP

一个用于 Hermes Agent 的中文 SciFeeds 工作流，结合可移植的 RSS/Atom 订阅清单和本地只读 MCP 服务器，按来源汇总近期文章。内置订阅以地球科学期刊为主，也包括一些博客、科技和书影音来源。

## 内容

- `skills/scifeeds-by-source/SKILL.md`：中文工作流，包括来源覆盖检查、去重、日期验证、错误回退和地球科学主题筛选。
- `skills/scifeeds-by-source/references/sources.opml`：技能离线回退使用的来源快照。
- `mcp/sci_feeds_server.py`：使用 Python 标准库的本地 stdio MCP 服务器，无需额外 Python 包。
- `mcp/feeds.opml`：MCP 使用的来源清单；可直接编辑或替换为自己的 OPML。
- `mcp/tests/`：解析和 MCP 协议测试。

仓库提供的两份 OPML 初始内容一致。修改订阅时，请同步维护两份清单和下方来源列表；否则技能优先使用成功返回的 MCP 清单，离线回退时使用技能快照。

## 演示：使用本地模型NIVIDIA Nemotron 3.5 Bolt E4B

https://github.com/user-attachments/assets/e0e66129-f5f1-419f-bf66-0d7008be1079

[下载演示视频](assets/scifeeds-demo.mov)

## 安装

需要 Git、Python 3.10 或更高版本以及支持 MCP 的 Hermes Agent。克隆仓库并将技能复制到当前 Hermes profile 的技能目录：

```bash
git clone https://github.com/wenrongcao/scifeeds-by-source-with-mcp-cn.git
cd scifeeds-by-source-with-mcp-cn
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/skills/research"
cp -R skills/scifeeds-by-source "${HERMES_HOME:-$HOME/.hermes}/skills/research/"
```

如果同名技能已存在，请先备份，避免覆盖现有内容。保持克隆目录存在，再用绝对路径注册 MCP（`--args` 必须放在最后）：

```bash
hermes mcp add sci_feeds --command "$(command -v python3)" --args "$(pwd)/mcp/sci_feeds_server.py"
hermes mcp test sci_feeds
```

按提示选择启用工具。现有会话可使用 `/reload-mcp`，或开启新会话。MCP 启动后从服务器脚本同目录下的 `feeds.opml` 加载来源。也可以在其他支持 stdio MCP 的客户端中将命令设为 Python 解释器，参数设为服务器脚本的绝对路径。

## 使用

在 Hermes 中例如询问：

- “按来源列出 SciFeeds 最近 7 天的更新。”
- “查看 Nature Geoscience 最近 30 天的文章。”

`list_feeds` 返回来源名称、RSS URL 和主页 URL。`fetch_recent_entries` 接受 `days`（1–365，默认 7）、`feed_title`（可选，忽略大小写的精确名称）和 `max_per_feed`（1–100，默认 100），返回文章及各来源的错误。每个请求超时 18 秒，响应上限为 2 MiB；没有可解析日期的文章会被省略，达到每源上限也可能意味着结果不完整。服务端只检查日期下界，因此技能还会检查窗口上界，排除未来日期。

技能默认对名称恰为 **Science、Nature、Science Advances** 的来源做地球科学相关性筛选，用户也可要求全部主题。抓取失败、无更新、未能判断相关性是不同状态；某些站点可能返回 403 或无法提供完整数据，技能会按工作流尝试核查并披露覆盖缺口。

此 MCP 仅负责读取 RSS/Atom，不保存已读状态、不定时运行，也不直接实施地球科学主题筛选；后者由技能指导代理完成。抓取时会向来源网站发起网络请求。

## 测试

```bash
python3 -m unittest discover -s mcp/tests -v
hermes mcp test sci_feeds
```

## 内置来源

以下列表来自随仓库提供的 OPML；URL 中的 `&` 是正常的查询参数。

共 **32** 个来源：

- AGU Advances — <https://agupubs.onlinelibrary.wiley.com/feed/2576604x/most-recent>
- Annual Review of Earth and Planetary Sciences: Most Recent Articles — <https://www.annualreviews.org/rss/content/journals/earth/latestarticles?fmt=rss>
- Down to Earth Questions — <https://downtoearthquestions.blogspot.com/feeds/posts/default?alt=rss>
- essoar geology — <https://essopenarchive.org/action/showFeed?ui=0&mi=3fv225&type=search&feed=rss&query=%2526AllField%253Dgeology%2526content%253Dpreprints>
- EPSL — <https://rss.sciencedirect.com/publication/science/0012821X>
- ESR — <https://rss.sciencedirect.com/publication/science/00128252>
- Frontiers in Earth Science — <https://www.frontiersin.org/journals/earth-science/rss>
- Geology — <https://pubs.geoscienceworld.org/rss/site_65/advanceAccess_33.xml>
- Geoscience Frontiers — <https://rss.sciencedirect.com/publication/science/16749871>
- Geosphere — <https://pubs.geoscienceworld.org/rss/site_67/advanceAccess_34.xml>
- GGG — <https://agupubs.onlinelibrary.wiley.com/action/showFeed?jc=15252027&type=etoc&feed=rss>
- GRL — <https://agupubs.onlinelibrary.wiley.com/action/showFeed?jc=19448007&type=etoc&feed=rss>
- GSA Bulletin — <https://pubs.geoscienceworld.org/rss/site_69/advanceAccess_35.xml>
- Homepage on Miao Yu | 于淼 — <https://yufree.cn/index.xml>
- JAES — <https://rss.sciencedirect.com/publication/science/13679120>
- JGR SolidEarth — <https://agupubs.onlinelibrary.wiley.com/action/showFeed?jc=21699356&type=etoc&feed=rss>
- JSG — <https://rss.sciencedirect.com/publication/science/01918141>
- Lithos — <https://rss.sciencedirect.com/publication/science/00244937>
- Lithosphere — <https://pubs.geoscienceworld.org/rss/site_71/36.xml>
- Nature — <https://www.nature.com/nature.rss>
- Nature Geoscience — <https://www.nature.com/ngeo.rss>
- Nature Reviews Earth & Environment — <https://www.nature.com/natrevearthenviron.rss>
- PNAS Earth Sciences — <https://www.pnas.org/action/showFeed?type=searchTopic&taxonomyCode=topic&tagCode=earth-sci>
- Science — <https://feeds.science.org/rss/science.xml>
- Science Advances — <https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv>
- Speaking of Geoscience — <https://speakingofgeoscience.org/feed/>
- Tectonics — <https://agupubs.onlinelibrary.wiley.com/action/showFeed?jc=19449194&type=etoc&feed=rss>
- Tectonophysics — <https://rss.sciencedirect.com/publication/science/00401951>
- Terry Tao — <https://terrytao.wordpress.com/feed/>
- T客邦 — <https://feeds.feedburner.com/techbang/daily?format=xml>
- 豆瓣最受欢迎的书评 — <https://www.douban.com/feed/review/book>
- 豆瓣最受欢迎的影评 — <https://www.douban.com/feed/review/movie>
