from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TypeVar
from weakref import WeakKeyDictionary

from nicegui import core
from nicegui.client import Client
from nicegui.slot import Slot

from labcatalog import defaults
from labcatalog.charts import style
from labcatalog.config import LlmConfig, ProjectConfig

T = TypeVar("T")


@dataclass
class Look:
    # One window's settings: its person's colours and appearance, its project's numbers and model.
    palette: str = style.DEFAULT_PALETTE
    dark: bool = False
    decimals: int = defaults.DECIMALS
    llm: LlmConfig = field(default_factory=LlmConfig)

    def use_project(self, config: ProjectConfig | None) -> None:
        self.decimals = config.stats.decimals if config else defaults.DECIMALS
        self.llm = config.llm if config else LlmConfig()


# Set for work a window hands to a thread or its own background task, which have no page slot.
CURRENT: ContextVar[Look | None] = ContextVar("look", default=None)
WINDOWS: WeakKeyDictionary[Client, Look] = WeakKeyDictionary()
# Outside any window: before the app starts, and in tests.
OUTSIDE = Look()


def look() -> Look:
    found = CURRENT.get()
    if found is not None:
        return found
    stack = Slot.get_stack() if core.app.is_started else []
    if not stack:
        return OUTSIDE
    return WINDOWS.get(stack[-1].parent.client, OUTSIDE)


def register(client: Client, found: Look) -> None:
    WINDOWS[client] = found


def install() -> None:
    style.palette_of = lambda: look().palette


def scoped(found: Look, callback: Callable[..., T], *args) -> T:
    token = CURRENT.set(found)
    try:
        return callback(*args)
    finally:
        CURRENT.reset(token)


async def within(found: Look, work: Awaitable[T]) -> T:
    # A background task copies its context, so this setting stays with the task.
    CURRENT.set(found)
    return await work
