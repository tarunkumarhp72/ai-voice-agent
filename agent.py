from dotenv import load_dotenv
from pathlib import Path
import sys
from livekit import agents, rtc, api
from livekit.agents.voice import room_io
from livekit.agents import AgentSession, Agent, RoomInputOptions, JobContext
from livekit.plugins import (
    openai,
    elevenlabs,
    noise_cancellation,
    silero,
    groq,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents import function_tool, Agent, RunContext
import asyncio
import aiohttp
import json
import time
import random
import math
import struct
from datetime import datetime, timezone
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from qdrant_client import AsyncQdrantClient, models

#importer prompts
import yaml

# Load global environment variables
# Try loading from .env.local first, then .env as fallback
env_local_path = Path(__file__).parent / '.env.local'
env_path = Path(__file__).parent / '.env'

if env_local_path.exists():
    load_dotenv(env_local_path)
elif env_path.exists():
    load_dotenv(env_path)

# Also load from .env if it exists (for additional variables)
if env_path.exists():
    load_dotenv(env_path, override=True)

#Last inn yaml
presets_path = Path(__file__).parent / 'presets.yaml'
with open(presets_path, 'r') as file:
    presets = yaml.safe_load(file)

#Gjøre dataen til varuabler

ANBEFALT = presets['ANBEFALT']

#Import clinic settings fetcher


# Global variable to store clinic settings
clinic_settings = None


@dataclass
class CallData:
    """Data structure to track call information"""
    phone_number: str = ""
    call_start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    appointment_booked: bool = False
    conversation_messages: List[Dict[str, str]] = field(default_factory=list)  # Store conversation for summary
    # DTMF collection fields
    dtmf_digits: List[str] = field(default_factory=list)
    collected_personnummer: str = ""  # Store collected personnummer for reuse
    alternative_phone_number: str = ""  # Store DTMF-collected phone number
    language: str = "no"  # Current conversation language ("no" or "en")
    selected_appointment_date: str = ""  # Store selected appointment date for booking


# Load webhook URLs from environment
FORSTE_LEDIGE_TIME_URL = os.getenv('FORSTE_LEDIGE_TIME', 'https://n8n.csdevhub.com/webhook/sjekk_forste_ledige_time')
SJEKK_LEDIGHET_URL = os.getenv('SJEKK_LEDIGHET', 'https://n8n.csdevhub.com/webhook/sjekkLedighet')
BOOK_TIME_URL = os.getenv('BOOK_TIME', 'https://n8n.csdevhub.com/webhook/book-time')
LEGG_IGJEN_BESKJED_URL = os.getenv('LEGG_IGJEN_BESKJED', 'https://n8n.csdevhub.com/webhook-test/fallback')
GET_CLIENT_DETAIL_URL = os.getenv('GET_CLIENT_DETAIL', 'https://n8n.csdevhub.com/webhook/get_client_detail')
CANCEL_BOOKING_URL = os.getenv('CANCEL_BOOKING', 'https://n8n.csdevhub.com/webhook/cancel_booking')
UPDATE_APPOINTMENT_URL = os.getenv('UPDATE_APPOINTMENT', 'https://n8n.csdevhub.com/webhook/update_appointment_date')





# Multilingual instructions
multilingual_instructions = """
CRITICAL LANGUAGE HANDLING:

- You are bilingual (Norwegian + English), but each call must stay in a single language.

- The initial language is Norwegian. Language can be changed in two ways:
  1. When the user EXPLICITLY requests it (e.g., "speak English", "can you speak English", "snakk norsk", "kan du snakke norsk") - in this case, call sett_sprak("en") or sett_sprak("no") immediately
  2. When the user consistently speaks in a different language from the start (auto-detect on first user input) - the system will auto-detect, but you should also call sett_sprak() to ensure consistency

- IMPORTANT: If the user starts speaking in English from the beginning of the conversation, you should:
  1. Respond in English immediately
  2. Call sett_sprak("en") to update the language setting
  3. Continue in English for the rest of the conversation

- After the language is set (either explicitly or auto-detected), continue consistently in that language for the rest of the call.

- CRITICAL: When function tools return messages, they may include language hints like "Continue in English" or "Fortsett på norsk". These are instructions for YOU, not messages to repeat to the user. Do NOT repeat function return messages verbatim if they are in a different language than the current conversation. Instead, acknowledge the function result in the current conversation language.

- NEVER auto-detect or change language based on what language the user is speaking AFTER the initial language has been established. ONLY change language when the user explicitly asks you to switch.

- CRITICAL: If you don't understand a name or any other input, ask again in the SAME language. DO NOT change language just because you didn't understand something. Language can ONLY change on explicit user request.

- After the customer has explicitly requested a new language, continue the rest of the conversation consistently in that single language.

- If the user speaks in a different language than the current setting, continue responding in the current language unless they explicitly request a change.

- NEVER mix languages in a single response. Stick to one language per response.

- After collecting personal ID or phone numbers, keep speaking in the same language. If a function return says "IMPORTANT: Continue speaking in English", ensure you are already replying in English and continue accordingly.

- CRITICAL: When you need a customer's personal ID number (personnummer) for booking OR cancellation, you MUST immediately call the samle_personnummer_med_dtmf function. Do NOT ask the customer to provide it verbally - always use the DTMF collection function. This function will handle all the collection, validation, and retry logic automatically.

- CRITICAL: When customer says "cancel", "delete", "remove" booking/appointment, you MUST FIRST call samle_personnummer_med_dtmf() to collect SSN, THEN call get_client_detail().

- CRITICAL: When you need a customer's phone number (for booking or any other purpose) and they want to use a different number OR when they indicate they want to provide/enter a phone number, you MUST immediately call the samle_telefonnummer_med_dtmf function. Do NOT ask the customer to provide it verbally - always use the DTMF collection function. This function MUST be called whenever phone number collection is needed.

- CRITICAL: If you ask the customer "Do you want to use the number you're calling from, or do you want to provide a different number?" and they respond that they want to provide/enter a different number, you MUST immediately call samle_telefonnummer_med_dtmf() function. Do NOT continue the conversation without calling this function.

- CRITICAL: If the customer says anything indicating they want to provide, enter, or give a phone number (in any language), you MUST immediately call samle_telefonnummer_med_dtmf() function.

- Before you call sjekk_forste_ledige_time or sjekk_onsket_time, confirm the customer's preference (first available vs specific date) and store it with sett_booking_preference(preference="first_available" or "specific_date"). Do not call those functions until the preference is stored.

- CRITICAL: When calling book_time(), you MUST include the Dato parameter with the appointment date from the selected slot. The date format is DD/MM/YYYY (e.g., "05/12/2025"). Extract the appointment_date from the slot data returned by sjekk_forste_ledige_time() or sjekk_onsket_time(). The system will automatically store the date from the first slot, but you should still pass it explicitly when calling book_time().

CANCELLATION WORKFLOW:

- When customer says they want to cancel/delete their booking:

  STEP 1: First, say the cancel_booking_intro message to inform the customer that you need their personal number. Use the cancel_booking_intro text from LANGUAGE_TEXTS.

  STEP 2: After informing the customer, THEN call samle_personnummer_med_dtmf() function to collect SSN via DTMF. DO NOT call get_client_detail before collecting SSN.

  STEP 3: After SSN is collected, call get_client_detail() function to fetch their booking details using the collected SSN

  STEP 4: Check the response - if "already_cancelled" is True or melding contains "already cancelled", inform the customer that their booking is already cancelled and ask if they need anything else. DO NOT try to cancel again.

  STEP 5: If booking is active (not cancelled), present the booking details to customer (treatment, date, time)

  STEP 6: Ask for confirmation using cancel_booking_confirm text

  STEP 7: If customer confirms, call cancel_booking(ssn=<SSN>, start_time=<StartTime>, end_time=<EndTime>, clinic_id=<ClinicID>, treatment_id=<TreatmentID>, clinician_id=<ClinicianID>, confirm=True) with values from get_client_detail response's booking_details

  STEP 8: If customer declines, acknowledge and ask if they need anything else

CRITICAL: You MUST first inform the customer using cancel_booking_intro text, THEN call samle_personnummer_med_dtmf() function. Do NOT call the function without informing the customer first.

CRITICAL: You MUST call samle_personnummer_med_dtmf() BEFORE calling get_client_detail(). The get_client_detail function will use the collected SSN automatically.

CRITICAL: If get_client_detail returns "already_cancelled": true, inform the customer immediately and do NOT call cancel_booking function.

CRITICAL: When customer says "cancel", "delete", "remove" booking/appointment, you MUST first say cancel_booking_intro message, THEN call samle_personnummer_med_dtmf() function.

CHANGE APPOINTMENT DATE WORKFLOW:

- When customer says they want to "change", "update", "modify", or "reschedule" their appointment/booking:

  STEP 1: Call change_appointment_date() function. This function will:

    - Collect personal number via DTMF if not already collected (reuses if already collected)

    - Fetch current appointment details using get_client_detail()

    - Store treatment_type automatically for reuse in subsequent availability checks

    - Return appointment details for confirmation

  STEP 2: Present the appointment details to the customer using the message from change_appointment_date response

  STEP 3: Ask the customer to confirm if the details are correct

  STEP 4: If customer confirms the details are correct, ask: "Do you want the next available appointment or a specific date?" (use change_appointment_preference_question text)

  STEP 5: Based on customer's answer:

    - If "next available" or "first available": Use sett_booking_preference(preference="first_available"), then call sjekk_forste_ledige_time(). The treatment_type will be automatically passed from change_appointment_date().

    - If "specific date": Use sett_booking_preference(preference="specific_date"), then ask for the date and call sjekk_onsket_time(). The treatment_type will be automatically passed from change_appointment_date().

  STEP 6: Present available time slots to customer

  STEP 7: When customer selects a new time, call update_appointment_date() function instead of book_time(). Use the old appointment details stored in change_appointment_date() and the new appointment details from the selected slot:

    - ssn: from collected_personnummer

    - old_start_time, old_end_time, old_date, old_clinic_id, old_treatment_id, old_clinician_id: from change_appointment_date() response's booking_details

    - new_start_time, new_end_time, new_date, new_clinic_id, new_treatment_id, new_clinician_id: from the selected time slot (new_date from appointment_date field)

    - confirm: True

  STEP 8: After successful update, confirm the change with the customer

CRITICAL: 

- When changing appointment, ALWAYS use update_appointment_date() function, NOT book_time()

- update_appointment_date() will update the existing appointment, not create a new one

- The old appointment details are automatically stored by change_appointment_date() function

- change_appointment_date() will automatically reuse collected_personnummer if it was already collected earlier in the conversation

- change_appointment_date() automatically stores treatment_type from the current appointment, which will be automatically passed to sjekk_forste_ledige_time() and sjekk_onsket_time() when called after change_appointment_date()

- Do NOT ask for personal number again if change_appointment_date() was called successfully

- Do NOT ask for treatment type again - it's automatically passed from the appointment being changed

- Always confirm the current appointment details before asking about new appointment preference

- After confirming details, you MUST ask the preference question before searching for new appointments

"""


LANGUAGE_TEXTS = {
    "first_slot_intro": {
        "no": "la meg finne den første ledige timen vi har tilgjengelig for deg...",
        "en": "Let me find the earliest available appointment we have for you...",
    },
    "first_slot_updates": {
        "no": [
            "Et lite øyeblikk, jeg søker etter første ledige time...",
            "Vi søker fortsatt...",
            "Takk for din tålmodighet...",
            "Jeg sjekker flere alternativer for deg...",
            "Bare et øyeblikk til...",
            "Fortsetter å lete etter beste tidspunkt...",
            "Snart ferdig med søket...",
        ],
        "en": [
            "One moment, I'm searching for the earliest available slot...",
            "Still looking...",
            "Thank you for your patience...",
            "I'm reviewing a few options for you...",
            "Just a moment more...",
            "Continuing to look for the best time...",
            "Almost finished with the search...",
        ],
    },
    "first_slot_success": {
        "no": "Første ledige time ble funnet.",
        "en": "First available appointment found.",
    },
    "first_slot_error_connection": {
        "no": "Fikk ikke kontakt med bookingsystemet. Statuskode: {status}",
        "en": "Could not connect to the booking system. Status code: {status}",
    },
    "first_slot_error_technical": {
        "no": "En teknisk feil oppstod ved sjekking av ledige timer.",
        "en": "A technical error occurred while checking available appointments.",
    },
    "desired_slot_intro": {
        "no": "la meg sjekke tilgjengeligheten vår...",
        "en": "Let me check our availability...",
    },
    "desired_slot_updates": {
        "no": [
            "Et øyeblikk, jeg søker etter ledig time for deg...",
            "Vi søker fortsatt...",
            "Takk for at du venter...",
            "Ser etter ledige tidspunkter...",
            "Bare litt til, snart ferdig...",
            "Går gjennom mulighetene...",
            "Nesten fremme med resultatet...",
        ],
        "en": [
            "One moment, I'm checking for available times on that date...",
            "Still searching...",
            "Thank you for waiting...",
            "Looking through the available options...",
            "Just a little longer...",
            "Reviewing the possibilities...",
            "Almost ready with the result...",
        ],
    },
    "desired_slot_success": {
        "no": "Ledige timer ble funnet for ønsket tidsrom.",
        "en": "Available appointments found for the requested time period.",
    },
    "desired_slot_error_connection": {
        "no": "Fikk ikke kontakt med bookingsystemet. Statuskode: {status}",
        "en": "Could not connect to the booking system. Status code: {status}",
    },
    "desired_slot_error_technical": {
        "no": "En teknisk feil oppstod ved sjekking av ledige timer.",
        "en": "A technical error occurred while checking available appointments.",
    },
    "booking_intro": {
        "no": "Flott, la meg booke den timen for deg med en gang...",
        "en": "Great, let me book that appointment for you right away...",
    },
    "booking_updates": {
        "no": [
            "Bare et øyeblikk, jeg registrerer timen din...",
            "Jobber med bookingen...",
            "Takk for tålmodigheten...",
            "Snart ferdig med registreringen...",
            "Fullfører bookingen nå...",
            "Siste detaljer...",
            "Nesten klar...",
        ],
        "en": [
            "One moment, I'm recording your appointment...",
            "Working on the booking...",
            "Thanks for your patience...",
            "Almost done with the registration...",
            "Finishing the booking now...",
            "Just taking care of the last details...",
            "Almost done...",
        ],
    },
    "booking_success": {
        "no": "Time er nå booket for {name}.",
        "en": "Appointment is now booked for {name}.",
    },
    "booking_error_connection": {
        "no": "Klarte ikke å booke timen i systemet. Statuskode: {status}",
        "en": "Could not book the appointment in the system. Status code: {status}",
    },
    "booking_error_technical": {
        "no": "En teknisk feil oppstod under booking.",
        "en": "A technical error occurred during booking.",
    },
    "personnummer_already_collected": {
        "no": "Personnummer er lagret.",
        "en": "Personal ID number is stored.",
    },
    "personnummer_dtmf_instruction": {
        "no": "Venligst tast inn personnummeret ditt på telefonen din etterfulgt av firkanttegnet.",
        "en": "Please enter your personal ID number on your phone followed by the hash key.",
    },
    "personnummer_collection_failed": {
        "no": "Kunde klarte ikke taste inn personnummer korrekt",
        "en": "Customer could not enter personal ID number correctly",
    },
    "personnummer_collection_error": {
        "no": "Kunde klarte ikke korrekt taste inn personnummer, instruer kunden i hvordan korrekt bruke taster i telefonsamtale samt at hashtag ikonet er firkant tasten. Deretter når det virker som at kunden har forstått kjør funksjonen på nytt. Om problemet gjenntar seg, videresend til ekstern behandler.",
        "en": "Customer could not correctly enter personal ID number, instruct the customer on how to correctly use keys in phone call and that the hash icon is the square key. Then when it seems the customer has understood, run the function again. If the problem repeats, forward to external handler.",
    },
    "personnummer_received": {
        "no": "Takk, mottatt personnummer som slutter på {last_four}.",
        "en": "Thank you, received personal ID number ending in {last_four}.",
    },
    "personnummer_retry": {
        "no": "Beklager, prøv igjen. Tast elleve siffer etterfulgt av firkanttast.",
        "en": "Sorry, please try again. Enter eleven digits followed by the hash key.",
    },
    "phone_number_dtmf_instruction": {
        "no": "Tast inn de åtte sifrene i telefonnummeret etterfulgt av firkanttast.",
        "en": "Enter the eight digits of the phone number followed by the hash key.",
    },
    "phone_number_timeout": {
        "no": "Beklager, jeg mottok ikke noe nummer. Prøver på nytt.",
        "en": "Sorry, I did not receive any number. Trying again.",
    },
    "phone_number_timeout_return": {
        "no": "Timeout - kunde må oppgi nummer muntlig",
        "en": "Timeout - customer must provide number verbally",
    },
    "phone_number_received": {
        "no": "Takk, mottatt telefonnummer som slutter på {last_four}.",
        "en": "Thank you, received phone number ending in {last_four}.",
    },
    "phone_number_stored": {
        "no": "Telefonnummer {number} er lagret",
        "en": "Phone number {number} is stored",
    },
    "phone_number_retry": {
        "no": "Beklager, prøv igjen. Tast åtte siffer etterfulgt av firkanttast.",
        "en": "Sorry, please try again. Enter eight digits followed by the hash key.",
    },
    "leave_message_intro": {
        "no": "Jeg beklager at jeg ikke kan hjelpe deg direkte med dette. La meg legge igjen en beskjed til våre ansatte så de kan kontakte deg.",
        "en": "I'm sorry I can't help you directly with this. Let me leave a message for our staff so they can contact you.",
    },
    "leave_message_prompt": {
        "no": "Vennligst si hva du trenger hjelp med, så skal jeg notere det.",
        "en": "Please tell me what you need help with, and I'll make a note of it.",
    },
    "leave_message_updates": {
        "no": [
            "Jeg forstår situasjonen, la meg notere dette for deg...",
            "Registrerer all informasjonen...",
            "Sender beskjed til våre ansatte...",
            "Snart ferdig med å legge igjen beskjeden...",
            "Vent litt mens jeg fullfører registreringen...",
            "Sørger for at beskjeden kommer fram...",
        ],
        "en": [
            "I understand the situation, let me note this for you...",
            "Recording all the information...",
            "Sending message to our staff...",
            "Almost done leaving the message...",
            "Please wait while I complete the registration...",
            "Making sure the message gets through...",
        ],
    },
    "leave_message_success": {
        "no": "Beskjed er nå registrert og vil bli fulgt opp av våre ansatte.",
        "en": "Message has been registered and will be followed up by our staff.",
    },
    "leave_message_error": {
        "no": "Fikk ikke kontakt med systemet for å legge igjen beskjed. Statuskode: {status}",
        "en": "Could not connect to the system to leave a message. Status code: {status}",
    },
    "leave_message_technical_error": {
        "no": "En teknisk feil oppstod ved sending av beskjed.",
        "en": "A technical error occurred while sending the message.",
    },
    "leave_message_name_prompt": {
        "no": "Kan jeg få navnet ditt?",
        "en": "May I have your name?",
    },
    "leave_message_name_retry": {
        "no": "Jeg fikk ikke helt med meg navnet. Kan du si det én gang til?",
        "en": "I didn't quite catch that name. Could you repeat it for me?",
    },
    "leave_message_name_confirm": {
        "no": "Takk, {name}.",
        "en": "Thank you, {name}.",
    },
    "no_availability_first": {
        "no": "Beklager, jeg fant ingen ledige timer akkurat nå. Spør kunden om de vil legge igjen en beskjed eller sjekke tilgjengelighet for en annen behandling.",
        "en": "I'm sorry, I couldn't find any available appointments right now. Please ask if the customer would like to leave a message or check availability for another treatment.",
    },
    "no_availability_date": {
        "no": "Beklager, vi har ingen ledige timer {date}. Spør om kunden vil velge en annen dato eller første ledige tid.",
        "en": "I'm sorry, there are no appointments available on {date}. Please ask if the customer would like a different date or the next available slot.",
    },
}

class Assistant(Agent):
    def __init__(self, persona_prompt: str, clinic_name: str, booking_config: dict, call_data: CallData = None, clinic_info: dict = None, job_context: JobContext = None, agent_name: str = None, conversation_history: dict = None) -> None:
        # Get current Norwegian time
        import pytz
        norwegian_tz = pytz.timezone('Europe/Oslo')
        current_time = datetime.now(norwegian_tz)
        
        # Format date and time in Norwegian format
        day_names = {
            'Monday': 'mandag',
            'Tuesday': 'tirsdag', 
            'Wednesday': 'onsdag',
            'Thursday': 'torsdag',
            'Friday': 'fredag',
            'Saturday': 'lørdag',
            'Sunday': 'søndag'
        }
        
        month_names = {
            1: 'januar', 2: 'februar', 3: 'mars', 4: 'april',
            5: 'mai', 6: 'juni', 7: 'juli', 8: 'august',
            9: 'september', 10: 'oktober', 11: 'november', 12: 'desember'
        }
        
        day_name = day_names[current_time.strftime('%A')]
        date_str = f"{current_time.day}. {month_names[current_time.month]} {current_time.year}"
        time_str = current_time.strftime('%H:%M')
        
        # Add time context (Norwegian) to the beginning of the prompt
        time_context_no = f"""
[SYSTEMKONTEKST - IKKE FOR SAMTALE]
Dagens dato: {day_name} {date_str}
Klokkeslett nå: {time_str} (norsk tid)
[SLUTT SYSTEMKONTEKST]

"""
        
        # Add agent name and clinic context before the persona prompt
        full_prompt = time_context_no + multilingual_instructions + f"Du er {agent_name}, en AI resepsjonist hos {clinic_name} Tannklinikk. {persona_prompt}"
        
        # Add clinic info at the end if available
        if clinic_info:
            import json
            clinic_info_str = json.dumps(clinic_info, ensure_ascii=False)
            full_prompt += f"\n\nHer er informasjon om klinikken:\n{clinic_info_str}"
        
        super().__init__(instructions=full_prompt)
        self.booking_config = booking_config
        self.clinic_name = clinic_name
        self.call_data = call_data  # Store reference to call data
        self.job_context = job_context  # Store reference for SIP API access
        self.conversation_history = conversation_history  # Store conversation history as attribute
        

    @function_tool()
    async def sjekk_forste_ledige_time(
        self, context: RunContext, 
        personnr: str, 
        kundeMelding: str
        ):
        """Brukes for å finne første ledige time for pasienten"""
        
        # Determine current language (default to Norwegian)
        current_lang = "no"
        if self.call_data and getattr(self.call_data, "language", None) in ("no", "en"):
            current_lang = self.call_data.language

        # Use collected personnummer if available, otherwise collect via DTMF
        if self.call_data and self.call_data.collected_personnummer:
            personnr = self.call_data.collected_personnummer
        else:
            result = await self.samle_personnummer_med_dtmf(context)
            error_msg_no = LANGUAGE_TEXTS["personnummer_collection_failed"]["no"]
            error_msg_en = LANGUAGE_TEXTS["personnummer_collection_failed"]["en"]
            if result == error_msg_no or result == error_msg_en:
                error_instruction = LANGUAGE_TEXTS["personnummer_collection_error"].get(
                    current_lang, LANGUAGE_TEXTS["personnummer_collection_error"]["no"]
                )
                return {
                    "suksess": False,
                    "melding": error_instruction
                }
            personnr = self.call_data.collected_personnummer
        
        #Opprett en task som gir periodiske oppdateringer
        update_task = None

        async def periodic_updates():
            """Gir brukeren oppdateringer hvert 2-3.5 sekund"""
            update_messages = LANGUAGE_TEXTS["first_slot_updates"].get(
                current_lang, LANGUAGE_TEXTS["first_slot_updates"]["no"]
            )
            message_index = 0

            await asyncio.sleep(3.0)

            while True:
                try:
                    await context.session.say(
                        update_messages[message_index],
                        allow_interruptions=False
                    )
                    message_index = (message_index + 1) % len(update_messages)
                    await asyncio.sleep(random.uniform(2.0, 3.5))
                except asyncio.CancelledError:
                    break
                except Exception:
                    #Hvis noe går galt, bare avslutt
                    break

        try:
            update_task = asyncio.create_task(periodic_updates())

            await context.session.say(
                LANGUAGE_TEXTS["first_slot_intro"].get(
                    current_lang, LANGUAGE_TEXTS["first_slot_intro"]["no"]
                ),
                allow_interruptions=False
            )
            
            #hent webhook url fra konfigurasjonen
            webhook_url = FORSTE_LEDIGE_TIME_URL
            
            # Forbered data for HTTP POST request
            data = {
                "personnr": personnr,
                "kundeMelding": kundeMelding
            }
            data.update(self.booking_config)
            
            # Log webhook payload
            print(f"[WEBHOOK] sjekk_forste_ledige_time")
            print(f"[WEBHOOK] URL: {webhook_url}")
            print(f"[WEBHOOK] Payload: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # Send HTTP POST request
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(webhook_url, json=data) as response:
                        response_text = await response.text()
                        print(f"[WEBHOOK] Response Status: {response.status}")
                        print(f"[WEBHOOK] Response Body: {response_text}")
                        
                        if response.status == 200:
                            available_slots = []
                            try:
                                result = json.loads(response_text)
                                print(f"[WEBHOOK] Response JSON: {json.dumps(result, indent=2, ensure_ascii=False)}")
                                
                                # Check if there are any available slots
                                available_slots = result.get("data", {}).get("available_slots", [])
                                
                                # If no slots available, return appropriate message
                                if not available_slots or len(available_slots) == 0:
                                    no_availability_msg = LANGUAGE_TEXTS["no_availability_first"].get(
                                        current_lang, LANGUAGE_TEXTS["no_availability_first"]["no"]
                                    )
                                    return {
                                        "suksess": False,
                                        "data": result,
                                        "melding": no_availability_msg
                                    }
                                
                                # Store appointment_date from first available slot if present
                                if self.call_data and available_slots and len(available_slots) > 0:
                                    if available_slots[0].get("appointment_date"):
                                        self.call_data.selected_appointment_date = available_slots[0]["appointment_date"]
                                        print(f"[DEBUG] Stored appointment_date: {self.call_data.selected_appointment_date}")
                            except:
                                result = response_text
                            
                            # Only return success if we have slots
                            if available_slots and len(available_slots) > 0:
                                success_msg = LANGUAGE_TEXTS["first_slot_success"].get(
                                    current_lang, LANGUAGE_TEXTS["first_slot_success"]["no"]
                                )
                                return {
                                    "suksess": True,
                                    "data": result,
                                    "melding": success_msg
                                }
                            else:
                                no_availability_msg = LANGUAGE_TEXTS["no_availability_first"].get(
                                    current_lang, LANGUAGE_TEXTS["no_availability_first"]["no"]
                                )
                                return {
                                    "suksess": False,
                                    "data": result,
                                    "melding": no_availability_msg
                                }
                        elif response.status == 404:
                            # 404 might mean no availability, check response body
                            try:
                                result = json.loads(response_text)
                                available_slots = result.get("data", {}).get("available_slots", [])
                                if not available_slots or len(available_slots) == 0:
                                    no_availability_msg = LANGUAGE_TEXTS["no_availability_first"].get(
                                        current_lang, LANGUAGE_TEXTS["no_availability_first"]["no"]
                                    )
                                    return {
                                        "suksess": False,
                                        "data": result,
                                        "melding": no_availability_msg
                                    }
                            except:
                                pass
                            
                            # If it's a real 404 error, return connection error
                            error_msg = LANGUAGE_TEXTS["first_slot_error_connection"].get(
                                current_lang, LANGUAGE_TEXTS["first_slot_error_connection"]["no"]
                            ).format(status=str(response.status))
                            return {
                                "suksess": False,
                                "melding": error_msg
                            }
                        else:
                            error_msg = LANGUAGE_TEXTS["first_slot_error_connection"].get(
                                current_lang, LANGUAGE_TEXTS["first_slot_error_connection"]["no"]
                            ).format(status=str(response.status))
                            return {
                                "suksess": False,
                                "melding": error_msg
                            }
                except Exception as e:
                    error_msg = LANGUAGE_TEXTS["first_slot_error_technical"].get(
                        current_lang, LANGUAGE_TEXTS["first_slot_error_technical"]["no"]
                    )
                    return {
                        "suksess": False,
                        "melding": error_msg
                    }
            
        finally:
            # Avbryt oppdaterings-tasken
            if update_task:
                update_task.cancel()
                try:
                    await update_task
                except asyncio.CancelledError:
                    pass
    @function_tool()
    async def sjekk_onsket_time(
        self, context: RunContext, 
        personnr: str, 
        kundeMelding: str,
        OnsketDato: str
        ):
        """Brukes for å se om ønsket dato har ledig time"""
        
        # Determine current language (default to Norwegian)
        current_lang = "no"
        if self.call_data and getattr(self.call_data, "language", None) in ("no", "en"):
            current_lang = self.call_data.language

        # Use collected personnummer if available, otherwise collect via DTMF
        if self.call_data and self.call_data.collected_personnummer:
            personnr = self.call_data.collected_personnummer
        else:
            result = await self.samle_personnummer_med_dtmf(context)
            error_msg_no = LANGUAGE_TEXTS["personnummer_collection_failed"]["no"]
            error_msg_en = LANGUAGE_TEXTS["personnummer_collection_failed"]["en"]
            if result == error_msg_no or result == error_msg_en:
                error_instruction = LANGUAGE_TEXTS["personnummer_collection_error"].get(
                    current_lang, LANGUAGE_TEXTS["personnummer_collection_error"]["no"]
                )
                return {
                    "suksess": False,
                    "melding": error_instruction
                }
            personnr = self.call_data.collected_personnummer
        
        #Opprett en task som gir periodiske oppdateringer
        update_task = None

        async def periodic_updates():
            """Gir brukeren oppdateringer hvert 2-3.5 sekund"""
            update_messages = LANGUAGE_TEXTS["desired_slot_updates"].get(
                current_lang, LANGUAGE_TEXTS["desired_slot_updates"]["no"]
            )
            message_index = 0

            await asyncio.sleep(3.0)

            while True:
                try:
                    await context.session.say(
                        update_messages[message_index],
                        allow_interruptions=False
                    )
                    message_index = (message_index + 1) % len(update_messages)
                    await asyncio.sleep(random.uniform(2.0, 3.5))
                except asyncio.CancelledError:
                    break
                except Exception:
                    #Hvis noe går galt, bare avslutt
                    break

        try:
            update_task = asyncio.create_task(periodic_updates())

            await context.session.say(
                LANGUAGE_TEXTS["desired_slot_intro"].get(
                    current_lang, LANGUAGE_TEXTS["desired_slot_intro"]["no"]
                ),
                allow_interruptions=False
            )
            
            #hent webhook url fra konfigurasjonen
            webhook_url = SJEKK_LEDIGHET_URL
            
            # Forbered data for HTTP POST request
            data = {
                "personnr": personnr,
                "kundeMelding": kundeMelding,
                "OnsketDato": OnsketDato
            }
            data.update(self.booking_config)
            
            # Log webhook payload
            print(f"[WEBHOOK] sjekk_onsket_time")
            print(f"[WEBHOOK] URL: {webhook_url}")
            print(f"[WEBHOOK] Payload: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # Send HTTP POST request
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(webhook_url, json=data) as response:
                        response_text = await response.text()
                        print(f"[WEBHOOK] Response Status: {response.status}")
                        print(f"[WEBHOOK] Response Body: {response_text}")
                        
                        if response.status == 200:
                            available_slots = []
                            try:
                                result = json.loads(response_text)
                                print(f"[WEBHOOK] Response JSON: {json.dumps(result, indent=2, ensure_ascii=False)}")
                                
                                # Check if there are any available slots
                                available_slots = result.get("data", {}).get("available_slots", [])
                                
                                # If no slots available, return appropriate message
                                if not available_slots or len(available_slots) == 0:
                                    no_availability_msg = LANGUAGE_TEXTS["no_availability_date"].get(
                                        current_lang, LANGUAGE_TEXTS["no_availability_date"]["no"]
                                    ).format(date=OnsketDato)
                                    return {
                                        "suksess": False,
                                        "data": result,
                                        "melding": no_availability_msg
                                    }
                                
                                # Store appointment_date from first available slot if present
                                if self.call_data and available_slots and len(available_slots) > 0:
                                    if available_slots[0].get("appointment_date"):
                                        self.call_data.selected_appointment_date = available_slots[0]["appointment_date"]
                                        print(f"[DEBUG] Stored appointment_date: {self.call_data.selected_appointment_date}")
                            except:
                                result = response_text
                            
                            # Only return success if we have slots
                            if available_slots and len(available_slots) > 0:
                                success_msg = LANGUAGE_TEXTS["desired_slot_success"].get(
                                    current_lang, LANGUAGE_TEXTS["desired_slot_success"]["no"]
                                )
                                return {
                                    "suksess": True,
                                    "data": result,
                                    "melding": success_msg
                                }
                            else:
                                no_availability_msg = LANGUAGE_TEXTS["no_availability_date"].get(
                                    current_lang, LANGUAGE_TEXTS["no_availability_date"]["no"]
                                ).format(date=OnsketDato)
                                return {
                                    "suksess": False,
                                    "data": result,
                                    "melding": no_availability_msg
                                }
                        elif response.status == 404:
                            # 404 might mean no availability, check response body
                            try:
                                result = json.loads(response_text)
                                available_slots = result.get("data", {}).get("available_slots", [])
                                if not available_slots or len(available_slots) == 0:
                                    no_availability_msg = LANGUAGE_TEXTS["no_availability_date"].get(
                                        current_lang, LANGUAGE_TEXTS["no_availability_date"]["no"]
                                    ).format(date=OnsketDato)
                                    return {
                                        "suksess": False,
                                        "data": result,
                                        "melding": no_availability_msg
                                    }
                            except:
                                pass
                            
                            # If it's a real 404 error, return connection error
                            error_msg = LANGUAGE_TEXTS["desired_slot_error_connection"].get(
                                current_lang, LANGUAGE_TEXTS["desired_slot_error_connection"]["no"]
                            ).format(status=str(response.status))
                            return {
                                "suksess": False,
                                "melding": error_msg
                            }
                        else:
                            error_msg = LANGUAGE_TEXTS["desired_slot_error_connection"].get(
                                current_lang, LANGUAGE_TEXTS["desired_slot_error_connection"]["no"]
                            ).format(status=str(response.status))
                            return {
                                "suksess": False,
                                "melding": error_msg
                            }
                except Exception as e:
                    error_msg = LANGUAGE_TEXTS["desired_slot_error_technical"].get(
                        current_lang, LANGUAGE_TEXTS["desired_slot_error_technical"]["no"]
                    )
                    return {
                        "suksess": False,
                        "melding": error_msg
                    }
            
        finally:
            # Avbryt oppdaterings-tasken
            if update_task:
                update_task.cancel()
                try:
                    await update_task
                except asyncio.CancelledError:
                    pass
    @function_tool()
    async def book_time(
        self, context: RunContext, 
        personnr: str,
        Fornavn: str, 
        Etternavn: str,
        mobilnr: str,
        ClinicIDForValgtTime: str,
        TreatmentIDForValgtTime: str,
        ClinicianIDForValgtTime: str,        
        StartTid: str,
        SluttTid: str,
        Dato: str = "",
        ):
        """Brukes for å booke en time for pasienten. Dato parameter er påkrevd og skal være i formatet DD/MM/YYYY (f.eks. 05/12/2025)."""
        
        # Determine current language (default to Norwegian)
        current_lang = "no"
        if self.call_data and getattr(self.call_data, "language", None) in ("no", "en"):
            current_lang = self.call_data.language

        # Use collected personnummer if available, otherwise collect via DTMF
        if self.call_data and self.call_data.collected_personnummer:
            personnr = self.call_data.collected_personnummer
        else:
            result = await self.samle_personnummer_med_dtmf(context)
            error_msg_no = LANGUAGE_TEXTS["personnummer_collection_failed"]["no"]
            error_msg_en = LANGUAGE_TEXTS["personnummer_collection_failed"]["en"]
            if result == error_msg_no or result == error_msg_en:
                error_instruction = LANGUAGE_TEXTS["personnummer_collection_error"].get(
                    current_lang, LANGUAGE_TEXTS["personnummer_collection_error"]["no"]
                )
                return {
                    "suksess": False,
                    "melding": error_instruction
                }
            personnr = self.call_data.collected_personnummer
        
        # Use helper method to get phone number if not provided
        mobilnr = self.get_phone_number_for_booking()
        
        # Get appointment date - use parameter if provided, otherwise use stored date from call_data
        if not Dato and self.call_data and self.call_data.selected_appointment_date:
            Dato = self.call_data.selected_appointment_date
        
        # Validate that Dato is provided
        if not Dato:
            if current_lang == "en":
                error_msg = "Missing required field: Dato (appointment date). Please provide the date in DD/MM/YYYY format."
            else:
                error_msg = "Mangler påkrevd felt: Dato (avtaledato). Vennligst oppgi datoen i formatet DD/MM/YYYY."
            return {
                "suksess": False,
                "melding": error_msg
            }
        
        #Opprett en task som gir periodiske oppdateringer
        update_task = None

        async def periodic_updates():
            """Gir brukeren oppdateringer hvert 2-3.5 sekund"""
            update_messages = LANGUAGE_TEXTS["booking_updates"].get(
                current_lang, LANGUAGE_TEXTS["booking_updates"]["no"]
            )
            message_index = 0

            await asyncio.sleep(3.0)

            while True:
                try:
                    await context.session.say(
                        update_messages[message_index],
                        allow_interruptions=False
                    )
                    message_index = (message_index + 1) % len(update_messages)
                    await asyncio.sleep(random.uniform(2.0, 3.5))
                except asyncio.CancelledError:
                    break
                except Exception:
                    #Hvis noe går galt, bare avslutt
                    break

        try:
            update_task = asyncio.create_task(periodic_updates())

            await context.session.say(
                LANGUAGE_TEXTS["booking_intro"].get(
                    current_lang, LANGUAGE_TEXTS["booking_intro"]["no"]
                ),
                allow_interruptions=False
            )
            
            #hent webhook url fra konfigurasjonen
            webhook_url = BOOK_TIME_URL
            
            # Forbered data for HTTP POST request
            data = {
                "personnr": personnr,
                "Fornavn": Fornavn,
                "Etternavn": Etternavn,
                "mobilnr": mobilnr,
                "ClinicIDForValgtTime": ClinicIDForValgtTime,
                "TreatmentIDForValgtTime": TreatmentIDForValgtTime,
                "ClinicianIDForValgtTime": ClinicianIDForValgtTime,
                "StartTid": StartTid,
                "SluttTid": SluttTid,
                "Dato": Dato
            }
            data.update(self.booking_config)
            
            # Log webhook payload
            print(f"[WEBHOOK] book_time")
            print(f"[WEBHOOK] URL: {webhook_url}")
            print(f"[WEBHOOK] Payload: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # Send HTTP POST request
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(webhook_url, json=data) as response:
                        response_text = await response.text()
                        print(f"[WEBHOOK] Response Status: {response.status}")
                        print(f"[WEBHOOK] Response Body: {response_text}")
                        
                        if response.status == 200:
                            try:
                                result = json.loads(response_text)
                                print(f"[WEBHOOK] Response JSON: {json.dumps(result, indent=2, ensure_ascii=False)}")
                            except:
                                result = response_text
                            
                            if self.call_data:
                                self.call_data.appointment_booked = True
                            success_msg = LANGUAGE_TEXTS["booking_success"].get(
                                current_lang, LANGUAGE_TEXTS["booking_success"]["no"]
                            ).format(name=Fornavn)
                            return {
                                "suksess": True,
                                "data": result,
                                "melding": success_msg
                            }
                        else:
                            error_msg = LANGUAGE_TEXTS["booking_error_connection"].get(
                                current_lang, LANGUAGE_TEXTS["booking_error_connection"]["no"]
                            ).format(status=str(response.status))
                            return {
                                "suksess": False,
                                "melding": error_msg
                            }
                except Exception as e:
                    error_msg = LANGUAGE_TEXTS["booking_error_technical"].get(
                        current_lang, LANGUAGE_TEXTS["booking_error_technical"]["no"]
                    )
                    return {
                        "suksess": False,
                        "melding": error_msg
                    }
            
        finally:
            # Avbryt oppdaterings-tasken
            if update_task:
                update_task.cancel()
                try:
                    await update_task
                except asyncio.CancelledError:
                    pass

    @function_tool()
    async def videresend_til_menneske(
        self, 
        context: RunContext,
        grunn: str
    ):
        """Videresender samtalen til et menneske"""
        
        ekstern_nummer = clinic_settings.get('ekstern_behandler')
        sip_trunk_id = os.getenv('SIP_TRUNK_ID')
        
        if not ekstern_nummer or not sip_trunk_id:
            await context.session.say(
                "Beklager, kan ikke videresende akkurat nå. La meg ta en beskjed.",
                allow_interruptions=False
            )
            return {"suksess": False, "melding": "Videresending ikke tilgjengelig"}
        
        try:
            await context.session.say(
                "Setter deg over nå.",
                allow_interruptions=False
            )
            
            await self.job_context.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=sip_trunk_id,
                    sip_call_to=ekstern_nummer,
                    room_name=self.job_context.room.name,
                    participant_identity=f"transfer_{datetime.now().timestamp()}"
                )
            )
            
            return {"suksess": True}
            
        except:
            await context.session.say(
                "Videresending feilet. La meg heller ta en beskjed.",
                allow_interruptions=False
            )
            return {"suksess": False, "melding": "Videresending feilet"}

    @function_tool()
    async def legg_igjen_beskjed(
        self, 
        context: RunContext,
        sammendrag: str = "",
        telefonnummer: str = ""
    ):
        """Legger igjen beskjed til klinikkens ansatte når agenten ikke kan hjelpe kunden videre. Hvis sammendrag ikke er oppgitt, vil funksjonen be kunden om å si beskjeden direkte."""
        
        # Determine current language
        current_lang = "no"
        if self.call_data and getattr(self.call_data, "language", None) in ("no", "en"):
            current_lang = self.call_data.language
        
        # Check and collect phone number if not available
        if not telefonnummer:
            telefonnummer = self.get_phone_number_for_booking()
            # If still no phone number, collect it via DTMF
            if not telefonnummer or telefonnummer == "Telefonnummer ikke tilgjengelig":
                await self.samle_telefonnummer_med_dtmf(context)
                telefonnummer = self.get_phone_number_for_booking()
        
        # Extract first name and last name from conversation if available
        fornavn_clean = ""
        etternavn_clean = ""
        
        # Try to extract name from conversation messages
        if self.call_data and self.call_data.conversation_messages:
            for msg in reversed(self.call_data.conversation_messages):
                content = msg.get("content", "").lower()
                # Look for patterns like "my name is X" or "jeg heter X"
                if "name is" in content or "heter" in content or "mitt navn" in content:
                    # Try to extract name (simplified - could be improved)
                    parts = content.split()
                    for i, part in enumerate(parts):
                        if part in ["is", "heter", "navn"] and i + 1 < len(parts):
                            name_parts = parts[i+1:i+3]  # Get next 1-2 words as name
                            if len(name_parts) >= 1:
                                fornavn_clean = name_parts[0].capitalize()
                            if len(name_parts) >= 2:
                                etternavn_clean = name_parts[1].capitalize()
                            break
                    if fornavn_clean:
                        break
        
        # If name is not found, ask for it
        if not fornavn_clean:
            max_retries = 2
            for attempt in range(max_retries):
                # Ask for name
                name_prompt = LANGUAGE_TEXTS["leave_message_name_prompt"].get(
                    current_lang, LANGUAGE_TEXTS["leave_message_name_prompt"]["no"]
                )
                await context.session.say(name_prompt, allow_interruptions=True)
                
                # Wait for user input
                await asyncio.sleep(2.5)  # Give user time to speak
                
                # Try to get the latest user message from conversation
                if self.call_data and self.call_data.conversation_messages:
                    user_messages = [msg for msg in self.call_data.conversation_messages if msg.get("role") == "user"]
                    if user_messages:
                        latest_message = user_messages[-1].get("content", "").strip()
                        # Try to extract name from the latest message
                        if latest_message:
                            # Simple extraction: take first 1-2 words as name
                            name_parts = latest_message.split()[:2]
                            if len(name_parts) >= 1:
                                fornavn_clean = name_parts[0].capitalize()
                            if len(name_parts) >= 2:
                                etternavn_clean = name_parts[1].capitalize()
                
                # If we got a name, confirm and break
                if fornavn_clean:
                    confirm_msg = LANGUAGE_TEXTS["leave_message_name_confirm"].get(
                        current_lang, LANGUAGE_TEXTS["leave_message_name_confirm"]["no"]
                    ).format(name=fornavn_clean)
                    await context.session.say(confirm_msg, allow_interruptions=False)
                    break
                elif attempt < max_retries - 1:
                    # Retry
                    retry_msg = LANGUAGE_TEXTS["leave_message_name_retry"].get(
                        current_lang, LANGUAGE_TEXTS["leave_message_name_retry"]["no"]
                    )
                    await context.session.say(retry_msg, allow_interruptions=True)
                    await asyncio.sleep(2.5)
        
        # If sammendrag is not provided, capture it from the customer
        summary_value = sammendrag
        if not summary_value or summary_value.strip() == "":
            # Ask customer to provide the message
            prompt_msg = LANGUAGE_TEXTS["leave_message_prompt"].get(
                current_lang, LANGUAGE_TEXTS["leave_message_prompt"]["no"]
            )
            await context.session.say(prompt_msg, allow_interruptions=True)
            
            # Wait for user input - simple approach: wait a bit and check conversation messages
            await asyncio.sleep(2.0)  # Give user time to speak
            
            # Try to get the latest user message from conversation
            if self.call_data and self.call_data.conversation_messages:
                # Get the most recent user message
                user_messages = [msg for msg in self.call_data.conversation_messages if msg.get("role") == "user"]
                if user_messages:
                    summary_value = user_messages[-1].get("content", "")
            
            # If still no message, use a default
            if not summary_value or summary_value.strip() == "":
                if current_lang == "en":
                    summary_value = "Customer requested assistance but message was not captured."
                else:
                    summary_value = "Kunde ba om hjelp men beskjeden ble ikke fanget opp."
        
        # Opprett en task som gir periodiske oppdateringer
        update_task = None
        
        async def periodic_updates():
            """Gir brukeren oppdateringer hvert 3. sekund"""
            update_messages = LANGUAGE_TEXTS["leave_message_updates"].get(
                current_lang, LANGUAGE_TEXTS["leave_message_updates"]["no"]
            )
            message_index = 0
            
            await asyncio.sleep(3.0)
            
            while True:
                try:
                    await context.session.say(
                        update_messages[message_index],
                        allow_interruptions=False
                    )
                    message_index = (message_index + 1) % len(update_messages)
                    await asyncio.sleep(3.0)
                except asyncio.CancelledError:
                    break
                except Exception:
                    # Hvis noe går galt, bare avslutt
                    break
        
        try:
            update_task = asyncio.create_task(periodic_updates())
            
            intro_msg = LANGUAGE_TEXTS["leave_message_intro"].get(
                current_lang, LANGUAGE_TEXTS["leave_message_intro"]["no"]
            )
            await context.session.say(intro_msg, allow_interruptions=False)
            
            # hent webhook url fra konfigurasjonen
            webhook_url = LEGG_IGJEN_BESKJED_URL
            
            # Forbered data for HTTP POST request with new structure
            other_info = f"Samtale fra {self.clinic_name} Tannklinikk"
            data = {
                "Summary": summary_value,
                "CustomerNumber": telefonnummer,
                "OtherInfo": other_info,
                "StartTime": "",
                "EndTime": "",
                "TreatmentID": "",
                "ClinicianID": "",
                "ClinicID": self.booking_config.get("ClinicID", ""),
                "FirstName": fornavn_clean,
                "LastName": etternavn_clean,
            }
            data.update(self.booking_config)
            
            # Log webhook payload
            print(f"[WEBHOOK] legg_igjen_beskjed")
            print(f"[WEBHOOK] URL: {webhook_url}")
            print(f"[WEBHOOK] Payload: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # Send HTTP POST request
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(webhook_url, json=data) as response:
                        response_text = await response.text()
                        print(f"[WEBHOOK] Response Status: {response.status}")
                        print(f"[WEBHOOK] Response Body: {response_text}")
                        
                        if response.status == 200:
                            try:
                                result = json.loads(response_text)
                                print(f"[WEBHOOK] Response JSON: {json.dumps(result, indent=2, ensure_ascii=False)}")
                            except:
                                result = response_text
                            
                            # Mark in call data that message was left
                            if self.call_data:
                                self.call_data.conversation_messages.append({
                                    "role": "system",
                                    "content": f"Beskjed lagt igjen til ansatte: {summary_value}"
                                })
                            
                            success_msg = LANGUAGE_TEXTS["leave_message_success"].get(
                                current_lang, LANGUAGE_TEXTS["leave_message_success"]["no"]
                            )
                            return {
                                "suksess": True,
                                "melding": success_msg
                            }
                        else:
                            error_msg = LANGUAGE_TEXTS["leave_message_error"].get(
                                current_lang, LANGUAGE_TEXTS["leave_message_error"]["no"]
                            ).format(status=str(response.status))
                            return {
                                "suksess": False,
                                "melding": error_msg
                            }
                except Exception as e:
                    print(f"[WEBHOOK] Exception: {str(e)}")
                    error_msg = LANGUAGE_TEXTS["leave_message_technical_error"].get(
                        current_lang, LANGUAGE_TEXTS["leave_message_technical_error"]["no"]
                    )
                    return {
                        "suksess": False,
                        "melding": error_msg
                    }
                    
        finally:
            # Avbryt oppdaterings-tasken
            if update_task:
                update_task.cancel()
                try:
                    await update_task
                except asyncio.CancelledError:
                    pass
    
    @function_tool()
    async def sett_sprak(
        self,
        context: RunContext,
        sprak: str,
    ) -> str:
        """
        Setter samtalespraket til norsk eller engelsk.
        
        Parametere:
        - sprak: "no" for norsk eller "en" for engelsk
        """
        if not self.call_data:
            return "Call data ikke tilgjengelig"
        
        if sprak.lower() in ("no", "nb", "nn", "norsk", "norwegian"):
            self.call_data.language = "no"
            return "Sprak satt til norsk. Fortsett på norsk."
        elif sprak.lower() in ("en", "english", "engelsk"):
            self.call_data.language = "en"
            return "Language set to English. Continue in English."
        else:
            return f"Ugyldig sprak: {sprak}. Bruk 'no' eller 'en'."
    
    @function_tool()
    async def hent_telefonnummer_fra_samtale(
        self,
        context: RunContext,
        note: str = "",
    ) -> str:
        """
        Henter telefonnummeret som kunden ringer fra.

        Parametere:
        - note: Valgfri tekst som kan brukes av modellen for egen notatføring.
        """
        # Primært: bruk nummeret kunden ringer fra (lagret i call_data)
        if self.call_data and self.call_data.phone_number:
            return self.call_data.phone_number

        # Sekundært: bruk klinikkens konfigurerte nummer hvis tilgjengelig
        global clinic_settings
        if clinic_settings and isinstance(clinic_settings, dict):
            fallback_number = clinic_settings.get("phone_number")
            if fallback_number:
                return fallback_number

        return "Telefonnummer ikke tilgjengelig"
    
    @function_tool()
    async def samle_personnummer_med_dtmf(
        self, 
        context: RunContext,
        note: str = "",
    ) -> str:
        """
        Samler personnummer via DTMF (tastetrykk) for sikker og nøyaktig innhenting.

        Parametere:
        - note: Valgfri tekst som kan brukes av modellen for egen notatføring.
        """

        # --- CONSOLE MODE SHORTCUT: use static personnummer instead of DTMF ---
        # Enable by setting CONSOLE_MODE=true in .env when running via console.
        console_mode_val = os.getenv("CONSOLE_MODE", "").strip().lower()
        console_mode = console_mode_val in ("true", "1", "yes", "on")
        
        # Debug logging (can be removed in production)
        if console_mode_val:
            print(f"[DEBUG] CONSOLE_MODE detected: '{console_mode_val}' -> {console_mode}")
        
        if console_mode:
            if not self.call_data:
                raise ValueError("No call data available for static personnummer")

            # Static personal number for console testing
            static_personnr = os.getenv("STATIC_PERSONNR", "01010112345").strip()
            if not static_personnr:
                static_personnr = "01010112345"  # Fallback default
            
            self.call_data.collected_personnummer = static_personnr
            print(f"[DEBUG] Using static personnummer in console mode: {static_personnr}")

            # Choose language (default Norwegian)
            lang = "no"
            if getattr(self.call_data, "language", None) in ("no", "en"):
                lang = self.call_data.language

            if lang == "en":
                msg = (
                    "Your personal ID number has been stored "
                )
            else:
                msg = (
                    "Personnummer er lagret."
                )

            await context.session.say(msg, allow_interruptions=False)
            # Return a neutral status message for the LLM
            if lang == "en":
                return "Personal ID number stored in console mode. Continue in English."
            else:
                return "Personnummer lagret i konsollmodus. Fortsett på norsk."
        # --- END CONSOLE MODE SHORTCUT ---

        # Determine current language (default to Norwegian)
        current_lang = "no"
        if self.call_data and getattr(self.call_data, "language", None) in ("no", "en"):
            current_lang = self.call_data.language

        # Check if already collected
        if self.call_data and self.call_data.collected_personnummer:
            # Return a neutral status message that the LLM can use to inform the user in the correct language
            if current_lang == "en":
                return "Personal ID number is already collected and will be used automatically. Continue in English."
            else:
                return "Personnummer er allerede samlet og vil bli brukt automatisk. Fortsett på norsk."
        
        if not self.call_data:
            raise ValueError("No call data available for DTMF collection")
        
        # Clear DTMF buffer before starting
        self.call_data.dtmf_digits.clear()
        
        # Instruct user - NO interruptions allowed
        instruction_msg = LANGUAGE_TEXTS["personnummer_dtmf_instruction"].get(
            current_lang, LANGUAGE_TEXTS["personnummer_dtmf_instruction"]["no"]
        )
        await context.session.say(instruction_msg, allow_interruptions=False)
        
        # Monitor for # character continuously
        start_time = time.time()
        while True:
            # Check timeout - stop function after 15 seconds
            if time.time() - start_time > 15:
                return LANGUAGE_TEXTS["personnummer_collection_failed"].get(
                    current_lang, LANGUAGE_TEXTS["personnummer_collection_failed"]["no"]
                )
            
            await asyncio.sleep(0.1)  # Check every 100ms
            
            # Check if # is in buffer
            if '#' in self.call_data.dtmf_digits:
                # Find index of #
                hash_index = self.call_data.dtmf_digits.index('#')
                
                # Extract digits before #
                digits_before_hash = self.call_data.dtmf_digits[:hash_index]
                
                # Get last 11 digits
                if len(digits_before_hash) >= 11:
                    personnummer = ''.join(digits_before_hash[-11:])
                    
                    if len(personnummer) == 11 and personnummer.isdigit():
                        # Confirm receipt
                        received_msg = LANGUAGE_TEXTS["personnummer_received"].get(
                            current_lang, LANGUAGE_TEXTS["personnummer_received"]["no"]
                        ).format(last_four=personnummer[-4:])
                        await context.session.say(received_msg, allow_interruptions=False)
                        self.call_data.collected_personnummer = personnummer
                        # Return a neutral status message
                        if current_lang == "en":
                            return "Personal ID number collected successfully. Continue in English."
                        else:
                            return "Personnummer samlet. Fortsett på norsk."
                
                # Invalid input - retry
                self.call_data.dtmf_digits.clear()
                retry_msg = LANGUAGE_TEXTS["personnummer_retry"].get(
                    current_lang, LANGUAGE_TEXTS["personnummer_retry"]["no"]
                )
                await context.session.say(retry_msg, allow_interruptions=False)

    @function_tool()
    async def samle_telefonnummer_med_dtmf(
        self,
        context: RunContext,
        note: str = "",
    ) -> str:
        """
        Samler telefonnummer via DTMF (tastetrykk) når kunde ønsker å bruke annet nummer.

        Parametere:
        - note: Valgfri tekst som kan brukes av modellen for egen notatføring.
        """
        
        # Determine current language (default to Norwegian)
        current_lang = "no"
        if self.call_data and getattr(self.call_data, "language", None) in ("no", "en"):
            current_lang = self.call_data.language
        
        if not self.call_data:
            raise ValueError("No call data available")
        
        # Clear DTMF buffer before starting
        self.call_data.dtmf_digits.clear()
        
        # Instruct user - NO interruptions allowed
        instruction_msg = LANGUAGE_TEXTS["phone_number_dtmf_instruction"].get(
            current_lang, LANGUAGE_TEXTS["phone_number_dtmf_instruction"]["no"]
        )
        await context.session.say(instruction_msg, allow_interruptions=False)
        
        # Set timeout for fallback
        timeout_seconds = 20
        start_time = asyncio.get_event_loop().time()
        
        # Monitor for # character continuously
        while True:
            await asyncio.sleep(0.1)  # Check every 100ms
            
            # Check timeout
            if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                timeout_msg = LANGUAGE_TEXTS["phone_number_timeout"].get(
                    current_lang, LANGUAGE_TEXTS["phone_number_timeout"]["no"]
                )
                await context.session.say(timeout_msg, allow_interruptions=False)
                return LANGUAGE_TEXTS["phone_number_timeout_return"].get(
                    current_lang, LANGUAGE_TEXTS["phone_number_timeout_return"]["no"]
                )
            
            # Check if # is in buffer
            if '#' in self.call_data.dtmf_digits:
                # Find index of #
                hash_index = self.call_data.dtmf_digits.index('#')
                
                # Extract digits before #
                digits_before_hash = self.call_data.dtmf_digits[:hash_index]
                
                # Get last 8 digits
                if len(digits_before_hash) >= 8:
                    phone_digits = ''.join(digits_before_hash[-8:])
                    
                    if len(phone_digits) == 8 and phone_digits.isdigit():
                        # Add + prefix for Norwegian number
                        phone_number = f"+47{phone_digits}"
                        
                        # Confirm receipt
                        received_msg = LANGUAGE_TEXTS["phone_number_received"].get(
                            current_lang, LANGUAGE_TEXTS["phone_number_received"]["no"]
                        ).format(last_four=phone_digits[-4:])
                        await context.session.say(received_msg, allow_interruptions=False)
                        
                        # Store in call_data for reuse
                        self.call_data.alternative_phone_number = phone_number
                        stored_msg = LANGUAGE_TEXTS["phone_number_stored"].get(
                            current_lang, LANGUAGE_TEXTS["phone_number_stored"]["no"]
                        ).format(number=phone_number)
                        return stored_msg
                
                # Invalid input - retry
                self.call_data.dtmf_digits.clear()
                retry_msg = LANGUAGE_TEXTS["phone_number_retry"].get(
                    current_lang, LANGUAGE_TEXTS["phone_number_retry"]["no"]
                )
                await context.session.say(retry_msg, allow_interruptions=False)


    def get_phone_number_for_booking(self) -> str:
        """Get the appropriate phone number for booking - alternative or calling number"""
        if self.call_data.alternative_phone_number:
            return self.call_data.alternative_phone_number
        else:
            return self.call_data.phone_number


async def generate_conversation_summary(call_data: CallData) -> str:
    """Generate a summary of the conversation using LLM"""
    try:
        if not call_data.conversation_messages:
            return "Ingen samtale registrert."
        
        # Build conversation text from stored messages
        conversation_text = "\n".join([
            f"{msg['role'].capitalize()}: {msg['content']}"
            for msg in call_data.conversation_messages[-20:]
        ])
        
        # Import what we need
        from livekit.plugins import openai
        from livekit.agents.llm import ChatContext, ChatMessage
        
        # Create a simple LLM instance to generate the summary
        llm = openai.LLM(model="gpt-4o-mini", temperature=1)
        
        # Create chat context
        chat_ctx = ChatContext([
            ChatMessage(
                role="system",
                content=["Du er en AI som lager korte sammendrag av tannklinikk-samtaler. VIKTIG: Aldri inkluder personnummer, navn eller telefonnummer."]
            ),
            ChatMessage(
                role="user", 
                content=[f"Lag et kort sammendrag (1-2 setninger) av denne samtalen. Fokuser på hva kunden spurte om:\n\n{conversation_text}"]
            )
        ])
        
        # Generate summary using chat
        response = ""
        async with llm.chat(chat_ctx=chat_ctx) as stream:
            async for chunk in stream:
                if not chunk:
                    continue
                # Extract content from chunk - samme mønster som i eksemplet
                content = getattr(chunk.delta, 'content', None) if hasattr(chunk, 'delta') else str(chunk)
                if content:
                    response += content
        
        summary = response.strip()
        return summary
        
    except Exception as e:
        return "Kunne ikke generere sammendrag av samtalen."


def extract_phone_from_room_name(room_name: str) -> Optional[str]:
    """Extract phone number from room name format like _+4747788636_FccScBRpKxpE"""
    if room_name.startswith('_+'):
        parts = room_name.split('_')
        if len(parts) >= 2:
            return parts[1]  # Returns '+4747788636'
    return None


def format_conversation_history(history: Dict[str, Any]) -> str:
    """Format conversation history into natural language context"""
    if not history:
        return ""
    
    sorted_calls = sorted(history.items(), key=lambda x: x[0], reverse=True)
    
    context_parts = []
    context_parts.append("VIKTIG INFORMASJON: Du har følgende historikk fra tidligere samtaler med denne kunden som ringer inn nå.")
    context_parts.append("Dette er sammendrag av tidligere samtaler, IKKE den pågående samtalen:")
    context_parts.append("")
    
    for timestamp_key, call_data in sorted_calls:
        date_str = timestamp_key[:10]
        time_str = timestamp_key[11:].replace('-', ':')
        
        summary = call_data.get('Kort sammendrag', 'Ingen sammendrag')
        booked = "Ja" if call_data.get('Time booket?') else "Nei"
        
        context_parts.append(
            f"- {date_str} kl {time_str}: {summary} (Time booket: {booked})"
        )
    
    context_parts.append("\nBruk denne informasjonen til å gi personlig og tilpasset service til kunden.")
    return "\n".join(context_parts)



async def entrypoint(ctx: agents.JobContext):
    # Fetch clinic settings at startup
    
    # Debug: Check if CONSOLE_MODE is loaded
    console_mode_debug = os.getenv("CONSOLE_MODE", "NOT_SET")
    static_personnr_debug = os.getenv("STATIC_PERSONNR", "NOT_SET")
    print(f"[DEBUG] Environment check - CONSOLE_MODE: '{console_mode_debug}', STATIC_PERSONNR: '{static_personnr_debug}'")
    
    phone_number = extract_phone_from_room_name(ctx.room.name)
    if not phone_number:
        phone_number = "+4723507256"
        
    global clinic_settings
    try:
        clinic_settings = {
        "clinic_id": "clinic_001",
        "clinic_name": "Oslo Tannklinikk",
        "business_name": "Oslo Tannklinikk",
        "business_type": "clinic",
        "phone_number": "+4723507256",
        "agent_navn": "Emma",
        "active_persona": "ANBEFALT",
        "voice": {
            "id": "b3jcIbyC3BSnaRu8avEk",
            "stability": 0.5,
            "similarity_boost": 0.75,
            "speed": 1.0
        },
        "stt_model": "gpt-4o-transcribe",
        "llm_model": "gpt-4.1",
        "stt_prompt": "This is a conversation between an AI receptionist for a dental clinic and a patient or potential patient regarding appointment booking and questions. The conversation can be in either Norwegian or English. Transcribe accurately in the language being spoken with correct punctuation and formatting. If the user is speaking Norwegian, transcribe in Norwegian. If the user is speaking English, transcribe in English. Detect the language automatically and transcribe accordingly.",
        "service_name": "appointment",
        "service_name_plural": "appointments",
        "booking_term": "booking",
        "bookingkonfigurasjoner": {},
        "klinikk_informasjon": {},
        "business_info": """Grünerløkkas Hus Tannlegesenter - Forretningsinformasjon
Klinikkens Oversikt
Grünerløkkas Hus Tannlegesenter er et moderne og veletablert tannlegesenter som ligger i Grünerløkka-området i Oslo, Norge. Klinikkens slogan er "din tannlege på Grünerløkka". Klinikken er sentralt plassert bare 200 meter fra trikkestoppet på Birkelunden i Oslo og ligger i øverste etasje av en bygning med heisstilgang, med panorama utsikt over hele Oslo bysentrum. Klinikken har nylig blitt utvidet og fullstendig renovert til moderne og tidsriktig standard.
Plassering og Tilgjengelighet
Klinikken er lokalisert i Grünerløkka, Oslo, Norge. Spesifikke adressedetaljer viser at den ligger 200 meter fra trikkestoppet på Birkelunden. Klinikken ligger i øverste etasje med heistilgang tilgjengelig. Gateparkering er tilgjengelig i området rundt Birkelunden. Klinikken er lett tilgjengelig via kollektivtransport inkludert trikk og busser. Plasseringen er sentral i Oslo og praktisk for pasienter i hele regionen.
Fasiliteter og Særtrekk
Klinikken har store og romslige behandlingsrom designet med moderne designprinsipper og pasientkomfort i fokus. Et rolig og behagelig venterom er tilgjengelig for pasientavslapping. En unik ekstra amenity er en 70 kvadratmeter stor takterrasse hvor pasienter kan slappe av mens de venter på timen sin. Fasiliteten gir panorama utsikt over Oslo by fra plasseringen i øverste etasje. Heistilgang sikrer tilgjengelighet for pasienter med mobilitetsutfordringer. Hele klinikken har nylig blitt renovert til moderne standard med oppdatert utstyr og systemer.
Personale
Klinikken sysselsetter et team bestående av 15 dedikerte og dyktige tannhelsefagpersoner som jobber sammen for å gi profesjonell og sikker behandling. Teamet inkluderer tannleger og en oral kirurg som tilbyr spesialiserte kirurgiske tjenester. Klinikken har omfattende erfaring innen tannlegefaget, og har behandlet flere tusen fornøyde pasienter fra hele Oslo over mange år.
Akkrediteringer og Sertifiseringer
Alle tannleger ved klinikken følger etiske retningslinjer for behandling fastsatt av Den Norske Tannlegeforeningen. Alle tannhelseprofesjonelle er godkjent av Statens Autorisasjonskontor for helsepersonell. Praksisen er anerkjent som veletablert og høyt anerkjent. Klinikken investerer kontinuerlig i oppdatert utstyr, moderne systemer og toppmodern teknologi for å tilby pasienter noe av det beste markedet har å tilby.
Tjenester som Tilbys
Klinikken tilbyr et omfattende spekter av tannlegetjenester inkludert generell tannlegebehandling med komplette sjekker (inkludert røntgen, tannrens og AirFlow-behandling), akutt tannlegebehandling for akutte problemer, Invisalign ortodontisk konsultasjon og behandling, og profesjonell tannbleking. Klinikken tilbyr også spesialisert oral kirurgisk tjeneste gjennom deres ansatte oral kirurg.
Priser
Nytt Pasient Tilbud: Komplett sjekk med røntgen, tannrens og AirFlow-behandling - 790 NOK (kun for nye pasienter)
Akutt Behandling: Fra 1150 NOK (avhengig av nødvendig behandling)
Invisalign Behandling: Inkluderer profesjonell tannbleking verdsatt til 3600 NOK
2025 Omfattende Pakke: Komplett sjekk med røntgen, tannrens, AirFlow og profesjonell tannbleking - Vanlig pris 4750 NOK
Alle priser er i NOK (Norske Kroner) og inkluderer MVA (merverdiavgift).
        """,
        "ekstern_behandler": "+4791534220",
        "enable_conversation_history": True
            }
    except Exception as e:
        clinic_settings = {}
    

    # Extract phone number from room name early
    conversation_history = None


    # Select persona based on clinic settings
    selected_persona = ANBEFALT
    
    # Get voice settings from clinic configuration
    print("am here")
    voice_config = clinic_settings.get('voice', {})
    voice_id = voice_config.get('id', 'b3jcIbyC3BSnaRu8avEk')  
    voice_stability = voice_config.get('stability', 0.5)
    voice_similarity = voice_config.get('similarity_boost', 0.75)
    voice_speed = voice_config.get('speed', 1.0)

 
    session = AgentSession(
        stt=openai.STT(
            model="gpt-4o-transcribe",
            prompt=f"""
            Dette er en samtale mellom deg (en norsk AI resepsjonist for en tannklinikk) og en norsk pasient eller potensiell pasient angående timebestilling og spørsmål. Transkriber nøyaktig på norsk med korrekt interpunksjon og formatering. I få tilfeller vil det være andre språk enn norsk, så vær klar for det, men forvent norsk.
            """
        ),
        llm=openai.LLM(
            model="gpt-4o", 
            temperature=selected_persona.get('Temperatur', 0.4)  # Default to 0.4 if not set
        ),
        tts=elevenlabs.TTS(
            voice_id=voice_id,
            model="eleven_flash_v2_5",
            voice_settings=elevenlabs.VoiceSettings(
                stability=voice_stability,
                similarity_boost=voice_similarity,
                speed=voice_speed,
            )
        ),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    # Initialize CallData for the session with phone number
    call_data = CallData(phone_number=phone_number or "")
    
    # Connect to room
    await ctx.connect()
    
    # Remove participant_connected handler - we already have phone from room name
    # No need for fallback since room name extraction is reliable
    
    # Set up DTMF event handler for personnummer collection
    @ctx.room.on("sip_dtmf_received")
    def on_dtmf_received(dtmf_event: rtc.SipDTMF):
        """Handle DTMF digits from SIP participants"""
        # Simply store all DTMF digits received during the call
        if call_data:
            call_data.dtmf_digits.append(dtmf_event.digit)
    
    # Set up participant disconnection handler to save call log
    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant):
        """Handle participant disconnection and save call log"""
        if not participant.identity.startswith('sip_'):
            return
            

    
    booking_config = clinic_settings.get('bookingkonfigurasjoner', {})
    
    # Get persona prompt without history injection
    persona_prompt = selected_persona['Prompt']
    
    # Create agent instance with conversation_history as separate parameter
    assistant = Assistant(
        persona_prompt=persona_prompt,
        clinic_name=clinic_settings.get('clinic_name', 'Tannklinikk'),
        booking_config=booking_config,
        call_data=call_data,
        clinic_info=clinic_settings.get('klinikk_informasjon', {}),
        job_context=ctx,
        agent_name=clinic_settings.get('agent_navn'),
        conversation_history=conversation_history  # Pass as separate parameter
    )
    
    # Set up transcription handler to capture conversation
    @session.on("user_input_transcribed")
    def on_user_transcript(transcript):
        if transcript.is_final and call_data:
            call_data.conversation_messages.append({
                "role": "user",
                "content": transcript.transcript
            })
            
            # Auto-detect language from user input if not already set or on first input
            if hasattr(transcript, 'language') and transcript.language:
                # Use language from transcript if available
                detected_lang = transcript.language.lower()
                if detected_lang in ('en', 'english') and call_data.language == "no":
                    # Only auto-detect on first few messages (first 3 user messages)
                    if len([m for m in call_data.conversation_messages if m.get('role') == 'user']) <= 3:
                        call_data.language = "en"
                        print(f"[LANGUAGE] Auto-detected English from user input, updated call_data.language to 'en'")
                elif detected_lang in ('no', 'nb', 'nn', 'norwegian') and call_data.language == "en":
                    # Only auto-detect on first few messages
                    if len([m for m in call_data.conversation_messages if m.get('role') == 'user']) <= 3:
                        call_data.language = "no"
                        print(f"[LANGUAGE] Auto-detected Norwegian from user input, updated call_data.language to 'no'")
    room_options=room_io.RoomOptions(
    video_input=True,
    audio_input=room_io.AudioInputOptions(
        noise_cancellation=noise_cancellation.BVC(),
    ),
    text_output=room_io.TextOutputOptions(
        sync_transcription=False,
    ),
    participant_identity="user_123",
)
    await session.start(
        room=ctx.room,
        agent=assistant,
        room_options=room_options
    )
    
    
    await session.generate_reply(
        instructions=f"Hils på kunden og tilby hjelp fra {clinic_settings.get('clinic_name')} Tannklinikk. Som en AI Resepsjonist. Eksempel: Hei jeg heter {clinic_settings.get('agent_navn')} og er en Ai resepsjonist for {clinic_settings.get('clinic_name')}. Hva kan jeg hjelpe deg med?"
    )


if __name__ == "__main__":
    # Get agent name from environment variable
    agent_name = os.getenv('AGENT_NAME', 'DefaultAgent')
    
    agents.cli.run_app(agents.WorkerOptions(
        entrypoint_fnc=entrypoint,
        initialize_process_timeout=60.0, # Økt til 60 sekunder for multilingual modell

        # agent_name is required for explicit dispatch
        agent_name=agent_name
    ))


