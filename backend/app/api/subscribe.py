"""Endpoints de planos/assinatura.

Nenhuma cobrança acontece aqui — é só o "gancho" para o gateway de
pagamento futuro (Stripe ou Mercado Pago, pensando em uso no Brasil).
Quando isso for implementado de verdade, é este endpoint que passa a criar
uma sessão de checkout no provedor e, via webhook, atualizar
`Subscription.status` para "active" (ver models em app/db/models.py).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Plan, Subscription, User
from app.db.session import get_db

router = APIRouter(tags=["billing"])


class PlanResponse(BaseModel):
    id: int
    name: str
    price_cents: int
    max_searches_per_day: int
    max_categories: int
    max_notifications_per_day: int


class SubscribeRequest(BaseModel):
    plan_name: str


class SubscribeResponse(BaseModel):
    status: str
    message: str


@router.get("/plans", response_model=List[PlanResponse])
def list_plans(db: Session = Depends(get_db)):
    plans = db.query(Plan).order_by(Plan.price_cents.asc()).all()
    return [PlanResponse(**p.__dict__) for p in plans]


@router.post("/subscribe", response_model=SubscribeResponse)
def subscribe(
    payload: SubscribeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stub: só grava a intenção de assinatura, sem cobrar nada de verdade.

    TODO (quando integrar Stripe/Mercado Pago): trocar o bloco de plano pago
    por uma chamada real ao provedor criando uma sessão de checkout e
    devolvendo a URL de pagamento; o webhook do provedor então atualiza
    `Subscription.status` para "active" junto com
    `provider_customer_id`/`current_period_end`.
    """
    plan = db.query(Plan).filter(Plan.name == payload.plan_name).first()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plano '{payload.plan_name}' não existe")

    if plan.price_cents == 0:
        db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", provider=None))
        user.plan_id = plan.id
        db.commit()
        return SubscribeResponse(status="active", message=f"Plano '{plan.name}' ativado (gratuito).")

    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="pending", provider=None))
    db.commit()
    return SubscribeResponse(
        status="pending",
        message=(
            "Cobrança ainda não implementada neste MVP. Esta chamada só registrou a "
            "intenção de assinatura — a integração com Stripe/Mercado Pago é o próximo passo."
        ),
    )
