from nicegui import ui


class NetworkGraph(
    ui.element, component="network_graph.js", dependencies=["vendor/force-graph.min.js"]
):
    def __init__(self, spec: dict, height: int) -> None:
        super().__init__()
        self._props["spec"] = spec
        self._props["height"] = height

    def show(self, spec: dict) -> None:
        self._props["spec"] = spec
        self.update()
