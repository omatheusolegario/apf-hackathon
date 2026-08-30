from __future__ import annotations

from datetime import datetime, date
from sqlalchemy import (
    String, Float, Integer, Boolean, DateTime, Date, Text, ForeignKey, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    perfil_investidor: Mapped[str] = mapped_column(String(20), default="moderado")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    consent_padroes_pagamento: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_habitos_gasto: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_saldo_ocioso: Mapped[bool] = mapped_column(Boolean, default=False)

    notificacoes_hoje: Mapped[int] = mapped_column(Integer, default=0)
    ultima_notificacao_data: Mapped[date | None] = mapped_column(Date, nullable=True)

    muted_categories: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    patterns: Mapped[list["Pattern"]] = relationship(back_populates="user")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
    pix_automaticos: Mapped[list["PixAutomatico"]] = relationship(back_populates="user")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"))
    data: Mapped[date] = mapped_column(Date)
    tipo: Mapped[str] = mapped_column(String(30))
    valor: Mapped[float] = mapped_column(Float)
    descricao: Mapped[str] = mapped_column(String(255))
    categoria: Mapped[str] = mapped_column(String(80))
    favorecido: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="transactions")


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"))
    tipo: Mapped[str] = mapped_column(String(50))
    descricao: Mapped[str] = mapped_column(String(255))
    valor_medio: Mapped[float] = mapped_column(Float)
    frequencia: Mapped[int] = mapped_column(Integer)
    ultima_data: Mapped[date | None] = mapped_column(Date, nullable=True)
    metodo: Mapped[str] = mapped_column(String(50), default="agregacao_sql")
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="patterns")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="conversations")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"))
    categoria: Mapped[str] = mapped_column(String(50))
    mensagem: Mapped[str] = mapped_column(Text)
    enviado: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PixAutomatico(Base):
    __tablename__ = "pix_automaticos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"))
    favorecido: Mapped[str] = mapped_column(String(120))
    valor: Mapped[float] = mapped_column(Float)
    dia_mes: Mapped[int] = mapped_column(Integer, default=10)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="pix_automaticos")


class FinancialPreference(Base):
    """Preferências financeiras editáveis sem alterar o cadastro bancário."""
    __tablename__ = "financial_preferences"

    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), primary_key=True
    )
    reserva_seguranca: Mapped[float] = mapped_column(Float, default=2000.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class BoletoPago(Base):
    __tablename__ = "boletos_pagos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"))
    boleto_id: Mapped[str] = mapped_column(String(50))
    valor: Mapped[float] = mapped_column(Float)
    beneficiario: Mapped[str] = mapped_column(String(120))
    pago_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FlowState(Base):
    """Estado transacional persistente, compartilhado entre app e Telegram."""
    __tablename__ = "flow_states"

    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), primary_key=True)
    pending_transfer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_transfer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ContinuationToken(Base):
    """Token curto para uma jornada iniciada fora do canal seguro."""
    __tablename__ = "continuation_tokens"

    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    action: Mapped[dict] = mapped_column(JSON)
    source_channel: Mapped[str] = mapped_column(String(30), default="telegram")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScannedBoleto(Base):
    """Boleto extraído de imagem; só pode ser pago após confirmação no app."""
    __tablename__ = "scanned_boletos"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    beneficiario: Mapped[str] = mapped_column(String(120))
    valor: Mapped[float] = mapped_column(Float)
    vencimento: Mapped[date | None] = mapped_column(Date, nullable=True)
    linha_digitavel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_hash: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extraction_mode: Mapped[str] = mapped_column(String(40), default="demo_fallback")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChannelIdentity(Base):
    """Vínculo verificado entre uma identidade externa e o cliente do APF."""
    __tablename__ = "channel_identities"

    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChannelLinkCode(Base):
    """Código de uso único criado no app para vincular um canal externo."""
    __tablename__ = "channel_link_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="telegram")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
