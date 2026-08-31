"""
Gera 6 meses de transações sintéticas realistas + mais variedade para demo.
Tudo explicitamente rotulado como sintético.
"""
import asyncio
from datetime import date, timedelta
from random import uniform, choice, randint, seed as py_seed
from database import init_db, AsyncSessionLocal
from models import (
    User,
    Transaction,
    Pattern,
    Conversation,
    NotificationLog,
    PixAutomatico,
    BoletoPago,
    FinancialPreference,
    FlowState,
    ContinuationToken,
    ScannedBoleto,
    ChannelLinkCode,
)

py_seed(42)  # reprodutível

USER_ID = "demo"
USER_NAME = "Maria Silva"


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


async def seed_user(
    user_id: str = USER_ID,
    user_name: str = USER_NAME,
    *,
    reset: bool = True,
    initial_consents: bool = True,
):
    """Cria uma conta sintética isolada e, opcionalmente, reinicia sua jornada."""
    if not user_id.startswith("demo") or len(user_id) > 50:
        raise ValueError("Identificador de demonstração inválido")
    py_seed(42)
    await init_db()
    async with AsyncSessionLocal() as session:
        existing = await session.get(User, user_id)
        if existing and reset:
            consents = (
                existing.consent_padroes_pagamento,
                existing.consent_habitos_gasto,
                existing.consent_saldo_ocioso,
            )
            print("Usuário demo já existe. Limpando transações e padrões...")
            for model in (
                ContinuationToken,
                ChannelLinkCode,
                ScannedBoleto,
                FlowState,
                FinancialPreference,
                BoletoPago,
                PixAutomatico,
                NotificationLog,
                Conversation,
                Pattern,
                Transaction,
            ):
                await session.execute(
                    model.__table__.delete().where(model.user_id == user_id)
                )
            existing.consent_padroes_pagamento = consents[0]
            existing.consent_habitos_gasto = consents[1]
            existing.consent_saldo_ocioso = consents[2]
            existing.muted_categories = {}
            existing.notificacoes_hoje = 0
            existing.ultima_notificacao_data = None
            await session.commit()
        elif not existing:
            user = User(
                id=user_id,
                name=user_name,
                perfil_investidor="moderado",
                consent_padroes_pagamento=initial_consents,
                consent_habitos_gasto=initial_consents,
                consent_saldo_ocioso=initial_consents,
            )
            session.add(user)
            await session.commit()
            print(f"Usuário {user_name} criado.")
        else:
            return {"user_id": user_id, "created": False, "reset": False}

        today = date.today()
        start = today - timedelta(days=180)
        transactions = []

        # 1. Salário — final do mês (~R$ 5.500)
        for d in daterange(start, today):
            if d.day in (28, 29, 30, 31) and d.weekday() < 5:
                if not any(
                    t.data.month == d.month and t.data.year == d.year and "Salário" in t.descricao
                    for t in transactions
                ):
                    transactions.append(
                        Transaction(
                            user_id=user_id,
                            data=d,
                            tipo="ted",
                            valor=5500.00,
                            descricao="Salário - Empresa XYZ",
                            categoria="renda",
                            favorecido=None,
                            is_synthetic=True,
                        )
                    )

        # 2. Aluguel — dia 10 (PIX R$ 1.500)
        for d in daterange(start, today):
            if d.day == 10:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="pix",
                        valor=1500.00,
                        descricao="Aluguel - João Silva",
                        categoria="moradia",
                        favorecido="João Silva",
                        is_synthetic=True,
                    )
                )

        # 3. Academia — dia 5 (PIX R$ 89,90)
        for d in daterange(start, today):
            if d.day == 5:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="pix",
                        valor=89.90,
                        descricao="Academia Smart Fit",
                        categoria="saude",
                        favorecido="Smart Fit",
                        is_synthetic=True,
                    )
                )

        # 4. Netflix — dia 15
        for d in daterange(start, today):
            if d.day == 15:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="debito",
                        valor=39.90,
                        descricao="Netflix",
                        categoria="entretenimento",
                        favorecido="Netflix",
                        is_synthetic=True,
                    )
                )

        # 5. Spotify — dia 12
        for d in daterange(start, today):
            if d.day == 12:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="debito",
                        valor=21.90,
                        descricao="Spotify Premium",
                        categoria="entretenimento",
                        favorecido="Spotify",
                        is_synthetic=True,
                    )
                )

        # 6. Internet Vivo — dia 20
        for d in daterange(start, today):
            if d.day == 20:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="boleto",
                        valor=119.90,
                        descricao="Vivo Fibra",
                        categoria="moradia",
                        favorecido="Vivo",
                        is_synthetic=True,
                    )
                )

        # 7. iFood — ~70% dias úteis
        for d in daterange(start, today):
            if d.weekday() < 5 and randint(1, 10) <= 7:
                valor = round(uniform(32.0, 68.0), 2)
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="pix",
                        valor=valor,
                        descricao=f"iFood - {choice(['Restaurante A', 'Restaurante B', 'Lanche C', 'Sushi Express'])}",
                        categoria="alimentacao",
                        favorecido="iFood",
                        is_synthetic=True,
                    )
                )

        # 8. Conta de água / luz
        for d in daterange(start, today):
            if d.day == 5:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="boleto",
                        valor=round(uniform(160.0, 220.0), 2),
                        descricao="SABESP - Água",
                        categoria="moradia",
                        favorecido="SABESP",
                        is_synthetic=True,
                    )
                )
            if d.day == 8:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="boleto",
                        valor=round(uniform(180.0, 280.0), 2),
                        descricao="ENEL - Energia",
                        categoria="moradia",
                        favorecido="ENEL",
                        is_synthetic=True,
                    )
                )

        # 9. Pix mensal para mãe (R$ 300)
        for d in daterange(start, today):
            if d.day == 3:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="pix",
                        valor=300.00,
                        descricao="Ajuda familiar - Maria Aparecida",
                        categoria="transferencia",
                        favorecido="Maria Aparecida",
                        is_synthetic=True,
                    )
                )

        # 10. Combustível / posto
        for d in daterange(start, today):
            if d.weekday() == 5 and randint(1, 10) <= 6:  # sábados
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="credito",
                        valor=round(uniform(120.0, 280.0), 2),
                        descricao="Posto Ipiranga",
                        categoria="transporte",
                        favorecido="Ipiranga",
                        is_synthetic=True,
                    )
                )

        # 11. Extras aleatórios
        categorias_extras = [
            ("transporte", "Uber / 99", 12, 55),
            ("saude", "Farmácia Droga Raia", 25, 110),
            ("compras", "Mercado Extra", 80, 320),
            ("lazer", "Cinema / Show", 40, 180),
            ("compras", "Amazon", 35, 250),
            ("educacao", "Curso online", 50, 199),
            ("vestuario", "Renner / Zara", 60, 280),
        ]
        for d in daterange(start, today):
            if randint(1, 10) <= 4:
                cat, desc, vmin, vmax = choice(categorias_extras)
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo=choice(["pix", "debito", "credito"]),
                        valor=round(uniform(vmin, vmax), 2),
                        descricao=desc,
                        categoria=cat,
                        favorecido=None,
                        is_synthetic=True,
                    )
                )

        # 12. Poupança programada — dia 25 (TED saída R$ 500)
        for d in daterange(start, today):
            if d.day == 25 and d.weekday() < 5:
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        data=d,
                        tipo="ted",
                        valor=500.00,
                        descricao="Transferência para poupança",
                        categoria="investimento",
                        favorecido="Poupança Itaú",
                        is_synthetic=True,
                    )
                )

        session.add_all(transactions)
        await session.commit()
        print(f"{len(transactions)} transações sintéticas criadas para o usuário '{user_id}'.")
        print("Seed concluído com sucesso.")
        return {"user_id": user_id, "created": existing is None, "reset": bool(existing)}


async def seed():
    return await seed_user()


if __name__ == "__main__":
    asyncio.run(seed())
