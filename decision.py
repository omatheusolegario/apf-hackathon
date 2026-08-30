"""
Comparador de pagamento + Suitability Gate (Resolução CVM 30).
"""
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from models import User

PERFIL_PRODUTOS = {
    "conservador": ["cdb_liquidez", "poupanca", "tesouro_selic"],
    "moderado": ["cdb_liquidez", "poupanca", "tesouro_selic", "cdb_pos"],
    "arrojado": ["cdb_liquidez", "poupanca", "tesouro_selic", "cdb_pos", "fundos_rf"],
}

PRODUTOS_INFO = {
    "cdb_liquidez": {
        "nome": "CDB Liquidez Diária",
        "risco": "baixíssimo",
        "descricao": "Renda fixa com liquidez diária e garantia FGC até R$ 250 mil.",
        "rendimento_estimado": "~100% do CDI",
    },
    "poupanca": {
        "nome": "Poupança",
        "risco": "baixíssimo",
        "descricao": "Tradicional, isenta de IR para pessoa física.",
        "rendimento_estimado": "70% da Selic (quando Selic > 8,5%)",
    },
    "tesouro_selic": {
        "nome": "Tesouro Selic",
        "risco": "baixíssimo",
        "descricao": "Título público com liquidez diária, acompanha a Selic.",
        "rendimento_estimado": "Selic + ágio/deságio",
    },
    "cdb_pos": {
        "nome": "CDB Pós-fixado",
        "risco": "baixo",
        "descricao": "Renda fixa atrelada ao CDI, prazo definido.",
        "rendimento_estimado": "100% a 110% do CDI",
    },
    "fundos_rf": {
        "nome": "Fundos de Renda Fixa",
        "risco": "baixo a médio",
        "descricao": "Fundos que investem em títulos de renda fixa.",
        "rendimento_estimado": "Variável conforme carteira",
    },
}


async def get_perfil(session: AsyncSession, user_id: str) -> str:
    user = await session.get(User, user_id)
    if not user:
        return "moderado"
    return user.perfil_investidor or "moderado"


async def check_suitability_gate(
    session: AsyncSession, user_id: str, produto: str
) -> Dict[str, Any]:
    perfil = await get_perfil(session, user_id)
    permitidos = PERFIL_PRODUTOS.get(perfil, [])

    if produto not in permitidos:
        return {
            "permitido": False,
            "perfil": perfil,
            "mensagem": (
                f"O produto '{PRODUTOS_INFO.get(produto, {}).get('nome', produto)}' "
                f"não está disponível para o seu perfil ({perfil}) neste protótipo. "
                "Só sugerimos CDB liquidez diária, poupança e Tesouro Selic. "
                "Fale com um assessor Itaú para análise completa."
            ),
        }

    info = PRODUTOS_INFO.get(produto, {})
    return {
        "permitido": True,
        "perfil": perfil,
        "produto": info.get("nome", produto),
        "risco": info.get("risco"),
        "descricao": info.get("descricao"),
        "rendimento_estimado": info.get("rendimento_estimado"),
        "disclaimer": "Projeção estimada. Rentabilidade passada não garante rentabilidade futura.",
    }


def comparar_formas_pagamento(
    valor: float,
    saldo_disponivel: float = 0.0,
    fatura_atual: float = 1328.70,
    limite_disponivel: float = 6171.30,
) -> Dict[str, Any]:
    """
    Comparador interativo: cada opção tem id selecionável no frontend.
    """
    saldo_apos = round(saldo_disponivel - valor, 2)
    fatura_apos = round(fatura_atual + valor, 2)
    limite_apos = round(limite_disponivel - valor, 2)
    pix_viavel = saldo_apos >= 0
    credito_viavel = limite_apos >= 0
    return {
        "valor": valor,
        "selecionavel": True,
        "contexto": {
            "saldo_disponivel": round(saldo_disponivel, 2),
            "fatura_atual": fatura_atual,
            "limite_disponivel": limite_disponivel,
            "fonte": "cenário sintético do protótipo",
        },
        "opcoes": [
            {
                "id": "pix",
                "forma": "Pix",
                "custo": 0.0,
                "prazo": "Imediato",
                "recomendado": pix_viavel,
                "viavel": pix_viavel,
                "impacto": f"Saldo após: R$ {saldo_apos:,.2f}",
                "motivo": "Liquidação imediata e sem aumentar a fatura.",
                "icone": "bolt",
            },
            {
                "id": "debito",
                "forma": "Débito",
                "custo": 0.0,
                "prazo": "Imediato",
                "recomendado": False,
                "viavel": pix_viavel,
                "impacto": f"Saldo após: R$ {saldo_apos:,.2f}",
                "motivo": "Mesmo impacto no saldo; depende da aceitação do estabelecimento.",
                "icone": "credit_card",
            },
            {
                "id": "credito",
                "forma": "Crédito à vista",
                "custo": 0.0,
                "prazo": "Próxima fatura",
                "recomendado": False,
                "viavel": credito_viavel,
                "impacto": (
                    f"Fatura projetada: R$ {fatura_apos:,.2f}; "
                    f"limite restante: R$ {limite_apos:,.2f}"
                ),
                "motivo": "Preserva caixa hoje, mas exige pagamento integral da fatura para evitar juros.",
                "icone": "calendar_month",
            },
        ],
        "premissas": [
            "Não há desconto específico informado para Pix.",
            "Crédito considerado à vista e sem tarifa; juros do rotativo não foram incluídos.",
            "A recomendação muda se saldo, limite ou desconto real mudarem.",
        ],
        "_source": "sintético",
        "_disclaimer": "Comparação ilustrativa para demonstração. Selecione uma opção e confirme.",
    }
