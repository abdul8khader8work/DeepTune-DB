"""Rate limiting shared by the API routers."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.config import get_settings

limiter = Limiter(key_func=get_remote_address)
analyze_limit = get_settings().analyze_rate_limit
