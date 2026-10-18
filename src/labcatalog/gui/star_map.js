import "force-graph";

// The overview banner's catalog map: still, unclickable, drawn on a dark ground in the area given.
const LINK_ALPHA = 0.22;
const RELATED_ALPHA = 0.1;
const LABEL_PX = 10;
const MAX_ZOOM = 3;

function gravity(strength, squeeze) {
  // Pulls nodes to the centre, harder up and down, so the map spreads wide like the banner.
  let nodes = [];
  const force = (alpha) => {
    for (const n of nodes) {
      n.vx -= n.x * strength * alpha;
      n.vy -= n.y * strength * squeeze * alpha;
    }
  };
  force.initialize = (all) => (nodes = all);
  return force;
}

export default {
  template: `<div class="lc-star-map"></div>`,
  props: {
    spec: Object,
    // The area to fill, as shares of the banner: left, top, right, bottom.
    area: Array,
  },
  mounted() {
    const el = this.$el;
    const [short, long] = this.spec.force.length;
    this.graph = new window.ForceGraph(el)
      .width(el.clientWidth)
      .height(el.clientHeight)
      .backgroundColor("rgba(0,0,0,0)")
      .enablePointerInteraction(false)
      .enableZoomInteraction(false)
      .enablePanInteraction(false)
      .enableNodeDrag(false)
      .nodeCanvasObject((n, ctx, scale) => this.paintNode(n, ctx, scale))
      .linkCanvasObject((l, ctx, scale) => this.paintLink(l, ctx, scale))
      .warmupTicks(300)
      .cooldownTicks(0)
      .onEngineStop(() => this.fit());
    this.graph.d3Force("center", null);
    this.graph.d3Force("gravity", gravity(this.spec.force.gravity, 4));
    this.graph.d3Force("charge").strength(-this.spec.force.repel).distanceMax(long * 4);
    this.graph.d3Force("link").distance((l) => (l.tip ? long : short)).strength((l) => (l.tip ? 0.03 : 0.8));
    this.graph.graphData({
      nodes: this.spec.nodes.map((n) => ({ ...n })),
      links: this.spec.links.map((l) => ({ ...l })),
    });
    this.resizeObserver = new ResizeObserver(() => {
      this.graph.width(el.clientWidth).height(el.clientHeight);
      this.fit();
    });
    this.resizeObserver.observe(el);
  },
  beforeUnmount() {
    this.resizeObserver?.disconnect();
    this.graph?._destructor();
  },
  methods: {
    fit() {
      const box = this.graph.getGraphBbox();
      if (!box) return;
      const w = this.$el.clientWidth;
      const h = this.$el.clientHeight;
      const [left, top, right, bottom] = this.area;
      const [x0, x1] = box.x;
      const [y0, y1] = box.y;
      const k = Math.min(((right - left) * w) / Math.max(x1 - x0, 1), ((bottom - top) * h) / Math.max(y1 - y0, 1), MAX_ZOOM);
      // Puts the map's middle at the area's middle rather than the banner's.
      const cx = (x0 + x1) / 2 - (((left + right) / 2) * w - w / 2) / k;
      const cy = (y0 + y1) / 2 - (((top + bottom) / 2) * h - h / 2) / k;
      this.graph.centerAt(cx, cy, 0);
      this.graph.zoom(k, 0);
    },
    paintNode(n, ctx, scale) {
      const color = this.spec.groups[n.group]?.color || "#9aa5b1";
      ctx.save();
      ctx.shadowColor = color;
      ctx.shadowBlur = n.named ? 14 : 7;
      ctx.globalAlpha = n.named ? 0.95 : 0.8;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, (n.named ? 4.2 : Math.max(1.4, n.size * 0.75)) / scale, 0, 2 * Math.PI);
      ctx.fill();
      ctx.restore();
      if (!n.named) return;
      ctx.font = `600 ${LABEL_PX / scale}px ${getComputedStyle(this.$el).fontFamily}`;
      ctx.fillStyle = "rgba(236, 236, 238, 0.75)";
      ctx.textBaseline = "bottom";
      ctx.fillText(n.name, n.x + 6 / scale, n.y - 3 / scale);
    },
    paintLink(l, ctx, scale) {
      const s = l.source;
      const t = l.target;
      if (typeof s !== "object" || typeof t !== "object") return;
      ctx.strokeStyle = `rgba(255, 255, 255, ${l.tip ? RELATED_ALPHA : LINK_ALPHA})`;
      ctx.lineWidth = 0.6 / scale;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
    },
  },
};
