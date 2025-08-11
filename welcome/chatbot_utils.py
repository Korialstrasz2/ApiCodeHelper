from __future__ import annotations

import json
import logging
import threading
from typing import Deque, Dict, List, Tuple, Union
from django.http import JsonResponse

try:
    from the_elder_django.log_config import get_log_types  # noqa: F401 – side‑effects
except Exception:  # pragma: no cover - optional dependency
    pass
from .GLOBALS_AND_WORKING import LOCK, CONVERSATIONS
from .models import Persona

logging.getLogger("faiss.loader").setLevel(logging.ERROR)
log = logging.getLogger("custom")

def _conversation_key(character: str | None, persona_pk: int) -> Tuple[str, int]:
    return (character or "anonymous", persona_pk)

def _conversation_dump(character: str | None) -> Dict[str, List[Dict[str, str]]]:
    result: Dict[str, List[Dict[str, str]]] = {}
    with LOCK:
        for (p, persona_pk), history in CONVERSATIONS.items():
            if p != (character or "anonymous"):
                continue
            try:
                persona = Persona.objects.get(pk=persona_pk)
            except Persona.DoesNotExist:
                continue
            result.setdefault(persona.nome, []).extend(
                {"role": r, "content": t} for r, t in history
            )
    return result

def personas_list(request):
    master_mode = request.GET.get("master") == "true"
    qs = Persona.objects.all()
    if not master_mode:
        qs = qs.filter(ristretto=False)
    data = [
        {
            "id": p.pk,
            "nome": p.nome,
            "versione": p.versione,
        }
        for p in qs.order_by("nome")
    ]
    return JsonResponse({"personas": data})

def ollama_get_conversations(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        data = json.loads(request.body)
        character = data.get("character")
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not character:
        return JsonResponse({"error": "character required."}, status=400)
    return JsonResponse({"conversations": _conversation_dump(character)})

def persona_add_experience(request):
    try:
        data = json.loads(request.body)
        nome = data["nome"]
        versione = data.get("versione", "1")
        text = data["text"].strip()
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Payload non valido."}, status=400)
    if not text:
        return JsonResponse({"error": "Testo vuoto."}, status=400)
    try:
        persona = Persona.objects.get(nome=nome, versione=versione)
    except Persona.DoesNotExist:
        return JsonResponse({"error": "Persona non trovata."}, status=404)
    suffix = ";\n"
    nuovo = (persona.esperienze or "").rstrip()
    if nuovo and not nuovo.endswith(";"):
        nuovo += ";"
    persona.esperienze = f"{nuovo} {text}{suffix}".lstrip()
    persona.save(update_fields=["esperienze"])
    return JsonResponse({"ok": True})
