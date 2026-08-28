import os
import json
import urllib.request
import urllib.error
import asyncio
from pathlib import Path

# Helper to load .env files manually without external dependencies
def load_env_file():
    possible_paths = [
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[3] / ".env",
        Path(__file__).resolve().parents[4] / ".env",
    ]
    for path in possible_paths:
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                                val = val[1:-1]
                            os.environ[key] = val
            except Exception:
                pass

# Load environment variables on start
load_env_file()

def deterministic_explanation(result):
    summary = result["summary"]
    count = result["stomata_count"]
    calibrated = bool(result.get("is_calibrated", False))
    magnification = int(result.get("magnification", 400))
    suffix = "µm" if calibrated else "px"
    area_suffix = "µm²" if calibrated else "px²"
    key_suffix = "um" if calibrated else "px"
    avg_perim = summary.get(f"avg_perimeter_{key_suffix}", "N/A")
    calibration_note = (
        f"Physical values use the supplied calibration of {result['microns_per_pixel']} µm per pixel."
        if calibrated
        else f"Values are reported in pixels because {magnification}x optical magnification is not a pixel-to-µm conversion factor."
    )
    return (
        f"I detected {count} stomata at confidence {result['confidence']:.2f}. "
        f"The average length is {summary[f'avg_length_{key_suffix}']} {suffix}, average width is "
        f"{summary[f'avg_width_{key_suffix}']} {suffix}, average area is "
        f"{summary[f'avg_area_{key_suffix}2']} {area_suffix}, and average perimeter is "
        f"{avg_perim} {suffix}. {calibration_note} "
        "The green equivalent ellipses show orientation-independent major and minor axes, "
        "while the blue outlines follow the predicted segmentation masks."
    )

def query_llm_sync(api_key: str, system_prompt: str, user_instruction: str) -> str:
    # Determine the model and service based on key prefix
    is_gemini = api_key.startswith("AIzaSy")

    if is_gemini:
        # Google Gemini API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        
        # Combine system prompt and user instructions for Gemini
        full_text = system_prompt
        if user_instruction:
            full_text += f"\n\nUser Question/Instruction:\n{user_instruction}"
            
        data = {
            "contents": [{
                "parts": [{
                    "text": full_text
                }]
            }],
            "generationConfig": {
                "maxOutputTokens": 250,
                "temperature": 0.2
            }
        }
    else:
        # OpenAI API
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        if user_instruction:
            messages.append({"role": "user", "content": user_instruction})
        else:
            messages.append({"role": "user", "content": "Provide a brief description of these results."})
            
        data = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": messages,
            "max_tokens": 250,
            "temperature": 0.2
        }

    req_body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers=headers, method="POST")
    
    with urllib.request.urlopen(req, timeout=15) as response:
        resp_data = json.loads(response.read().decode("utf-8"))
        if is_gemini:
            return resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            return resp_data["choices"][0]["message"]["content"].strip()


async def build_explanation(result, prompt=None):
    # Retrieve API keys securely from the backend environment variables
    key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return deterministic_explanation(result)

    summary = result["summary"]
    calibrated = bool(result.get("is_calibrated", False))
    magnification = int(result.get("magnification", 400))
    key_suffix = "um" if calibrated else "px"
    length_unit = "µm" if calibrated else "pixels"
    area_unit = "µm²" if calibrated else "pixels²"
    calibration_description = (
        f"{result['microns_per_pixel']} µm/pixel"
        if calibrated
        else f"uncalibrated; report pixels only ({magnification}x is acquisition magnification, not a conversion factor)"
    )
    system_prompt = (
        "You are an expert plant morphometry assistant. "
        "Analyze these leaf imprint stomata segmentation metrics:\n"
        f"- Stomata count: {result['stomata_count']}\n"
        f"- Confidence threshold: {result['confidence']}\n"
        f"- Calibration: {calibration_description}\n"
        f"- Avg area: {summary[f'avg_area_{key_suffix}2']} {area_unit}\n"
        f"- Avg length: {summary[f'avg_length_{key_suffix}']} {length_unit}\n"
        f"- Avg width: {summary[f'avg_width_{key_suffix}']} {length_unit}\n"
        f"- Avg perimeter: {summary.get(f'avg_perimeter_{key_suffix}', 'N/A')} {length_unit}\n\n"
        "Provide a concise summary of these findings. Be direct and scientific."
    )

    try:
        # Run synchronous request in a separate thread so it doesn't block the async event loop
        explanation = await asyncio.to_thread(query_llm_sync, key, system_prompt, prompt)
        if len(explanation.split()) < 8:
            return deterministic_explanation(result)
        return explanation
    except Exception:
        # Keep provider and network errors out of the user-facing scientific result.
        return deterministic_explanation(result)
