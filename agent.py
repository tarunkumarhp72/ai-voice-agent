import logging
import os
import yaml
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    room_io,
)
from livekit.plugins import (
    noise_cancellation,
    silero,
    deepgram,
    groq,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# ===========================
#  Logger & Environment Setup
# ===========================
logger = logging.getLogger("agent-Harper-1370")
load_dotenv(".env.local")

# ===========================
#  Load Dynamic Prompt from YAML
# ===========================
prompt_path = os.path.join(os.path.dirname(__file__), "prompt.yaml")

with open(prompt_path, "r", encoding="utf-8") as f:
    prompts = yaml.safe_load(f)

# Extract the DENTALCLINIC persona from prompt.yaml
dental_persona = prompts.get("DENTALCLINIC", {})
DENTAL_PROMPT = dental_persona.get("Prompt", "You are a friendly voice assistant.")

# ===========================
#  Load API Keys from Environment
# ===========================
# Deepgram API Key for Speech-to-Text
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
if not DEEPGRAM_API_KEY:
    logger.warning("DEEPGRAM_API_KEY not found in environment variables")

# Groq API Key for Language Model
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY not found in environment variables")

# Groq Model Configuration from environment or default
GROQ_MODEL = os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct")
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.6"))
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "200"))

# Deepgram STT Configuration
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "en-IN")


# ===========================
#  DefaultAgent Class
# ===========================
class DefaultAgent(Agent):
    """
    AI Receptionist Agent for handling voice interactions.
    Uses dynamic instructions loaded from prompt.yaml (DENTALCLINIC persona).
    """
    def __init__(self) -> None:
        # Initialize agent with dynamic prompt from prompt.yaml
        super().__init__(instructions=DENTAL_PROMPT)

    async def on_enter(self):
        """
        Greeting handler called when the agent enters a session.
        Generates initial greeting to engage the user.
        """
        await self.session.generate_reply(
            instructions="""Greet the user and offer your assistance.""",
            allow_interruptions=True,
        )

    async def greet(self, context):
        """
        Custom greeting method for the AI receptionist.
        Called when the agent session starts.
        """
        await context.session.say(
            "Hi, I'm your AI receptionist. How can I help you today?"
        )


# ===========================
#  Agent Server Setup
# ===========================
server = AgentServer()

def prewarm(proc: JobProcess):
    """
    Prewarm function called at server startup.
    Loads and caches the Silero VAD (Voice Activity Detection) model
    to reduce latency during agent interactions.
    """
    proc.userdata["vad"] = silero.VAD.load()

# Register the prewarm function to execute at server startup
server.setup_fnc = prewarm

# ===========================
#  RTC Session Entrypoint
# ===========================
@server.rtc_session(agent_name="Harper-1370")
async def entrypoint(ctx: JobContext):
    """
    Main entrypoint for RTC session.
    Sets up the AgentSession with STT, LLM, TTS, and VAD components.
    
    Args:
        ctx (JobContext): Context containing room info and process data
    """
    # Initialize AgentSession with all required components using environment variables
    session = AgentSession(
        # Speech-to-Text: Uses Deepgram with Nova-2 model
        # API key loaded from DEEPGRAM_API_KEY environment variable
        stt=deepgram.STT(
            api_key=DEEPGRAM_API_KEY,
            model=DEEPGRAM_MODEL,
            language=DEEPGRAM_LANGUAGE
        ),
        
        # Language Model: Uses Groq with Moonshot Kimi K2 model
        # API key loaded from GROQ_API_KEY environment variable
        llm=groq.LLM(
            api_key=GROQ_API_KEY,
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
            max_completion_tokens=GROQ_MAX_TOKENS
        ),
        
        # Text-to-Speech: Uses Deepgram Aura-2 voice synthesis
        # API key loaded from DEEPGRAM_API_KEY environment variable
        tts=deepgram.TTS(
                api_key=DEEPGRAM_API_KEY,
                model="aura-2-thalia-en",  # Multilingual model that supports German
        ),
        
        # Turn Detection: Multilingual model for detecting speaker turns
        turn_detection=MultilingualModel(),
        
        # Voice Activity Detection: Pre-loaded Silero VAD from prewarm
        vad=ctx.proc.userdata["vad"],
        
        # Enable preemptive response generation for faster interactions
        preemptive_generation=True,
    )

    # ===========================
    #  Create Assistant Instance
    # ===========================
    assistant = DefaultAgent()

    # ===========================
    #  Start the AI Session
    # ===========================
    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            # Configure audio input with noise cancellation
            audio_input=room_io.AudioInputOptions(
                # Use BVCTelephony for SIP participants, BVC for others
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

    # ===========================
    #  Start Conversation
    # ===========================
    # Send welcome message to the user
    await session.say("Hello! Welcome to our dental clinic. How may I help you?")


if __name__ == "__main__":
    cli.run_app(server)
