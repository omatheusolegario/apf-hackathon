"""
Testes de regressão do fluxo transacional (sem LLM/Groq).
Rodar: python test_transfers.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ["GROQ_API_KEY"] = "test-dummy"

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, AsyncSessionLocal
from seed import seed
from transfers import (
    parse_transfer,
    detect_transfer_intent,
    clear_pending,
    set_last_transfer,
    execute_transfer,
    TransferDraft,
    compute_saldo,
    open_boletos,
    configure_pix_automatico,
    list_pix_automaticos,
    mute_category,
    is_muted,
)
from main import (
    process_message,
    _handle_card_action,
    _resolve_investment_amount,
    classify_intent,
)
from proactive import run_proactive_scan


def ok(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        raise AssertionError(name)


async def run():
    print("== seed ==")
    await seed()

    print("== parse / intent ==")
    d = parse_transfer("pix de 150 para João", user_id="demo")
    ok("parse valor", d.valor == 150.0)
    ok("parse joao", d.favorecido == "João Silva")
    ok("detect pix", detect_transfer_intent("quero fazer um pix"))
    ok("classify transferir", classify_intent("pix de 80 pro João") == "transferir")
    ok(
        "classify guardar como investimento",
        classify_intent("guardar o restante do saldo") == "investir",
    )

    print("== valores de investimento ==")
    explicit = _resolve_investment_amount("guardo 2000 no cdb", 7992.61)
    ok("valor explícito prevalece", explicit["valor"] == 2000.0, str(explicit))
    remaining = _resolve_investment_amount("guardar o restante do saldo", 2000.0)
    ok("restante usa saldo integral", remaining["valor"] == 2000.0, str(remaining))
    no_excess = _resolve_investment_amount("aplicar em cdb", 1200.0)
    ok("sem excedente não inventa R$ 800", no_excess["valor"] is None, str(no_excess))

    set_last_transfer("demo", {"tipo": "pix", "valor": 200.0, "favorecido": "João Silva"})
    d2 = parse_transfer("manda de novo", user_id="demo")
    ok("de novo valor", d2.valor == 200.0, str(d2.valor))
    ok("de novo fav", d2.favorecido == "João Silva")
    d3 = parse_transfer("metade", user_id="demo")
    ok("metade", d3.valor == 100.0, str(d3.valor))

    print("== proatividade acionável ==")
    async with AsyncSessionLocal() as s:
        proactive = await run_proactive_scan(s, "demo")
        ok("gera ações contextuais", any(item.get("action") for item in proactive))
        ok(
            "pix recorrente com favorecido real",
            any(
                item.get("action", {}).get("type") == "configure_pix_auto"
                and item.get("action", {}).get("favorecido") == "João Silva"
                for item in proactive
            ),
        )

    print("== multi-turno + execute ==")
    clear_pending("demo")
    async with AsyncSessionLocal() as s:
        saldo0 = await compute_saldo(s, "demo")
        r1 = await process_message(s, "quero fazer um pix", "demo")
        ok("ask slots", "valor" in r1["text"].lower() or "para quem" in r1["text"].lower())
        r2 = await process_message(s, "90 para João", "demo")
        types = [c["type"] for c in r2["cards"]]
        ok("confirm card", "transfer_confirm" in types, str(types))
        r3 = await _handle_card_action(s, {
            "type": "execute_transfer",
            "tipo": "pix",
            "valor": 90,
            "favorecido": "João Silva",
        }, "demo")
        ok("executed", "enviado" in r3["text"].lower() or "pix" in r3["text"].lower(), r3["text"][:80])
        saldo1 = await compute_saldo(s, "demo")
        ok("saldo debitado", abs((saldo0 - 90) - saldo1) < 0.02, f"{saldo0} -> {saldo1}")
        ok("receipt", any(c["type"] == "transfer_receipt" for c in r3["cards"]))

    print("== boletos ==")
    async with AsyncSessionLocal() as s:
        bills = await open_boletos(s, "demo")
        ok("3 boletos", len(bills) == 3, str(len(bills)))
        bid = bills[0]["id"]
        r = await _handle_card_action(s, {
            "type": "confirm_payment",
            "forma": "Pix",
            "valor": bills[0]["valor"],
            "boleto_id": bid,
            "favorecido": bills[0]["beneficiario"],
        }, "demo")
        bills2 = await open_boletos(s, "demo")
        ok("boleto sumiu", len(bills2) == 2 and all(b["id"] != bid for b in bills2), str(len(bills2)))
        ok("pago receipt", any(c["type"] == "transfer_receipt" for c in r["cards"]))
        r_dup = await _handle_card_action(s, {
            "type": "confirm_payment",
            "forma": "Pix",
            "boleto_id": bid,
            "valor": 0.01,
            "favorecido": "Atacante",
        }, "demo")
        ok("boleto idempotente", "já foi pago" in r_dup["text"].lower())

    print("== segurança no servidor ==")
    clear_pending("demo")
    async with AsyncSessionLocal() as s:
        risky = await process_message(s, "pix de 2500 para Carlos", "demo")
        ok("security card", any(c["type"] == "security_check" for c in risky["cards"]))
        blocked = await _handle_card_action(s, {
            "type": "execute_transfer",
            "tipo": "pix",
            "valor": 1,
            "favorecido": "Atacante",
        }, "demo")
        ok("bypass bloqueado", "confirme a identidade" in blocked["text"].lower())
        await _handle_card_action(s, {"type": "security_pass"}, "demo")
        sent = await _handle_card_action(s, {"type": "execute_transfer"}, "demo")
        ok("envia após segurança", any(c["type"] == "transfer_receipt" for c in sent["cards"]))

    print("== comparador continua o fluxo ==")
    clear_pending("demo")
    async with AsyncSessionLocal() as s:
        saldo0 = await compute_saldo(s, "demo")
        selected = await _handle_card_action(s, {
            "type": "confirm_payment", "forma": "Pix", "valor": 75,
        }, "demo")
        saldo1 = await compute_saldo(s, "demo")
        ok("pede destinatário", any(c["type"] == "transfer_contacts" for c in selected["cards"]))
        ok("não debita antes da confirmação", saldo0 == saldo1)

    print("== pix automatico + mute ==")
    async with AsyncSessionLocal() as s:
        saved = await configure_pix_automatico(s, "demo", "João Silva", 1500.0, dia_mes=10)
        items = await list_pix_automaticos(s, "demo")
        ok("pix auto saved", any(i["favorecido"] == "João Silva" for i in items), str(items))
        await mute_category(s, "demo", "pix_recorrente")
        ok("muted", await is_muted(s, "demo", "pix_recorrente"))

    print("== saldo insuficiente ==")
    async with AsyncSessionLocal() as s:
        r = await execute_transfer(s, "demo", TransferDraft(
            tipo="pix", valor=9_999_999, favorecido="X", security_passed=True,
        ))
        ok("bloqueia saldo", r.get("erro") == "saldo_insuficiente")

    print("\nTodos os testes passaram.")


if __name__ == "__main__":
    asyncio.run(run())
