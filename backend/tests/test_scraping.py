import datetime as dt

from app.db.models import Category, User
from app.scraping.planner import plan_today
from app.scraping.query_builder import build_queries
from app.scraping.quota import daily_query_allowance, record_credits, remaining_budget


def make_category(**overrides) -> Category:
    defaults = dict(
        user_id=1,
        slug="porcelanato",
        name="Porcelanato",
        priority=1,
        active=True,
        keywords_json={
            "base_terms": ["porcelanato"],
            "discount_terms": ["promoção", "oferta"],
            "sizes": ["80x80"],
        },
    )
    defaults.update(overrides)
    return Category(**defaults)


def test_build_queries_prioritizes_generic_before_sized():
    category = make_category()
    queries = build_queries(category)

    assert queries[:2] == ["porcelanato promoção", "porcelanato oferta"]
    assert "porcelanato 80x80 promoção" in queries
    assert "porcelanato 80x80 oferta" in queries
    # sem duplicatas
    assert len(queries) == len(set(queries))


def test_build_queries_respects_max_queries():
    category = make_category()
    queries = build_queries(category, max_queries=1)
    assert queries == ["porcelanato promoção"]


def test_build_queries_falls_back_to_category_name_when_no_terms():
    category = make_category(keywords_json={})
    queries = build_queries(category)
    assert queries == ["Porcelanato promoção"]


def test_quota_tracks_usage_and_remaining_budget(db_session):
    remaining_before = remaining_budget(db_session)
    assert remaining_before > 0

    record_credits(db_session, 10)
    remaining_after = remaining_budget(db_session)
    assert remaining_after == remaining_before - 10


def test_quota_allowance_drops_to_zero_when_budget_exhausted(db_session):
    remaining = remaining_budget(db_session)
    record_credits(db_session, remaining)  # zera o orçamento do mês

    assert daily_query_allowance(db_session, credits_per_query=5) == 0


def test_planner_returns_empty_when_no_categories(db_session):
    plans = plan_today(db_session, user_id=1)
    assert plans == []


def test_planner_rotates_categories_and_builds_queries(db_session):
    user = User(email="test@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    cats = [
        make_category(user_id=user.id, slug=f"cat-{i}", name=f"Categoria {i}", priority=i)
        for i in range(5)
    ]
    db_session.add_all(cats)
    db_session.commit()

    plans = plan_today(db_session, user_id=user.id, today=dt.date(2026, 8, 10))

    assert 0 < len(plans) <= 2  # categories_per_day do config/categories.yml é 2
    for plan in plans:
        assert plan.queries
        assert plan.scrape_top_n > 0
