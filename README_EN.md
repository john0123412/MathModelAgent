<h1 align="center">🤖 MathModelAgent 📐</h1>
<p align="center">
    <img src="./docs/icon.png" height="250px">
</p>
<h4 align="center">
    An agent designed for mathematical modeling<br>
    Automatically complete mathematical modeling and generate a ready-to-submit paper.
</h4>

<h5 align="center"><a href="README.md">简体中文</a> | English</h5>

## 🌟 Vision

Turn 3 days of competition into 1 hour <br>
Automatically generate an award-level modeling paper

<p align="center">
    <img src="./docs/index.png">
    <img src="./docs/coder.png">
    <img src="./docs/writer.png">
</p>

## ✨ Features

- 🔍 Automatic problem analysis, mathematical modeling, code writing, error correction, and paper writing
- 💻 Local code interpreter
- 📝 Generate a well-formatted paper
- 🤝 Multi-agents: ~~modeling expert~~, coding expert (reflection module, local code interpreter), paper expert
- 🔄 Multi-LLMs: Different models for each agent
- 💰 Low cost agentless (about 1 RMB per task)

## 🚀 Future Plans

- [x] Add and complete webui, cli
- [ ] Comprehensive tutorials and documentation
- [ ] Provide web service
- [ ] English support (MCM/ICM)
- [ ] LaTeX template integration
- [ ] Vision model integration
- [ ] Proper citation implementation
- [ ] More test cases
- [ ] Docker deployment
- [ ] User interaction (model selection, rewriting, etc.)
- [ ] Cloud integration for code interpreter (e.g., e2b providers)
- [ ] Multi-language: R, Matlab
- [ ] Drawing: napki, draw.io

## Video Demo

<video src="https://github.com/user-attachments/assets/10b3145a-feb7-4894-aaca-30d44bb35b9e"></video>

## 📖 Usage Guide

> **Notice:** Please make sure Python, Nodejs, and **Redis** are installed on your computer.
>
> If you want to run the CLI version, switch to the [master](https://github.com/jihe520/MathModelAgent/tree/master) branch. It's easier to deploy, but will not be updated in the future.

1. Configure Model

Copy `/backend/.env.dev.example` to `/backend/.env.dev` (remove the `.example` suffix), and fill in the model configuration and APIKEY  
[Deepseek Developer Platform](https://platform.deepseek.com/)

```bash
ENV=dev
# Compatible with OpenAI format, refer to official docs
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=
DEEPSEEK_BASE_URL=
# Max Q&A turns
MAX_CHAT_TURNS=60
# Reflection retries
MAX_RETRIES=5
# https://e2b.dev/
E2B_API_KEY=

LOG_LEVEL=DEBUG
DEBUG=true
# Make sure Redis is installed
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=20
CORS_ALLOW_ORIGINS=http://localhost:5173,http://localhost:3000
```

It is recommended to use models with strong capabilities and large parameter counts.

2. Install Dependencies

Clone the project

```bash
git clone https://github.com/jihe520/MathModelAgent.git
```

Start backend

```bash
cd backend
pip install uv # Recommended: use uv to manage python projects
uv sync # Install dependencies
# Start backend
ENV=DEV uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120
```

Start frontend

```bash
cd frontend
pnpm i # Make sure pnpm is installed
pnpm run dev
```

Results and outputs are generated in the `backend/project/work_dir/xxx/*` directory:
- notebook.ipynb: code generated during execution
- res.md: final results in markdown format, can be converted to Word (try pandoc)

## 🤝 Contribution & Development

[DeepWiki](https://deepwiki.com/jihe520/MathModelAgent)


- The project is in **experimental development stage** (updated when I have time), with frequent changes and some bugs being fixed.
- Everyone is welcome to participate and make the project better.
- PRs and issues are very welcome.
- For requirements, refer to Future Plans.

After cloning the project, install the **Todo Tree** plugin to view all todo locations in the code.

`.cursor/*` contains overall architecture, rules, and mcp for easier development.

## 📄 License

Free for personal use. For commercial use, please contact me (the author).

## 🙏 Reference

Thanks to the following projects:
- [OpenCodeInterpreter](https://github.com/OpenCodeInterpreter/OpenCodeInterpreter/tree/main)
- [TaskWeaver](https://github.com/microsoft/TaskWeaver)
- [Code-Interpreter](https://github.com/MrGreyfun/Local-Code-Interpreter/tree/main)
- [Latex](https://github.com/Veni222987/MathModelingLatexTemplate/tree/main)
- [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)

## Others

Thanks to sponsors  
[danmo-tyc](https://github.com/danmo-tyc)

For questions, join the group  
[QQ Group: 699970403](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=rFKquDTSxKcWpEhRgpJD-dPhTtqLwJ9r&authKey=xYKvCFG5My4uYZTbIIoV5MIPQedW7hYzf0%2Fbs4EUZ100UegQWcQ8xEEgTczHsyU6&noverify=0&group_code=699970403)

<img src="./docs/qq.jpg" height="400px">
