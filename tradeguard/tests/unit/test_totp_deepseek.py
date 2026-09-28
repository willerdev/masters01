import time

from app.core.totp import generate_secret, totp_at, verify_totp
from app.services.ai_service import DeepSeekProvider, provider_for


def test_totp_accepts_the_current_code():
    secret = generate_secret()
    code = totp_at(secret, int(time.time()))
    assert verify_totp(secret, code)
    wrong = "000000" if code != "000000" else "111111"
    assert not verify_totp(secret, wrong)


def test_deepseek_uses_the_openai_compatible_host():
    provider = provider_for("deepseek", "secret", "")
    assert isinstance(provider, DeepSeekProvider)
    assert provider.base_url == "https://api.deepseek.com/v1"
