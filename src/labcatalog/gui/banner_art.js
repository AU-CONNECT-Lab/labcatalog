// The overview banner's star map, inlined so hovering near a star lights it, its links and its neighbours.
const REACH_PX = 16;

export default {
  template: `<div class="lc-banner-art" @mousemove="move" @mouseleave="light(null)"></div>`,
  props: {
    src: String,
  },
  async mounted() {
    this.$el.innerHTML = await (await fetch(this.src)).text();
    this.svg = this.$el.querySelector("svg");
    this.stars = [...this.svg.querySelectorAll(".dots circle")].map((c) => ({
      i: c.dataset.i,
      x: +c.getAttribute("cx"),
      y: +c.getAttribute("cy"),
    }));
    this.lines = [...this.svg.querySelectorAll(".links line")];
    this.shown = null;
  },
  methods: {
    move(event) {
      if (!this.svg) return;
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(this.svg.getScreenCTM().inverse());
      const scale = this.svg.viewBox.baseVal.width / this.svg.getBoundingClientRect().width;
      let best = null;
      let nearest = REACH_PX * scale;
      for (const star of this.stars) {
        const d = Math.hypot(star.x - point.x, star.y - point.y);
        if (d < nearest) [best, nearest] = [star.i, d];
      }
      this.light(best);
    },
    light(i) {
      if (i === this.shown) return;
      this.shown = i;
      for (const on of this.svg.querySelectorAll(".lc-art-on, .lc-art-me")) on.classList.remove("lc-art-on", "lc-art-me");
      this.svg.classList.toggle("lc-art-focus", i !== null);
      if (i === null) return;
      const near = new Set([i]);
      for (const line of this.lines) {
        if (line.dataset.a === i || line.dataset.b === i) {
          line.classList.add("lc-art-on");
          near.add(line.dataset.a);
          near.add(line.dataset.b);
        }
      }
      for (const n of near) {
        for (const c of this.svg.querySelectorAll(`circle[data-i="${n}"]`)) c.classList.add("lc-art-on");
      }
      for (const c of this.svg.querySelectorAll(`circle[data-i="${i}"]`)) c.classList.add("lc-art-me");
    },
  },
};
