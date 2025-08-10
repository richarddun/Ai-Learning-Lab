# AI Learning Lab

A simple web application that teaches kids how to steer and converse with language models.  
The project is structured with a Python backend and a lightweight frontend that includes voice features.

## Development Setup

1. **Install dependencies**

```bash
pip install -r requirements.txt
```

2. **Configure environment**

Set your OpenRouter API key so the backend can access language models:

```bash
export OPENROUTER_API_KEY="your_key_here"
```

3. **Run the web server**

```bash
uvicorn backend.app.main:app --reload
```

Visit `http://localhost:8000` and open `frontend/index.html` in a browser to interact with the chat interface.

## Next steps

- Add support for more model providers.
- Improve the frontend with templates and more kid-friendly styling.
- Expand voice capabilities and persistence of conversations.
