"""Configuração central da aplicação, lida de variáveis de ambiente (.env).

Mantemos tudo em um único Settings (pydantic-settings) para que trocar de
SQLite (dev local / .exe) para Postgres/Supabase (produção cloud) seja só
uma questão de mudar DATABASE_URL — nenhum código de negócio depende do
banco específico. Os caminhos (onde fica o `.env`, onde grava o SQLite, onde
lê templates/config) vêm de app/core/paths.py, que sabe a diferença entre
rodar do código-fonte e rodar empacotado como .exe.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.paths import IS_FROZEN, env_file_dir, resource_dir, sqlite_dir


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(env_file_dir() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "local"

    # Banco: sqlite local por padrão (caminho absoluto, então funciona igual
    # não importa de qual diretório o processo é iniciado). Em produção
    # (cloud), aponte para o Postgres do Supabase via DATABASE_URL no .env
    # (ex: postgresql+psycopg2://...).
    database_url: str = f"sqlite:///{sqlite_dir() / 'promo_monitor.db'}"

    # Firecrawl
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev/v1"
    # Orçamento mensal de créditos com margem sobre a cota grátis (1000/mês).
    firecrawl_monthly_credit_budget: int = 900
    firecrawl_scrape_top_n: int = 3
    # Geo-bias dos resultados de busca (params "country"/"location" do
    # endpoint /search da Firecrawl) — prioriza lojas brasileiras/da região
    # sem restringir a busca a uma lista fixa de domínios. Ajuste no .env se
    # quiser mudar a região (ex: outra cidade/estado).
    firecrawl_search_country: str = "BR"
    firecrawl_search_location: str = "Rio de Janeiro, Rio de Janeiro, Brazil"

    # Telegram
    telegram_bot_token: str = ""
    telegram_default_chat_id: str = ""

    # Auth
    jwt_secret: str = "change-me-in-.env"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Regras de detecção de queda real de preço
    price_drop_threshold_pct: float = 15.0
    price_baseline_window_days: int = 60
    price_min_stable_days: int = 3

    # Config de categorias/keywords (recurso somente-leitura do bundle)
    categories_config_path: str = str(resource_dir("config", "categories.yml"))

    # Usuário semeado (você). No .exe local não há setup de .env prévio, então
    # usamos um login padrão claramente local — troque a senha em
    # Configurações (/settings) assim que abrir pela primeira vez.
    bootstrap_user_email: str = "admin@local.app" if IS_FROZEN else "enghudson.hl@gmail.com"
    bootstrap_user_password: str = "trocar123" if IS_FROZEN else "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
