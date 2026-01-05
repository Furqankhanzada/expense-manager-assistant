# Expense Manager Telegram Bot

An AI-powered Telegram bot for tracking expenses. Send text, voice messages, photos of receipts, or videos - the bot uses LLMs to parse and categorize your expenses automatically.

## Features

- **Multi-modal Input**: Text, voice, audio, photos, videos, and documents
- **AI-Powered Parsing**: Uses LLMs to extract expense information from natural language
- **Receipt Scanning**: Vision AI extracts expenses from receipt photos
- **Auto-Categorization**: Intelligent expense categorization
- **Multiple LLM Providers**: OpenAI, Google Gemini, Grok (xAI), or Ollama (local)
- **Reports & Insights**: AI-generated spending reports and budget advice
- **Export**: Export data to CSV or JSON

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database (Supabase recommended)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- LLM API key (OpenAI, Google, xAI) or Ollama installed

### Installation

1. **Clone and setup**
   ```bash
   git clone <your-repo>
   cd expense-manager-telegram-bot
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Generate encryption key**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # Add this to ENCRYPTION_KEY in .env
   ```

4. **Setup database**
   ```bash
   # Create your Supabase project at https://supabase.com
   # Or use local PostgreSQL

   # Run migrations
   alembic upgrade head
   ```

5. **Run the bot**
   ```bash
   python -m src.main
   ```

## Docker Deployment

### With Docker Compose (Recommended)

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# Start services
docker-compose up -d

# View logs
docker-compose logs -f bot
```

This starts:
- The bot service
- Ollama (for local LLM, optional)

### Pull Ollama Models (if using local LLM)

```bash
docker exec -it expense-ollama ollama pull llama3.2
docker exec -it expense-ollama ollama pull llava  # For vision
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | Yes |
| `DATABASE_URL` | PostgreSQL connection URL | Yes |
| `ENCRYPTION_KEY` | Fernet key for encrypting API keys | Yes |
| `DEFAULT_LLM_PROVIDER` | Default LLM: openai, gemini, grok, ollama | No |
| `DEFAULT_LLM_MODEL` | Default model name | No |
| `OPENAI_API_KEY` | OpenAI API key | If using OpenAI |
| `GOOGLE_API_KEY` | Google AI API key | If using Gemini |
| `XAI_API_KEY` | xAI API key | If using Grok |
| `OLLAMA_BASE_URL` | Ollama server URL | If using Ollama |
| `WHISPER_MODEL` | Whisper model size (tiny/base/small/medium/large-v3) | No |

### Database Setup (Supabase)

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to Settings → Database → Connection string
3. Copy the URI and add to `DATABASE_URL` (use `postgresql+asyncpg://` prefix)

### LLM Providers

**OpenAI (Recommended)**
- Get API key from [platform.openai.com](https://platform.openai.com)
- Models: gpt-4o-mini (default), gpt-4o (for vision)

**Google Gemini**
- Get API key from [aistudio.google.com](https://aistudio.google.com)
- Models: gemini-1.5-flash, gemini-1.5-pro

**Grok (xAI)**
- Get API key from [x.ai](https://x.ai)
- Models: grok-beta, grok-vision-beta

**Ollama (Local/Free)**
- Install from [ollama.ai](https://ollama.ai)
- Models: llama3.2, llava (vision)

## Usage

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and instructions |
| `/help` | Show help |
| `/report` | Generate expense reports |
| `/categories` | View expense categories |
| `/settings` | Configure LLM and currency |
| `/export` | Export data to CSV/JSON |

### Adding Expenses

**Text**
```
Spent $25 on lunch
Uber ride 15 dollars
paid 50 euros for groceries yesterday
```

**Voice**: Record a voice message describing your expense

**Photo**: Send a photo of a receipt

**Video**: Record a video or send a video note

### Example Interactions

```
You: Spent $45 on dinner with friends last night

Bot: ✅ Expense recorded:
     💰 $45.00 - Food & Dining
     📝 Dinner with friends
     📅 Yesterday
     [Edit] [Delete] [Change Category]
```

## Project Structure

```
expense-manager-telegram-bot/
├── src/
│   ├── main.py              # Entry point
│   ├── config.py            # Configuration
│   ├── bot/
│   │   ├── handlers/        # Message handlers
│   │   ├── keyboards.py     # Inline keyboards
│   │   └── middlewares.py   # Auth & DB middleware
│   ├── llm/
│   │   ├── provider.py      # LLM abstraction
│   │   ├── expense_parser.py
│   │   ├── categorizer.py
│   │   └── reporter.py
│   ├── media/
│   │   ├── transcriber.py   # Whisper integration
│   │   ├── vision.py        # Image processing
│   │   └── video.py         # Video processing
│   └── database/
│       ├── models.py        # SQLAlchemy models
│       ├── repository.py    # Data access
│       └── connection.py    # DB connection
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src

# Linting
ruff check src
```

## License

MIT
