from app.scraping.coupon_parser import extract_coupon


def test_extracts_simple_coupon():
    match = extract_coupon("Use o cupom PROMO10 e ganhe 10% de desconto")
    assert match is not None
    assert match.code == "PROMO10"


def test_extracts_coupon_with_colon():
    match = extract_coupon("CUPOM: DESC15OFF válido até domingo")
    assert match is not None
    assert match.code == "DESC15OFF"


def test_extracts_coupon_in_english_variants():
    assert extract_coupon("use code SAVE20 at checkout").code == "SAVE20"
    assert extract_coupon("coupon: WELCOME5").code == "WELCOME5"


def test_ignores_generic_words_without_digits():
    assert extract_coupon("veja o código abaixo") is None
    assert extract_coupon("cupom promocional disponível") is None


def test_returns_none_when_no_coupon_present():
    assert extract_coupon("Preço: R$ 89,90/m² à vista") is None


def test_returns_none_for_empty_text():
    assert extract_coupon("") is None
    assert extract_coupon(None) is None
