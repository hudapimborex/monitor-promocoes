"""Modelos do banco.

Desenhado multi-tenant desde o início: todas as tabelas "de negócio" têm
user_id, mesmo que no MVP exista um único usuário. `Plan`/`Subscription` são
o gancho para o gateway de pagamento futuro (Stripe/Mercado Pago) — sem
nenhuma lógica de cobrança implementada ainda.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Plan(Base):
    """Plano de assinatura (ex: Free, Pro). Limites usados para throttling."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    max_searches_per_day: Mapped[int] = mapped_column(Integer, default=30)
    max_categories: Mapped[int] = mapped_column(Integer, default=2)
    max_notifications_per_day: Mapped[int] = mapped_column(Integer, default=50)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    users: Mapped[list["User"]] = relationship(back_populates="plan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plans.id"), nullable=True)

    plan: Mapped[Optional[Plan]] = relationship(back_populates="users")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user")
    categories: Mapped[list["Category"]] = relationship(back_populates="user")
    notification_settings: Mapped[Optional["NotificationSettings"]] = relationship(
        back_populates="user", uselist=False
    )


class Subscription(Base):
    """Gancho para gateway de pagamento futuro (Stripe / Mercado Pago).

    Nenhuma cobrança real acontece ainda — o endpoint /subscribe só grava
    aqui com status "inactive"/"pending". Quando a integração de pagamento
    for feita, é este o registro que passa a refletir o estado real.
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(20), default="inactive")
    provider: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    provider_customer_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    current_period_end: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions")
    plan: Mapped[Plan] = relationship()


class Category(Base):
    """Categoria de busca (porcelanato, piso laminado, ...) com seus termos."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    slug: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    keywords_json: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_category_user_slug"),)

    user: Mapped[User] = relationship(back_populates="categories")
    search_runs: Mapped[list["SearchRun"]] = relationship(back_populates="category")
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class SearchRun(Base):
    """Registro de cada chamada de busca feita (para auditoria de cota/custo)."""

    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    query: Mapped[str] = mapped_column(String(255))
    ran_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category: Mapped[Category] = relationship(back_populates="search_runs")
    price_points: Mapped[list["PriceHistory"]] = relationship(back_populates="source_search_run")


class Product(Base):
    """Produto único (deduplicado por URL normalizada) visto em uma loja."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    store_domain: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "url_hash", name="uq_product_user_url"),)

    category: Mapped[Category] = relationship(back_populates="products")
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="product", order_by="PriceHistory.captured_at"
    )
    alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="product")
    coupons: Mapped[list["Coupon"]] = relationship(back_populates="product")


class PriceHistory(Base):
    """Toda observação de preço, sempre gravada (é a base do histórico)."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source_search_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("search_runs.id"), nullable=True
    )

    product: Mapped[Product] = relationship(back_populates="price_history")
    source_search_run: Mapped[Optional[SearchRun]] = relationship(back_populates="price_points")


class PriceAlert(Base):
    """Só é criado quando a lógica de queda real (app/pricing) confirma a queda."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    old_price: Mapped[float] = mapped_column(Float)
    new_price: Mapped[float] = mapped_column(Float)
    drop_pct: Mapped[float] = mapped_column(Float)
    # Aponta pra linha exata de price_history que originou o alerta — usado
    # para não recriar o mesmo alerta se a checagem rodar de novo sem uma
    # observação de preço nova (idempotência).
    source_price_history_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("price_history.id"), nullable=True
    )
    notified_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "product_id", "source_price_history_id", name="uq_price_alert_product_source"
        ),
    )

    product: Mapped[Product] = relationship(back_populates="alerts")


class Coupon(Base):
    """Código de cupom de desconto — achado de graça no texto já raspado da
    página (mesma chamada que já extrai preço) ou via busca dedicada em
    sites agregadores (Cuponomia, Pelando, Méliuz — ver query_builder.py).

    `product_id` fica nulo quando o cupom veio de um site agregador que não
    corresponde a um produto específico que já rastreamos.
    """

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    store_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    found_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    product: Mapped[Optional[Product]] = relationship(back_populates="coupons")


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # Pode ter vários chat_ids separados por vírgula (ver app/notifications/service.py).
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channels_enabled_json: Mapped[list] = mapped_column(
        JSON, default=lambda: ["telegram", "dashboard"]
    )

    user: Mapped[User] = relationship(back_populates="notification_settings")


class UserCredentials(Base):
    """Chaves/tokens de integração configuráveis pelo painel (/settings) em
    vez de só pelo .env — quando preenchidas aqui, têm prioridade sobre a
    variável de ambiente correspondente (ver app/core/user_credentials.py).
    """

    __tablename__ = "user_credentials"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    firecrawl_api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_bot_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Pode ter vários chat_ids separados por vírgula (ver app/notifications/service.py).
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()


class CreditUsage(Base):
    """Contador simples de créditos Firecrawl gastos por mês (gerenciador de cota)."""

    __tablename__ = "credit_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_month: Mapped[str] = mapped_column(String(7), unique=True, index=True)  # "2026-08"
    credits_used: Mapped[float] = mapped_column(Float, default=0.0)
