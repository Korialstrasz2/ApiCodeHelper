# programming_helper_api.py
from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from typing import Deque, Dict, List, Tuple, Union

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - environment without requests
    requests = None

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - environment without openai
    OpenAI = None

# Reuse your shared state & utils exactly like your current endpoint
from .GLOBALS_AND_WORKING import LOCK, CONVERSATIONS
from .chatbot_utils import _conversation_key, _conversation_dump
from .models import Persona

log = logging.getLogger("custom")

# ——— Config & Models ———
# Default persona id used when none is specified
PROGRAMMING_HELPER_PERSONA_ID = -42042

CONTEXT_STANDARD = 2500
CONTEXT_ASSISTANT = 10000

# Ollama
OLLAMA_QWEN_BASE = "qwen3:8b"
OLLAMA_MISTRAL = "mistral"
OLLAMA_QWEN_14 = "huihui_ai/qwen2.5-abliterate:14b"

# Mistral
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL_S = "mistral-small-latest"
MISTRAL_MODEL_M = "mistral-medium-latest"
MISTRAL_MODEL_L = "mistral-large-latest"
MISTRAL_MODEL_R = "magistral-medium-latest"

# OpenAI (Responses API)
OPENAI_MODEL_S = "gpt-5-mini"
OPENAI_MODEL_L = "gpt-5-chat-latest"
OPENAI_MODEL_R = "gpt-5"

DEFAULT_VERBOSITY = "medium"
VERBOSITY_VALUES = {"low", "medium", "high"}

# OpenRouter
OPENROUTER_BASE_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL_S    = "mistralai/mistral-small-3.2-24b-instruct"
OPENROUTER_MODEL_M    = "thedrummer/anubis-70b-v1.1"
OPENROUTER_MODEL_L    = "deepseek/deepseek-chat-v3-0324"


# ——— System prompt ———
PROGRAMMING_HELPER_SYSTEM = """
You are **Programming Helper**, a senior software engineer and ruthless code reviewer.
Be pragmatic, precise, and *useful*. Favor actionable fixes over theory.

## Language
- Default to the **user’s language** (Italian/English) unless `lang` is specified.
- Keep tone professional, concise, and direct.

## How to answer
1) If code is provided: 
   - Briefly summarize what it does (1–2 lines).
   - Identify the likely issue(s) or design smells.
   - Propose the **minimal** fix first; then list alternatives (with trade-offs).
   - Provide **runnable code** or **unified diffs** in fenced blocks.
   - Include imports and any required config.
2) If the ask is ambiguous:
   - Ask **at most 1–2 clarifying questions** *only if* they block progress.
   - Otherwise, state assumptions and proceed.
3) When changing files:
   - Prefer `diff` format (unified) or a full updated file in one block.
4) Testing & safety:
   - Include a quick test or command to verify the fix (pytest, curl, CLI, etc.).
   - Warn about destructive commands. Never fabricate results.

## Formatting
- Use markdown. Label code fences with the language (```python, ```js, ```diff).
- Use short paragraphs and bullet points. No fluff.

## Limits
- If you don’t know, say so and suggest how to find out.
- Don’t hallucinate APIs or versions; call them out as *assumptions* if uncertain.
""".strip()


# ——— Helpers ———
def _build_messages(history: Deque[Tuple[str, str]], system_prompt: str) -> List[Dict[str, str]]:
    msgs = [{"role": "system", "content": system_prompt}]
    for role, text in history:
        msgs.append({"role": role, "content": text})
    return msgs


def _assemble_code_context(snippets: List[Dict[str, str]] | None, project_context: str | None, max_chars: int = 12000) -> str:
    """
    Build an auxiliary context block from user-provided code snippets.
    snippets: [{ "filename": "...", "language": "python|js|...", "content": "..." }, ...]
    Returns a string to prepend to the System prompt (kept separate from the user message).
    """
    if not snippets and not project_context:
        return ""

    parts: List[str] = []
    if project_context:
        parts.append("Project context:\n" + project_context.strip())

    total = 0
    if snippets:
        for sn in snippets:
            name = (sn.get("filename") or "snippet").strip()
            lang = (sn.get("language") or "").strip()
            code = (sn.get("content") or "").strip()
            if not code:
                continue
            header = f"\n--- BEGIN FILE: {name} ---\n"
            fence_open = f"```{lang}\n" if lang else "```\n"
            block = header + fence_open + code + "\n```\n--- END FILE ---\n"
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining <= 0:
                    parts.append("\n[Truncated additional code due to size limit]")
                    break
                # truncate this block
                parts.append(block[:remaining] + "\n[...truncated]\n")
                total = max_chars + 1
                break
            parts.append(block)
            total += len(block)

    return (
        "Auxiliary code/context provided by the user (treat as source of truth when relevant):\n"
        + "".join(parts)
        + "\nEnd of auxiliary context.\n"
    )


def _language_directive(lang: str | None) -> str:
    if not lang or lang.lower() in ("auto", "detect", "same"):
        return "Reply in the same language as the user's last message (Italian or English)."
    if lang.lower().startswith("it"):
        return "Reply in Italian."
    if lang.lower().startswith("en"):
        return "Reply in English."
    return "Reply in the same language as the user's last message."


# ——— Main endpoint ———
@csrf_exempt
def programming_helper_send_message(request):  # noqa: C901
    """
    POST JSON body:
    {
      "message": "string",                 # required
      "local": "openai|mistral|openrouter|ollama",   # default "ollama"
      "size": "s|m|l|r",                 # default "m" (Small/Medium/Large/Reasoning)
      "verbosity": "low|medium|high",      # default "medium" (OpenAI only)
      "lang": "auto|it|en",                # default "auto"
      "character": "string",               # optional, groups conversations; default "developer"
      "topic": "string",                   # optional, additional conversation partition key
      "persona_id": 123,                    # optional, chat persona id
      "snippets": [                        # optional code/context
        {"filename":"app.py","language":"python","content":"..."},
        {"filename":"index.tsx","language":"typescript","content":"..."}
      ],
      "project_context": "short free text about stack/config"  # optional
    }

    Response (same shape as your existing API):
    {
      "response": "<assistant text>",
      "conversations": <_conversation_dump(character)>
    }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    message: str = (data.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Message required."}, status=400)

    local = (data.get("local") or "ollama").strip().lower()
    size = (data.get("size") or "m").strip().lower()
    verbosity = (data.get("verbosity") or DEFAULT_VERBOSITY).lower()
    if verbosity not in VERBOSITY_VALUES:
        verbosity = DEFAULT_VERBOSITY

    lang = (data.get("lang") or "auto").strip().lower()
    character = (data.get("character") or "developer").strip()
    topic = (data.get("topic") or "").strip()

    snippets = data.get("snippets") or []
    project_context = data.get("project_context") or ""

    persona_obj = None
    try:
        persona_id = int(data.get("persona_id", PROGRAMMING_HELPER_PERSONA_ID))
        if persona_id != PROGRAMMING_HELPER_PERSONA_ID:
            persona_obj = Persona.objects.get(pk=persona_id)
    except (ValueError, Persona.DoesNotExist):
        persona_id = PROGRAMMING_HELPER_PERSONA_ID
        persona_obj = None

    # Conversation management (mirror your style)
    # Use your shared key function with a stable pseudo persona id + optional topic
    if topic and not persona_obj:
        # fold topic into the id space in a stable way
        persona_key_fragment = abs(hash(("ph", topic))) % (10**6)
        persona_id = - (100000 + persona_key_fragment)

    key = _conversation_key(character, persona_id)

    # Handle reset
    if message.lower() == "reset":
        with LOCK:
            CONVERSATIONS.pop(key, None)
        return JsonResponse({"response": "Conversation has been reset."})

    # Append user turn & enforce max history
    MAX_USER_MESSAGES = 200 if (character.lower() == "master") else 24
    with LOCK:
        history: Deque[Tuple[str, str]] = CONVERSATIONS.setdefault(key, deque(maxlen=MAX_USER_MESSAGES * 2))
        user_turns = sum(1 for role, _ in history if role == "user")
        if user_turns >= MAX_USER_MESSAGES:
            return JsonResponse({"error": "Turn limit reached."}, status=403)
        history.append(("user", message))
        # Ollama requires a flat prompt version of the convo as well
        prompt_for_ollama = "\n".join(f"{r}: {t}" for r, t in history)

    # Build system content (base + language directive + optional code context)
    lang_rule = _language_directive(lang)
    code_block = _assemble_code_context(snippets, project_context)
    if persona_obj:
        system_base = persona_obj.contenuto
        if persona_obj.esperienze:
            system_base = f"{system_base}\n\nEsperienze:\n{persona_obj.esperienze}"
    else:
        system_base = PROGRAMMING_HELPER_SYSTEM
    combined_system = f"{system_base}\n\n{lang_rule}\n\n{code_block}".strip()

    # Provider calls
    context_limit = CONTEXT_ASSISTANT
    reply: str = ""

    if local == "ollama":
        if requests is None:
            return JsonResponse({"error": "requests library not installed"}, status=500)
        model = {
            "s": OLLAMA_QWEN_BASE,
            "m": OLLAMA_MISTRAL,
            "l": OLLAMA_QWEN_14,
            "r": OLLAMA_QWEN_14,
        }.get(size, OLLAMA_QWEN_14)
        payload = {
            "model": model,
            "prompt": prompt_for_ollama,
            "system": combined_system,
            "stream": False,
            "think": False,
            "hidethinking": True,
        }
        print(f"Model in use: {model}")
        try:
            resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=45)
            resp.raise_for_status()
            reply = resp.json().get("response", "")
        except Exception as exc:
            return JsonResponse({"error": f"Ollama call failed: {exc}"}, status=500)

    elif local == "mistral":
        if requests is None:
            return JsonResponse({"error": "requests library not installed"}, status=500)
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            return JsonResponse({"error": "MISTRAL_API_KEY not set"}, status=500)
        messages = _build_messages(history, combined_system)
        model = {
            "s": MISTRAL_MODEL_S,
            "m": MISTRAL_MODEL_M,
            "l": MISTRAL_MODEL_L,
            "r": MISTRAL_MODEL_R,
        }.get(size, MISTRAL_MODEL_M)
        print(f"Model in use: {model}")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
            "max_tokens": context_limit,
        }
        try:
            resp = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=45)
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            return JsonResponse({"error": f"Mistral API call failed: {exc}"}, status=500)

    elif local == "openai":
        if OpenAI is None:
            return JsonResponse({"error": "openai library not installed"}, status=500)
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return JsonResponse({"error": "OpenAI API key is empty"}, status=500)
        client = OpenAI(api_key=api_key)
        messages = _build_messages(history, combined_system)
        model_name = {
            "s": OPENAI_MODEL_S,
            "m": OPENAI_MODEL_L,
            "l": OPENAI_MODEL_L,
            "r": OPENAI_MODEL_R,
        }.get(size, OPENAI_MODEL_L)
        reasoning = {"effort": "high"} if size == "r" else {"effort": "minimal"} if size == "s" else None
        print(f"Model in use: {model_name}")
        try:
            resp = client.responses.create(
                model=model_name,
                input=messages,
                text={"verbosity": verbosity},
                max_output_tokens=context_limit,
                **({"reasoning": reasoning} if reasoning else {}),
            )
            reply = resp.output_text
        except Exception as exc:
            return JsonResponse({"error": f"OpenAI API call failed: {exc}"}, status=500)

    elif local == "openrouter":
        if requests is None:
            return JsonResponse({"error": "requests library not installed"}, status=500)
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return JsonResponse({"error": "OPENROUTER_API_KEY not set"}, status=500)

        messages = _build_messages(history, combined_system)
        model_name = {
            "s": OPENROUTER_MODEL_S,
            "m": OPENROUTER_MODEL_M,
            "l": OPENROUTER_MODEL_L,
            "r": OPENROUTER_MODEL_L,
        }.get(size, OPENROUTER_MODEL_S)
        print(f"Model in use: {model_name}")

        body = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": context_limit,
            "provider": {
                "allow_fallbacks": False
            }
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(OPENROUTER_BASE_URL, json=body, headers=headers, timeout=45)
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
        except Exception as exc:
            return JsonResponse({"error": f"OpenRouter API call failed: {exc}"}, status=500)

    else:
        return JsonResponse({"error": f"Unknown local value '{local}'"}, status=400)

    # Append assistant turn & return
    with LOCK:
        history.append(("assistant", reply))
    full_state = _conversation_dump(character)

    return JsonResponse({
        "response": reply,
        "conversations": full_state,
        "debug_prompt": {
            "system": combined_system,
            "messages": _build_messages(history, combined_system),
            "flat_prompt": prompt_for_ollama
        },
        "persona_debug": {
            "nome": persona_obj.nome,
            "versione": persona_obj.versione,
            "contenuto": persona_obj.contenuto,
            "esperienze": persona_obj.esperienze,
        }
    })
