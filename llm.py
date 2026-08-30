"""
Proxy Groq + prompt engineering + guardrails de grounding.
"""
import os
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "openai/gpt-oss-20b"


def _client() -> Optional[AsyncGroq]:
    """Cria o cliente sob demanda para o app também iniciar sem chave de LLM."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return AsyncGroq(api_key=api_key, timeout=15.0, max_retries=1)

_PILLS: List[Dict[str, Any]] = []
_pills_path = Path(__file__).parent / "knowledge_pills.json"
if _pills_path.exists():
    try:
        _PILLS = json.loads(_pills_path.read_text(encoding="utf-8"))
    except Exception:
        _PILLS = []

SYSTEM_PROMPT = """Você é o Assistente Pessoal Financeiro (APF) do Itaú.

REGRAS OBRIGATÓRIAS:
1. Use APENAS os dados do contexto (grounding). Nunca invente saldos, valores, datas ou transações.
2. Fale de forma natural e confiante, como um assistente real do banco. NÃO mencione "dados sintéticos", "demonstração", "simulação", "protótipo" ou "em produção".
3. Investimentos: só sugira CDB liquidez diária, poupança ou Tesouro Selic. Nunca ações, cripto, multimercado ou COE.
4. Ao falar de rentabilidade, diga: "Projeção estimada. Rentabilidade passada não garante rentabilidade futura."
5. Seja objetivo, amigável e em português brasileiro.
6. Se faltar dado no grounding, diga que não tem a informação e sugira verificar no app Itaú.
7. FORMATAÇÃO: NÃO use markdown (sem **, sem #, sem listas com - ou *). Escreva texto corrido e claro, com quebras de linha simples quando precisar. Os cards da interface já mostram números e botões.
8. Respostas curtas: 2 a 5 frases, a menos que o usuário peça detalhe.
9. NÃO sugira ações que a UI já cobre com cards (ex.: "clique em confirmar"). Descreva o contexto; os cards fazem o resto.
10. Nunca diga que está em modo demo ou que os dados são fictícios.
"""


def _pick_pill(intent: str, user_text: str) -> Optional[Dict[str, Any]]:
    if not _PILLS:
        return None
    mapping = {
        "investir": ["investimentos", "compliance"],
        "pagar": ["pagamentos", "seguranca"],
        "comparar": ["pagamentos"],
        "saldo": ["investimentos", "educacao"],
        "padroes": ["educacao", "pagamentos"],
        "ajuda": ["educacao", "compliance"],
        "seguranca": ["seguranca"],
    }
    cats = mapping.get(intent, ["educacao"])
    for pill in _PILLS:
        if pill.get("categoria") in cats:
            return pill
    return _PILLS[0] if intent == "ajuda" else None


def strip_markdown(text: str) -> str:
    if not text:
        return text
    t = text
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"__(.+?)__", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"_(.+?)_", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^\s*[-*•]\s+", "• ", t, flags=re.MULTILINE)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# Remove vazamentos de linguagem de demo caso o modelo ignore o prompt
_DEMO_LEAK = re.compile(
    r"(?i)(\(?\s*)?(dados?\s+sint[eé]ticos?(?:\s+de\s+demonstra[cç][aã]o)?|"
    r"ambiente\s+de\s+demonstra[cç][aã]o|"
    r"modo\s+de\s+demonstra[cç][aã]o|"
    r"em\s+produ[cç][aã]o\s+viriam[^.]*\.?|"
    r"cen[aá]rio\s+de\s+demonstra[cç][aã]o|"
    r"\(simula[cç][aã]o\)|"
    r"simula[cç][aã]o\s+no\s+app|"
    r"protótipo)(\s*\))?",
)


def sanitize_user_facing(text: str) -> str:
    if not text:
        return text
    t = strip_markdown(text)
    t = _DEMO_LEAK.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" +\n", "\n", t)
    return t.strip()


async def call_groq(
    user_text: str,
    intent: str,
    grounding: Dict[str, Any],
    conversation_history: Optional[list] = None,
) -> str:
    # Não vaza flags internas de demo para o modelo falar sobre elas
    clean_grounding = {
        k: v for k, v in grounding.items()
        if not str(k).startswith("_")
    }
    grounding_str = json.dumps(clean_grounding, ensure_ascii=False, indent=2, default=str)

    pill = _pick_pill(intent, user_text)
    pill_block = ""
    if pill:
        pill_block = (
            f"\n\nPÍLULA DE CONHECIMENTO (pode citar de forma natural se for útil):\n"
            f"Título: {pill.get('titulo')}\n{pill.get('texto')}"
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                f"DADOS DE CONTEXTO (use somente estes):\n{grounding_str}\n\n"
                f"Intent detectado: {intent}{pill_block}"
            ),
        },
    ]

    if conversation_history:
        messages.extend(conversation_history[-6:])

    messages.append({"role": "user", "content": user_text})

    groq = _client()
    if groq is None:
        return (
            "Consigo executar saldo, extrato, pagamentos, transferências e padrões normalmente, "
            "mas a resposta conversacional está indisponível porque a chave da Groq não foi configurada."
        )

    models = [
        os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        os.getenv("GROQ_FALLBACK_MODEL", FALLBACK_MODEL),
    ]
    last_error: Optional[Exception] = None
    for model in dict.fromkeys(models):
        try:
            completion = await groq.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.25,
                max_tokens=400,
            )
            raw = (completion.choices[0].message.content or "").strip()
            if raw:
                return sanitize_user_facing(raw)
        except Exception as exc:
            last_error = exc
            print(f"[llm] Modelo {model} indisponível: {exc}")

    print(f"[llm] Falha em todos os modelos: {last_error}")
    return "Desculpe, a resposta conversacional está temporariamente indisponível. Tente novamente em instantes."


def validate_grounding(raw_text: str, grounding: Dict[str, Any]) -> str:
    # Não anexa mais disclaimer de dados sintéticos — imersão.
    return sanitize_user_facing(raw_text)
