# ai-voice-agent
ai voice calling agent using live kit tool
# AI Voice Agent 🎤

A real-time AI voice calling agent built with **LiveKit** that processes voice conversations through a complete **Speech-to-Text → Language Model → Text-to-Speech (STT-LLM-TTS)** pipeline. Perfect for building intelligent voice assistants, customer service bots, and interactive voice applications.

## What It Does

This project creates an AI voice agent that:
- **Listens** to users via real-time audio streaming
- **Transcribes** speech to text using Deepgram's speech-to-text engine
- **Processes** conversations with Groq's LLM for intelligent responses
- **Speaks** back with natural text-to-speech synthesis
- **Customizes** agent behavior through YAML-based prompts

### Use Cases

- 📞 **Call Center Agents** - AI-powered customer service and support
- 🏥 **Telehealth** - Patient triage and appointment scheduling
- 🍽️ **Restaurant Orders** - Voice-based food ordering systems
- 🤖 **NPCs & Robotics** - Interactive characters and robotic systems
- 🌍 **Real-time Translation** - Live conversation translation
- 💼 **Business Assistance** - Voice-based personal assistants

## Key Features

✅ **Real-time Voice Processing** - Stream audio through ML models without lag  
✅ **Multiple AI Integrations** - Deepgram (STT), Groq (LLM), and more  
✅ **Customizable Personas** - Define agent behavior via YAML configuration  
✅ **Production Ready** - Built-in load balancing, Kubernetes support, graceful shutdowns  
✅ **Automatic Conversation Flow** - State-of-the-art turn detection for natural conversations  
✅ **Multimodal Support** - Handle voice, text, and data inputs  

## Technology Stack

- **Runtime:** Python 3.9+
- **Framework:** [LiveKit Agents SDK](https://github.com/livekit/agents)
- **Speech-to-Text:** Deepgram API
- **Language Model:** Groq API
- **Text-to-Speech:** Supported via LiveKit plugins
- **Communication:** WebRTC (via LiveKit)

## Prerequisites

Before getting started, you need:

1. **Python 3.9 or higher** - [Download here](https://www.python.org/)
2. **API Keys:**
   - [Deepgram API Key](https://console.deepgram.com/) - for speech recognition
   - [Groq API Key](https://console.groq.com/) - for the language model
3. **LiveKit Server** - Either [LiveKit Cloud](https://cloud.livekit.io/) or self-hosted

## Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd ai-voice-agent
```

### 2. Create a Virtual Environment

**On Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**On macOS/Linux:**
```bash
python -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Download LiveKit Libraries

```bash
python agent.py download-files
```

This downloads required LiveKit libraries and models needed for the agent to function.

## Configuration

### Set Environment Variables

Create a `.env.local` file in the project root:

```bash
DEEPGRAM_API_KEY=your_deepgram_api_key_here
GROQ_API_KEY=your_groq_api_key_here
LIVEKIT_URL=ws://localhost:7880  # or your LiveKit Cloud URL
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
```

### Customize Agent Behavior

Edit `prompt.yaml` to define your agent's personality and instructions:

```yaml
DENTALCLINIC:
  Prompt: |
    You are a friendly dental clinic receptionist assistant. You help patients:
    - Schedule appointments
    - Answer questions about services
    - Provide clinic information
    
    Be professional, helpful, and empathetic in your responses.
    
RESTAURANT:
  Prompt: |
    You are a helpful restaurant ordering assistant.
    Help customers browse the menu and place orders...
```

## How to Use

### Running the Agent

Choose the appropriate mode for your use case:

#### 1. **Console Mode** - Interactive Testing

```bash
python agent.py console
```

Use this to test your agent interactively in the console with debugging information.

#### 2. **Development Mode** - Local Development

```bash
python agent.py dev
```

Starts a development server for testing locally. Hot-reloads on code changes and includes detailed logging for debugging.

#### 3. **Production Mode** - Deployed Agent

```bash
python agent.py start
```

Starts the agent server in production mode. The agent will:
1. Connect to your LiveKit server
2. Wait for incoming calls/room connections
3. Automatically join rooms and process voice conversations
4. Load the persona from `prompt.yaml`

#### Default Run

```bash
python agent.py
```

Runs in standard mode (equivalent to `start`).

## Project Structure

```
ai-voice-agent/
├── agent.py              # Main agent logic (STT-LLM-TTS pipeline)
├── prompt.yaml           # Agent personas and system prompts
├── requirements.txt      # Python dependencies
├── .env.local            # Environment variables (create this)
└── README.md             # This file
```

## Key Components Explained

### `agent.py`
The main script that:
- Loads environment variables and API keys
- Connects to LiveKit server
- Configures the STT-LLM-TTS pipeline
- Handles real-time audio streaming and responses

### `prompt.yaml`
Defines multiple agent personas. The `DENTALCLINIC` example shows how to:
- Set system instructions for the LLM
- Define agent personality and behavior
- Create different agents for different use cases

### `requirements.txt`
Contains all dependencies:
- `livekit-agents` - Core agent framework
- `deepgram` - Speech recognition
- `groq-sdk` - Language model
- `pyyaml` - Configuration management
- Plus plugins for noise cancellation, turn detection, etc.

## Deployment

### Local Development
```bash
python agent.py
```

### Production Deployment
Deploy to [LiveKit Cloud](https://docs.livekit.io/deploy/agents/) for:
- Managed hosting and scaling
- Built-in observability and transcripts
- Global infrastructure
- High availability

See [LiveKit Deployment Guide](https://docs.livekit.io/agents/ops/deployment/) for detailed instructions.

## Troubleshooting

**Problem:** `DEEPGRAM_API_KEY not found`
- **Solution:** Ensure `.env.local` exists and contains your API key

**Problem:** Agent not connecting to LiveKit
- **Solution:** Check your `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`

**Problem:** No audio output
- **Solution:** Verify TTS plugin is installed; check output device permissions

## Learning Resources

🎓 **Official Guides:**
- [LiveKit Agents Documentation](https://docs.livekit.io/agents/)
- [Voice AI Quickstart](https://docs.livekit.io/agents/start/voice-ai-quickstart/)
- [Interactive Playground](https://docs.livekit.io/agents/start/playground/)

🎬 **Free Course:**
- [DeepLearning.AI - Building AI Voice Agents for Production](https://www.deeplearning.ai/short-courses/building-ai-voice-agents-for-production/)

📚 **Examples:**
- [Medical Office Triage](https://github.com/livekit-examples/python-agents-examples/tree/main/complex-agents/medical_office_triage)
- [Restaurant Ordering](https://github.com/livekit/agents/blob/main/examples/voice_agents/restaurant_agent.py)
- [Company Directory](https://docs.livekit.io/recipes/company-directory/)

## Support & Community

- 💬 [LiveKit Community](https://community.livekit.io/)
- 🐛 [Report Issues](https://github.com/livekit/agents/issues)
- 💡 [Share Ideas](https://github.com/livekit/livekit/discussions)
- 📧 [Live Support](https://livekit.io/contact)

## License

This project uses the LiveKit Agents framework, which is open source under the **Apache 2.0 License**. See the [LiveKit repository](https://github.com/livekit/livekit) for details.

## About LiveKit

[LiveKit](https://livekit.io/) is an open-source, scalable WebRTC infrastructure for building real-time applications. It powers voice, video, and AI agents with enterprise-grade performance and reliability.

---

**Ready to build?** Start with the [Voice AI Quickstart Guide](https://docs.livekit.io/agents/start/voice-ai-quickstart/) or deploy directly to [LiveKit Cloud](https://cloud.livekit.io/).
