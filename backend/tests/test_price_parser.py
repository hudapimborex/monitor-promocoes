from app.scraping.price_parser import extract_best_price


def test_extracts_simple_price():
    assert extract_best_price("Preço: R$ 89,90/m²") == 89.90


def test_extracts_price_with_thousands_separator():
    assert extract_best_price("De R$ 1.500,00 por R$ 1.234,56") == 1234.56


def test_ignores_installment_prices():
    text = "12x de R$ 199,90 sem juros. À vista R$ 1.999,00"
    assert extract_best_price(text) == 1999.00


def test_returns_none_when_no_price_found():
    assert extract_best_price("Sem preço aqui") is None


def test_returns_none_for_empty_text():
    assert extract_best_price("") is None
