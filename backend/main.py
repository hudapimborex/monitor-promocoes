"""Entrypoint do Web Service (Render): serve o painel MVP + export CSV.

A busca agendada roda fora deste processo (GitHub Actions chamando
`worker.py --run-now`, ver README) — Render free não tem Background Worker.
O painel também tem um botão "rodar análise agora" que dispara a mesma busca
em background dentro deste processo, pra você poder testar sem depender do
GitHub Actions.
"""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from app.api.auth import router as auth_router
from app.api.subscribe import router as subscribe_router
from app.core.live_log import install_live_log_handler
from app.web.auth_web import NotAuthenticatedError
from app.web.login_routes import router as login_router
from app.web.routes import router as web_router
from app.web.settings_routes import router as settings_router

install_live_log_handler()

app = FastAPI(title="Monitor de Promoções de Pisos e Revestimentos")

app.include_router(auth_router)
app.include_router(subscribe_router)
app.include_router(login_router)
app.include_router(settings_router)
app.include_router(web_router)


@app.exception_handler(NotAuthenticatedError)
async def handle_not_authenticated(request: Request, exc: NotAuthenticatedError):
    return RedirectResponse(url="/login", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}
