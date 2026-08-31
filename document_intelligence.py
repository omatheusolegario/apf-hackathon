"""Extração multimodal de boletos com validação e fallback explícito de demo."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Dict

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ScannedBoleto

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")


def _image_content_type(content: bytes, declared_type: str | None) -> str:
    """Valida a assinatura do arquivo e devolve um MIME canônico.

    Navegadores podem enviar imagens escolhidas como application/octet-stream.
    A assinatura evita rejeitar esses arquivos sem confiar em uma extensão ou
    Content-Type potencialmente falsificados.
    """
    detected = None
    if content.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        detected = "image/webp"

    normalized = (declared_type or "").split(";", 1)[0].strip().lower()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if detected is None:
        raise ValueError("Envie uma imagem JPG, PNG ou WebP válida.")
    if normalized in ALLOWED_TYPES and normalized != detected:
        raise ValueError("O conteúdo da imagem não corresponde ao formato informado.")
    return detected


def _response_text(payload: Dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    chunks = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks)


def _json_from_text(text: str) -> Dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    return json.loads(candidate)


async def _extract_with_groq(content: bytes, content_type: str) -> Dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY") or ""
    if not api_key:
        raise RuntimeError("GROQ_API_KEY ausente")
    data_url = f"data:{content_type};base64,{base64.b64encode(content).decode()}"
    prompt = (
        "Extraia os dados visíveis deste boleto brasileiro. Responda SOMENTE JSON com: "
        "beneficiario (string), valor (number), vencimento (YYYY-MM-DD ou null), "
        "linha_digitavel (somente dígitos ou null), confidence (0 a 1). "
        "Não invente campos ilegíveis; use null e reduza confidence."
    )
    payload = {
        "model": VISION_MODEL,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
    }
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
    result = _json_from_text(_response_text(response.json()))
    result["extraction_mode"] = "groq_vision"
    result["model"] = VISION_MODEL
    return result


def _demo_fallback(filename: str | None) -> Dict[str, Any]:
    """Fallback determinístico para palco; nunca se apresenta como OCR real."""
    name = (filename or "").lower()
    if "enel" in name:
        beneficiary, amount = "ENEL", 243.10
    elif "vivo" in name:
        beneficiary, amount = "Vivo Fibra", 119.90
    else:
        beneficiary, amount = "SABESP", 187.40
    return {
        "beneficiario": beneficiary,
        "valor": amount,
        "vencimento": (date.today() + timedelta(days=5)).isoformat(),
        "linha_digitavel": "846700000017874000240209608290547110001001250805",
        "confidence": 0.62,
        "extraction_mode": "demo_fallback",
        "model": None,
    }


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    beneficiary = str(raw.get("beneficiario") or "").strip()[:120]
    amount = float(raw.get("valor") or 0)
    confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
    digits = re.sub(r"\D", "", str(raw.get("linha_digitavel") or "")) or None
    if digits and len(digits) not in (44, 46, 47, 48):
        digits = None
        confidence = min(confidence, 0.55)
    due = None
    if raw.get("vencimento"):
        try:
            due = datetime.strptime(str(raw["vencimento"]), "%Y-%m-%d").date()
        except ValueError:
            confidence = min(confidence, 0.5)
    if not beneficiary or not (0 < amount <= 1_000_000):
        raise ValueError("Não foi possível identificar beneficiário e valor com segurança.")
    return {
        **raw,
        "beneficiario": beneficiary,
        "valor": round(amount, 2),
        "vencimento": due,
        "linha_digitavel": digits,
        "confidence": confidence,
    }


async def scan_boleto(
    session: AsyncSession,
    user_id: str,
    content: bytes,
    content_type: str,
    filename: str | None,
) -> Dict[str, Any]:
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("A imagem deve ter até 8 MB.")
    content_type = _image_content_type(content, content_type)
    digest = hashlib.sha256(content).hexdigest()
    existing = await session.execute(
        select(ScannedBoleto).where(
            ScannedBoleto.user_id == user_id,
            ScannedBoleto.document_hash == digest,
        )
    )
    item = existing.scalars().first()
    if item:
        return _serialize(item, duplicate=True)
    try:
        raw = await _extract_with_groq(content, content_type)
    except Exception as exc:
        print(f"[boleto-scan] visão indisponível: {exc}")
        raw = _demo_fallback(filename)
    data = _validate(raw)
    item = ScannedBoleto(
        id=f"SCAN_{secrets.token_hex(6).upper()}",
        user_id=user_id,
        beneficiario=data["beneficiario"],
        valor=data["valor"],
        vencimento=data["vencimento"],
        linha_digitavel=data["linha_digitavel"],
        document_hash=digest,
        confidence=data["confidence"],
        extraction_mode=data["extraction_mode"],
    )
    session.add(item)
    await session.commit()
    return _serialize(item, model=raw.get("model"))


def _serialize(
    item: ScannedBoleto, duplicate: bool = False, model: str | None = None
) -> Dict[str, Any]:
    return {
        "id": item.id,
        "beneficiario": item.beneficiario,
        "valor": item.valor,
        "vencimento": item.vencimento.isoformat() if item.vencimento else None,
        "linha_digitavel": item.linha_digitavel,
        "confidence": item.confidence,
        "extraction_mode": item.extraction_mode,
        "model": model,
        "duplicate": duplicate,
        "requires_confirmation": True,
        "source": "imagem_enviada_pelo_usuario",
    }
