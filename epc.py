"""
EPC – Detecção de recorrência por agregação SQL.
Método explicitamente rotulado como agregacao_sql (não clustering).
"""
from datetime import date, timedelta
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from models import Pattern


async def detect_pix_recorrente(session: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    """
    Pix recorrente: mesmo favorecido, valor estável (variação < 5%), 3+ ocorrências.
    """
    query = text("""
        SELECT favorecido, AVG(valor) as valor_medio, COUNT(*) as frequencia, MAX(data) as ultima_data,
               MIN(valor) as min_valor, MAX(valor) as max_valor
        FROM transactions
        WHERE user_id = :user_id AND tipo = 'pix' AND favorecido IS NOT NULL
        GROUP BY favorecido
        HAVING COUNT(*) >= 3 AND (MAX(valor) - MIN(valor)) / NULLIF(MAX(valor), 0) < 0.05
        ORDER BY frequencia DESC
    """)
    result = await session.execute(query, {"user_id": user_id})
    rows = result.fetchall()

    patterns = []
    for row in rows:
        ultima = row.ultima_data
        if ultima and hasattr(ultima, "isoformat"):
            ultima = ultima.isoformat()
        elif ultima:
            ultima = str(ultima)
        patterns.append({
            "tipo": "pix_recorrente",
            "descricao": f"Pix recorrente para {row.favorecido}",
            "favorecido": row.favorecido,
            "valor_medio": round(float(row.valor_medio), 2),
            "frequencia": row.frequencia,
            "ultima_data": ultima,
            "_metodo": "agregacao_sql",
            "_nota": "Não utiliza clustering estatístico.",
        })
    return patterns


async def detect_gastos_fixos(session: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    """
    Gastos fixos por categoria nos últimos 3 meses.
    Thresholds mais sensíveis: 6+ ocorrências, variação < 30%.
    """
    tres_meses = (date.today() - timedelta(days=90)).isoformat()
    query = text("""
        SELECT categoria, AVG(valor) as valor_medio, COUNT(*) as frequencia,
               MIN(valor) as min_valor, MAX(valor) as max_valor
        FROM transactions
        WHERE user_id = :user_id AND data > :tres_meses
          AND categoria NOT IN ('renda', 'investimento', 'transferencia')
        GROUP BY categoria
        HAVING COUNT(*) >= 6 AND (MAX(valor) - MIN(valor)) / NULLIF(MAX(valor), 0) < 0.30
        ORDER BY frequencia DESC
    """)
    result = await session.execute(query, {"user_id": user_id, "tres_meses": tres_meses})
    rows = result.fetchall()

    patterns = []
    for row in rows:
        patterns.append({
            "tipo": "gasto_fixo",
            "descricao": f"Gasto recorrente em {row.categoria}",
            "categoria": row.categoria,
            "valor_medio": round(float(row.valor_medio), 2),
            "frequencia": row.frequencia,
            "_metodo": "agregacao_sql",
            "_nota": "Não utiliza clustering estatístico.",
        })
    return patterns


async def detect_assinaturas(session: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    """
    Assinaturas/débitos recorrentes por favorecido (Netflix, Spotify etc.).
    """
    query = text("""
        SELECT favorecido, descricao, AVG(valor) as valor_medio, COUNT(*) as frequencia,
               MAX(data) as ultima_data
        FROM transactions
        WHERE user_id = :user_id
          AND tipo IN ('debito', 'boleto')
          AND favorecido IS NOT NULL
        GROUP BY favorecido, descricao
        HAVING COUNT(*) >= 3
        ORDER BY frequencia DESC
    """)
    result = await session.execute(query, {"user_id": user_id})
    rows = result.fetchall()

    patterns = []
    for row in rows:
        ultima = row.ultima_data
        if ultima and hasattr(ultima, "isoformat"):
            ultima = ultima.isoformat()
        elif ultima:
            ultima = str(ultima)
        patterns.append({
            "tipo": "assinatura",
            "descricao": f"Assinatura: {row.descricao}",
            "favorecido": row.favorecido,
            "valor_medio": round(float(row.valor_medio), 2),
            "frequencia": row.frequencia,
            "ultima_data": ultima,
            "_metodo": "agregacao_sql",
            "_nota": "Não utiliza clustering estatístico.",
        })
    return patterns


async def run_epc(session: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    """Executa todas as detecções e persiste os padrões."""
    pix = await detect_pix_recorrente(session, user_id)
    gastos = await detect_gastos_fixos(session, user_id)
    assinaturas = await detect_assinaturas(session, user_id)
    all_patterns = pix + gastos + assinaturas

    await session.execute(
        Pattern.__table__.delete().where(Pattern.user_id == user_id)
    )

    for p in all_patterns:
        ultima = None
        if p.get("ultima_data"):
            try:
                ultima = date.fromisoformat(str(p["ultima_data"])[:10])
            except Exception:
                ultima = None
        pattern = Pattern(
            user_id=user_id,
            tipo=p["tipo"],
            descricao=p["descricao"],
            valor_medio=p["valor_medio"],
            frequencia=p["frequencia"],
            ultima_data=ultima,
            metodo="agregacao_sql",
            raw_data=p,
        )
        session.add(pattern)

    await session.commit()
    return all_patterns
