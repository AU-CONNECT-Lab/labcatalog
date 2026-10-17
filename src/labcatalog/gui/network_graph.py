from collections.abc import Callable

from nicegui import ui


class NetworkGraph(
    ui.element, component="network_graph.js", dependencies=["vendor/force-graph.min.js"]
):
    def __init__(
        self, spec: dict, height: int, on_click: Callable[[str], None] | None = None
    ) -> None:
        super().__init__()
        self._props["spec"] = spec
        self._props["height"] = height
        if on_click is not None:
            self.on("node_click", lambda e: on_click(e.args))

    def show(self, spec: dict) -> None:
        self._props["spec"] = spec
        self.update()
