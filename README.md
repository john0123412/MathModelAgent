<h1 align="center">🤖 MathModelAgent 📐</h1>
<p align="center">
    <img src="./docs/icon.png" height="250px">
</p>
<h4 align="center">
    专为数学建模设计的 Agent<br>
    自动完成数学建模，生成一份完整的可以直接提交的论文。
</h4>

<h5 align="center">简体中文 | <a href="README_EN.md">English</a></h5>

## 🌟 愿景：

3 天的比赛时间变为 1 小时 <br> 
自动完整一份可以获奖级别的建模论文

<p align="center">
    <img src="./docs/index.png">
    <img src="./docs/chat.png">
    <img src="./docs/coder.png">
    <img src="./docs/writer.png">
</p>

## ✨ 功能特性

- 🔍 自动分析问题，数学建模，编写代码，纠正错误，撰写论文
- 💻 Code Interperter
    - loacl Interperter: 基于 jupyter , 代码保存为 notebook 方便再编辑
    - 云端 code interperter: [E2B](https://e2b.dev/) 和 [daytona](https://app.daytona.io/)
- 📝 生成一份编排好格式的论文
- 🤝 muti-agents: ~~建模手~~，代码手，论文手
- 🔄 muti-llms: 每个agent设置不同的模型
- 支持所有模型: [litellm](https://docs.litellm.ai/docs/providers)
- 💰 成本低 agentless(单次任务成本约 1 rmb)

## 🚀 后期计划

- [x] 添加并完成 webui、cli
- [ ] 完善的教程、文档
- [ ] 提供 web 服务
- [ ] 英文支持（美赛）
- [ ] 集成 latex 模板
- [ ] 接入视觉模型
- [ ] 添加正确文献引用
- [x] 更多测试案例
- [ ] docker 部署
- [ ] 引入用户的交互（选择模型，重写等等）
- [x] codeinterpreter 接入云端 如 e2b 等供应商..
- [ ] 多语言: R 语言, matlab
- [ ] 绘图 napki,draw.io
- [ ] 添加 benchmark

## 视频demo

<video src="https://github.com/user-attachments/assets/954cb607-8e7e-45c6-8b15-f85e204a0c5d"></video>

> [!CAUTION]
> 项目处于实验探索迭代demo阶段，有许多需要改进优化改进地方，我(项目作者)很忙，有时间会优化更新
> 欢迎贡献


案例参考 [demo](./demo/) 文件夹下
**如果你有跑出来好的案例可以提交 PR 在该目录下**

## 📖 使用教程

> 确保电脑中安装好 Python, Nodejs, **Redis** 环境

> 如果你想运行 命令行版本 cli 切换到 [master](https://github.com/jihe520/MathModelAgent/tree/master) 分支,部署更简单，但未来不会更新



1. 配置模型

复制`/backend/.env.dev.example`到`/backend/.env.dev`(删除`.example` 后缀)

**配置环境变量**

推荐模型能力较强的、参数量大的模型。


复制`/fronted/.env.example`到`/fronted/.env`(删除`.example` 后缀)



2. 安装依赖

下载项目

```bash
git clone https://github.com/jihe520/MathModelAgent.git # 克隆项目
```

启动后端

```bash
cd backend # 切换到 backend 目录下
pip install uv # 推荐使用 uv 管理 python 项目
uv sync # 安装依赖
# 启动后端
# 激活 python 蓄虚拟环境
source .venv/bin/activate # MacOS or Linux
venv\Scripts\activate.bat # Windows
# MacOS or Linux 运行这条命令
ENV=DEV uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120 --reload
# Windows 运行这条命令
set ENV=DEV ; uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120
```

启动前端

```bash
cd frontend # 切换到 frontend 目录下
npm install -g pnpm
pnpm i #确保电脑安装了 pnpm 
pnpm run dev
```

[教程](./docs/md/tutorial.md)

运行的结果和产生在`backend/project/work_dir/xxx/*`目录下
- notebook.ipynb: 保存运行过程中产生的代码
- res.md: 保存最后运行产生的结果为 markdown 格式

## 🤝 贡献和开发

[DeepWiki](https://deepwiki.com/jihe520/MathModelAgent)

- 项目处于**开发实验阶段**（我有时间就会更新），变更较多，还存在许多 Bug，我正着手修复。
- 希望大家一起参与，让这个项目变得更好
- 非常欢迎使用和提交  **PRs** 和 issues 
- 需求参考 后期计划

clone 项目后，下载 **Todo Tree** 插件，可以查看代码中所有具体位置的 todo

`.cursor/*` 有项目整体架构、rules、mcp 可以方便开发使用

## 📄 版权License

个人免费使用，请勿商业用途。
[License](./docs/md/License.md)

## 🙏 Reference

Thanks to the following projects:
- [OpenCodeInterpreter](https://github.com/OpenCodeInterpreter/OpenCodeInterpreter/tree/main)
- [TaskWeaver](https://github.com/microsoft/TaskWeaver)
- [Code-Interpreter](https://github.com/MrGreyfun/Local-Code-Interpreter/tree/main)
- [Latex](https://github.com/Veni222987/MathModelingLatexTemplate/tree/main)
- [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)

## 其他

### Sponsor

[Buy Me a Coffee](./docs/sponser.md)

感谢赞助
[danmo-tyc](https://github.com/danmo-tyc)

### GROUP

有问题可以进群问
[QQ 群：699970403](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=rFKquDTSxKcWpEhRgpJD-dPhTtqLwJ9r&authKey=xYKvCFG5My4uYZTbIIoV5MIPQedW7hYzf0%2Fbs4EUZ100UegQWcQ8xEEgTczHsyU6&noverify=0&group_code=699970403)

<div align="center">
    <img src="./docs/qq.jpg" height="400px">
</div>