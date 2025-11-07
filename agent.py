from livekit import agents, rtc, api
from livekit.plugins import openai, elevenlabs, silero, groq
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

# -----------------------------
#  LiveKit Agent Entrypoint
# -----------------------------
async def entrypoint(ctx: agents.JobContext):
    print("Agent started — ready to join LiveKit room")

    # Connect to LiveKit
    await ctx.connect()
    
    voice_config = {
        "id": os.getenv("VOICE_ID", "cgSgspJ2msm6clMCkdW9"),
        "model": os.getenv("VOICE_MODEL", "eleven_turbo_v2"),
        "stability": float(os.getenv("VOICE_STABILITY", 0.5)),
        "similarity_boost": float(os.getenv("VOICE_SIMILARITY", 0.75)),
        "speed": float(os.getenv("VOICE_SPEED", 1.0)),
    }

    # -----------------------------
    #  TTS Setup with fallback
    # -----------------------------
    try:
        tts_engine = elevenlabs.TTS(
            voice_id=voice_config["id"],
            model=voice_config["model"],
            voice_settings=elevenlabs.VoiceSettings(
                stability=voice_config["stability"],
                similarity_boost=voice_config["similarity_boost"],
                speed=voice_config["speed"],
            ),
        )
        print("ElevenLabs TTS loaded successfully")
    except Exception as e:
        print("ElevenLabs TTS failed, using OpenAI fallback:", e)
        tts_engine = openai.TTS(model="gpt-4o-mini-tts")

    # -----------------------------
    #  Create Session
    # -----------------------------
    session = agents.AgentSession(
        stt=openai.STT(
            model="gpt-4o-transcribe",
            prompt=f"""
            This is a conversation between you (an AI receptionist for a dental clinic) and a patient or potential patient regarding appointment booking and questions. Transcribe accurately in English with correct punctuation and formatting. In rare cases there may be other languages than English, so be prepared for that, but expect English.
            """),
        llm=groq.LLM(
            model="moonshotai/kimi-k2-instruct", 
            temperature=dental_persona.get("Temperature", 0.4)
            ),
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
