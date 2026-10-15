import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_retries(
    func: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], bool],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    # Exponential backoff with jitter; the last failure is re-raised.
    attempt = 0
    while True:
        try:
            return func()
        except Exception as e:
            if attempt >= max_retries or not is_retryable(e):
                raise
            time.sleep(min(base_delay * 2**attempt + random.uniform(0, 0.5), max_delay))
            attempt += 1
