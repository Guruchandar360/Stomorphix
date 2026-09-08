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
    count = result["stomata_count"]
    summary = result.get("summary") or {}
    if summary.get("completed_images"):
        return (
            f"I analyzed {summary['completed_images']} images and detected {count} stomata in total, "
            f"averaging {summary['avg_stomata_per_image']} per image. Review the annotated images "
            "before using the counts."
        )
    return (
        f"I detected {count} stomata at confidence {result['confidence']:.2f}. "
        "The green outlines mark the segmentation masks used for this count. "
        "Review the annotated image and use Edit Detections to correct any missed or incorrect stomata."
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

    batch_context = ""
    if result.get("summary", {}).get("completed_images"):
        batch_context = (
            f"- Images analyzed: {result['summary']['completed_images']}\n"
            f"- Average count per image: {result['summary']['avg_stomata_per_image']}\n"
        )
    system_prompt = (
        "You are a careful stomata counting assistant. "
        "Discuss only the detection count and annotation review; do not infer sizes, shapes, "
        "plant health, physiological state, or biological significance from this result.\n"
        f"- Stomata count: {result['stomata_count']}\n"
        f"{batch_context}"
        f"- Confidence threshold: {result['confidence']}\n"
        f"- IoU threshold: {result['iou']}\n"
        f"- Acquisition magnification: {result.get('magnification', 40)}x\n\n"
        "Provide one complete, concise sentence reporting the count and reminding the user to review the annotation."
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
