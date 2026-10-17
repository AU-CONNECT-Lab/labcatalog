import "force-graph";

// Screen pixels at which a label is fully shown; below it labels fade out, as in Obsidian.
const LABEL_PX = 10;
const FADE_MS = 220;
const DIM = 0.12;
// The fitted view never zooms in further than this, so a small network keeps room around it.
const FIT_ZOOM = 2.6;
// For this long after a new layout starts, the view follows it while it spreads out.
const FOLLOW_MS = 1500;

function gravity(strength) {
  // Pulls every node towards the centre, so groups with no link between them stay in view.
  let nodes = [];
  const force = (alpha) => {
    for (const n of nodes) {
      n.vx -= n.x * strength * alpha;
      n.vy -= n.y * strength * alpha;
    }
  };
  force.initialize = (all) => (nodes = all);
  return force;
}

export default {
  template: `
    <div class="lc-network">
      <div ref="stage"></div>
      <div class="lc-network-legend">
        <span v-for="(g, i) in spec.groups" :key="g.name" class="lc-network-key"
              :class="{ 'lc-network-off': hidden.includes(i) }" @click="toggle(i)">
          <span class="lc-network-swatch" :style="{ background: g.color }"></span>{{ g.name }}
        </span>
      </div>
    </div>`,
  props: {
    spec: Object,
    height: Number,
  },
  data() {
    return { hidden: [] };
  },
  mounted() {
    this.focus = null;
    this.near = new Set();
    this.level = 0;
    this.fade = { from: 0, to: 0, start: 0 };
    this.touched = false;
    this.colors = {};
    const stage = this.$refs.stage;
    this.graph = new window.ForceGraph(stage)
      .width(this.$el.clientWidth)
      .height(this.height)
      .backgroundColor("rgba(0,0,0,0)")
      .nodeId("id")
      .nodeLabel("tip")
      .linkLabel("tip")
      .nodeVal((n) => n.size * n.size)
      .nodeRelSize(1)
      .nodeCanvasObject((n, ctx, scale) => this.paintNode(n, ctx, scale))
      .nodePointerAreaPaint((n, color, ctx) => {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.size + 2, 0, 2 * Math.PI);
        ctx.fill();
      })
      .linkCanvasObject((l, ctx, scale) => this.paintLink(l, ctx, scale))
      .nodeVisibility((n) => !this.hidden.includes(n.group))
      .linkVisibility((l) => !this.hidden.includes(l.source.group) && !this.hidden.includes(l.target.group))
      .onNodeHover((n) => this.hover(n))
      .onNodeDrag((n) => this.hover(n))
      .onRenderFramePre(() => this.readTheme())
      .d3VelocityDecay(0.3)
      .warmupTicks(100)
      .minZoom(0.2)
      .maxZoom(12)
      .onEngineTick(() => {
        if (!this.touched && performance.now() - this.started < FOLLOW_MS) this.fit(0);
      })
      .onEngineStop(() => {
        if (!this.touched) this.fit(600);
      });
    for (const event of ["wheel", "pointerdown"]) {
      stage.addEventListener(event, () => (this.touched = true), { passive: true });
    }
    this.resizeObserver = new ResizeObserver(() => this.graph.width(this.$el.clientWidth));
    this.resizeObserver.observe(this.$el);
    this.load(this.spec);
  },
  beforeUnmount() {
    this.resizeObserver?.disconnect();
    this.graph?._destructor();
  },
  watch: {
    spec(value) {
      this.load(value);
    },
  },
  methods: {
    load(spec) {
      const old = new Map(this.graph.graphData().nodes.map((n) => [n.id, n]));
      const linkKey = (l) => `${l.source.id ?? l.source}|${l.target.id ?? l.target}`;
      const oldLinks = new Map(this.graph.graphData().links.map((l) => [linkKey(l), l]));
      const sameNodes = old.size === spec.nodes.length && spec.nodes.every((n) => old.has(n.id));
      const sameLinks = oldLinks.size === spec.links.length && spec.links.every((l) => oldLinks.has(linkKey(l)));
      this.hidden = this.hidden.filter((i) => i < spec.groups.length);
      if (sameNodes && sameLinks) {
        // Only the colours changed: keep the layout still.
        for (const n of spec.nodes) Object.assign(old.get(n.id), n);
        for (const l of spec.links) {
          const { source, target, ...rest } = l;
          Object.assign(oldLinks.get(linkKey(l)), rest);
        }
        this.redraw();
        return;
      }
      // Scores already drawn keep their places, so the layout only drifts.
      const nodes = spec.nodes.map((n) => Object.assign(old.get(n.id) || {}, n));
      const links = spec.links.map((l) => ({ ...l }));
      const top = Math.max(...links.map((l) => l.value), 1e-9);
      const [short, long] = spec.force.length;
      this.graph.d3Force("center", null);
      this.graph.d3Force("gravity", gravity(spec.force.gravity));
      this.graph.d3Force("charge").strength(-spec.force.repel).distanceMax(long * 4);
      this.graph
        .d3Force("link")
        .distance((l) => long - ((long - short) * l.value) / top)
        .strength((l) => 0.15 + 0.6 * l.value);
      this.focus = null;
      this.near = new Set();
      if (!old.size) this.started = performance.now();
      this.graph.graphData({ nodes, links });
    },
    fit(ms) {
      const box = this.graph.getGraphBbox();
      if (!box) return;
      const pad = 50;
      const [x0, x1] = box.x;
      const [y0, y1] = box.y;
      const k = Math.min(
        (this.$el.clientWidth - 2 * pad) / Math.max(x1 - x0, 1),
        (this.height - 2 * pad) / Math.max(y1 - y0, 1),
        FIT_ZOOM,
      );
      this.graph.centerAt((x0 + x1) / 2, (y0 + y1) / 2, ms);
      this.graph.zoom(k, ms);
    },
    toggle(i) {
      this.hidden = this.hidden.includes(i) ? this.hidden.filter((k) => k !== i) : [...this.hidden, i];
      this.graph.nodeVisibility(this.graph.nodeVisibility());
    },
    readTheme() {
      const style = getComputedStyle(this.$el);
      this.colors = {
        ink: style.getPropertyValue("--lc-ink").trim(),
        muted: style.getPropertyValue("--lc-muted").trim(),
        panel: style.getPropertyValue("--lc-panel").trim(),
        font: style.fontFamily,
      };
      const t = Math.min(1, (performance.now() - this.fade.start) / FADE_MS);
      const eased = t * (2 - t);
      this.level = this.fade.from + (this.fade.to - this.fade.from) * eased;
    },
    hover(node) {
      if (node) {
        this.focus = node;
        this.near = new Set([node.id]);
        for (const l of this.graph.graphData().links) {
          if (l.source.id === node.id) this.near.add(l.target.id);
          if (l.target.id === node.id) this.near.add(l.source.id);
        }
      }
      const to = node ? 1 : 0;
      if (to === this.fade.to) return;
      this.fade = { from: this.level, to, start: performance.now() };
      this.redraw();
    },
    redraw() {
      // Keeps drawing while the fade runs, then lets the canvas rest again.
      this.graph.autoPauseRedraw(false);
      clearTimeout(this.resting);
      this.resting = setTimeout(() => {
        this.graph.autoPauseRedraw(true);
        if (this.fade.to === 0) this.focus = null;
      }, FADE_MS + 60);
    },
    paintNode(n, ctx, scale) {
      const focused = this.focus && this.near.has(n.id);
      const alpha = this.focus && !focused ? 1 - (1 - DIM) * this.level : 1;
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.size, 0, 2 * Math.PI);
      ctx.fillStyle = this.spec.groups[n.group]?.color || this.colors.muted;
      ctx.fill();
      if (this.focus && n.id === this.focus.id) {
        ctx.lineWidth = 2 / scale;
        ctx.strokeStyle = this.colors.ink;
        ctx.globalAlpha = this.level;
        ctx.stroke();
        ctx.globalAlpha = alpha;
      }
      // Labels grow with the zoom and fade out below LABEL_PX; the hovered one and its neighbours stay.
      const size = 4.2;
      let shown = Math.max(0, Math.min(1, (size * scale - LABEL_PX * 0.6) / (LABEL_PX * 0.4)));
      let font = size;
      if (focused) {
        shown = Math.max(shown * alpha, this.level);
        font = Math.max(size, LABEL_PX / scale);
      } else {
        shown *= alpha;
      }
      if (shown <= 0.02) return;
      ctx.globalAlpha = shown;
      ctx.font = `${focused && n.id === this.focus.id ? 600 : 400} ${font}px ${this.colors.font}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const y = n.y + n.size + font * 0.35;
      ctx.lineWidth = font * 0.3;
      ctx.lineJoin = "round";
      ctx.strokeStyle = this.colors.panel;
      ctx.strokeText(n.name, n.x, y);
      ctx.fillStyle = focused ? this.colors.ink : this.colors.muted;
      ctx.fillText(n.name, n.x, y);
      ctx.globalAlpha = 1;
    },
    paintLink(l, ctx, scale) {
      const s = l.source;
      const t = l.target;
      if (typeof s !== "object" || typeof t !== "object") return;
      const touching = this.focus && (s.id === this.focus.id || t.id === this.focus.id);
      let alpha = 0.5;
      let width = l.width;
      if (this.focus) {
        alpha = touching ? 0.5 + 0.45 * this.level : 0.5 * (1 - (1 - DIM) * this.level);
        if (touching) width += this.level;
      }
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = l.color;
      ctx.lineWidth = width / scale;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
      ctx.globalAlpha = 1;
    },
  },
};
