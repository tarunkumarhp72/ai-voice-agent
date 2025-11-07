from livekit import agents, rtc, api
from livekit.plugins import openai, elevenlabs, silero
import asyncio
import os
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# -----------------------------
#  Load prompt.yaml
# -----------------------------
prompt_path = os.path.join(os.path.dirname(__file__), "prompt.yaml")

with open(prompt_path, "r", encoding="utf-8") as f:
    prompts = yaml.safe_load(f)

# Extract the DENTALCLINIC persona
dental_persona = prompts.get("DENTALCLINIC", {})
DENTAL_PROMPT = dental_persona.get("Prompt", "You are an AI receptionist.")
DENTAL_TEMP = dental_persona.get("Temperature", 0.4)

# -----------------------------
# 🎧 LiveKit Agent Entrypoint
# -----------------------------
async def entrypoint(ctx: agents.JobContext):
    print("Agent started — ready to join LiveKit room")

    # Connect to LiveKit
    await ctx.connect()

    # -----------------------------
    # 🗣️ TTS Setup with fallback
    # -----------------------------
    try:
        tts_engine = elevenlabs.TTS(
            voice_id="JBFqnCBsd6RMkjVDRZzb",  
            model="eleven_turbo_v2"
        )
        print("ElevenLabs TTS loaded successfully")
    except Exception as e:
        print("ElevenLabs TTS failed, using OpenAI fallback:", e)
        tts_engine = openai.TTS(model="gpt-4o-mini-tts")

    # -----------------------------
    #  Create Session
    # -----------------------------
    session = agents.AgentSession(
        stt=openai.STT(model="gpt-4o-transcribe"),
        llm=openai.LLM(model="gpt-4o-mini", temperature=DENTAL_TEMP),
        tts=tts_engine,
        vad=silero.VAD.load(),
    )

    # -----------------------------
    #  Assistant Class
    # -----------------------------
    class Assistant(agents.Agent):
        def __init__(self):
            # Use YAML persona as system prompt
            super().__init__(instructions=DENTAL_PROMPT)

        async def greet(self, context: agents.RunContext):
            await context.session.say(
                "Hi, I'm your AI receptionist. How can I help you today?"
            )

    assistant = Assistant()

    # -----------------------------
    #  Start the AI Session
    # -----------------------------
    await session.start(room=ctx.room, agent=assistant)

    # Start conversation
    await session.say("Hello! Welcome to our dental clinic. How may I help you?")

# -----------------------------
#  Main Launcher
# -----------------------------
if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("AGENT_NAME"),
        )
    )
