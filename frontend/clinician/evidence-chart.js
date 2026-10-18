/**
 * One evidence chart: the patient's daily values against the reference band.
 *
 * Form (CLAUDE.md section 5.2): a single-series line over days, drawn on top of
 * the age- and sex-specific NHANES band (p10 to p90, with the p50 dashed). One
 * series, so there is no legend box: the card title names the metric, and the
 * band is labelled directly. Values outside the band get a hollow marker, so the
 * reading never depends on colour alone. Every point has a hover and keyboard
 * tooltip, and the card includes a table view of the same numbers.
 *
 * Plain SVG, no chart library: nothing to vendor, nothing to build.
 *
 * @module evidence-chart
 */

const SVG_NS = "http://www.w3.org/2000/svg";
const WIDTH = 420;
const HEIGHT = 190;
const MARGIN = { top: 12, right: 64, bottom: 28, left: 40 };
const MARKER_RADIUS = 4;
const HIT_RADIUS = 12;
const Y_TICKS = 4;

/** Human titles and how to read each metric (definitions in ml/features/daily.py). */
export const METRIC_TEXT = {
  sleep: {
    title: "Sleep and rest",
    help: "Hours per day with activity below 10 % of the person's own active level.",
    format: (value) => `${value.toFixed(1)} h`,
  },
  circadian_rhythm: {
    title: "Circadian rhythm",
    help: "Day-night contrast of activity (relative amplitude, 0 to 1). Lower is flatter.",
    format: (value) => value.toFixed(2),
  },
  daytime_activity: {
    title: "Daytime activity",
    help: "Share of 08:00–22:00 hours with activity of at least 25 % of the person's active level.",
    format: (value) => `${Math.round(value * 100)} %`,
  },
  heart_rate: {
    title: "Heart rate",
    help: "Resting heart rate per day.",
    format: (value) => `${Math.round(value)} bpm`,
  },
};

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function shortDate(isoDay) {
  return new Date(`${isoDay}T12:00:00Z`).toLocaleDateString([], {
    day: "numeric",
    month: "short",
  });
}

/**
 * Choose a y-range that contains the data and the band, with a little headroom.
 *
 * @param {number[]} values - Patient values.
 * @param {{p10: number, p90: number} | null} reference - Reference band.
 * @returns {[number, number]} Lower and upper bound.
 */
function yDomain(values, reference) {
  const all = [...values];
  if (reference) {
    all.push(reference.p10, reference.p90);
  }
  let low = Math.min(...all);
  let high = Math.max(...all);
  if (high - low < 1e-9) {
    low -= 0.5;
    high += 0.5;
  }
  const pad = (high - low) * 0.1;
  return [low - pad, high + pad];
}

/** Metrics that are shares or ratios can never leave 0..1; keep the axis honest. */
const BOUNDED_UNITS = new Set(["share", "0-1"]);

function clampDomain([low, high], unit) {
  return BOUNDED_UNITS.has(unit) ? [Math.max(low, 0), Math.min(high, 1)] : [low, high];
}

/**
 * Render the chart for one metric.
 *
 * @param {object} metric - A MetricEvidence object from the ModuleResult.
 * @param {HTMLElement} tooltip - Shared tooltip element positioned by the chart.
 * @returns {HTMLElement} A figure with the SVG chart and its table view.
 */
export function renderEvidenceChart(metric, tooltip) {
  const text = METRIC_TEXT[metric.name] ?? { title: metric.name, help: "", format: String };
  const figure = document.createElement("figure");
  figure.className = "evidence-chart";

  const points = (metric.patient_series ?? []).filter((point) => point.value !== null);
  if (!metric.available || points.length === 0) {
    const empty = document.createElement("p");
    empty.className = "evidence-chart__empty muted";
    empty.textContent =
      metric.name === "heart_rate"
        ? "No heart-rate data in this recording (activity-only band)."
        : "No valid days for this metric in the selected period.";
    figure.append(empty);
    return figure;
  }

  const reference = metric.reference ?? null;
  const values = points.map((point) => point.value);
  const [yMin, yMax] = clampDomain(yDomain(values, reference), metric.unit);
  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (index) =>
    MARGIN.left + (points.length === 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value) => MARGIN.top + (1 - (value - yMin) / (yMax - yMin)) * innerHeight;

  const svg = svgElement("svg", {
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
    class: "evidence-chart__svg",
    role: "img",
    "aria-label": `${text.title}: ${points.length} days. ${
      reference ? `Reference band ${text.format(reference.p10)} to ${text.format(reference.p90)}.` : ""
    }`,
  });

  // Recessive grid and y-axis labels.
  for (let tick = 0; tick <= Y_TICKS; tick += 1) {
    const value = yMin + ((yMax - yMin) * tick) / Y_TICKS;
    const ty = y(value);
    svg.append(
      svgElement("line", {
        x1: MARGIN.left,
        x2: WIDTH - MARGIN.right,
        y1: ty,
        y2: ty,
        class: "evidence-chart__grid",
      }),
    );
    const label = svgElement("text", {
      x: MARGIN.left - 6,
      y: ty + 4,
      "text-anchor": "end",
      class: "evidence-chart__axis",
    });
    label.textContent = text.format(value);
    svg.append(label);
  }

  // Reference band (p10 to p90) and median, labelled directly on the right.
  if (reference) {
    const top = y(Math.min(reference.p90, yMax));
    const bottom = y(Math.max(reference.p10, yMin));
    svg.append(
      svgElement("rect", {
        x: MARGIN.left,
        y: top,
        width: innerWidth,
        height: Math.max(bottom - top, 1),
        class: "evidence-chart__band",
      }),
      svgElement("line", {
        x1: MARGIN.left,
        x2: WIDTH - MARGIN.right,
        y1: y(reference.p50),
        y2: y(reference.p50),
        class: "evidence-chart__median",
      }),
    );
    const bandLabel = svgElement("text", {
      x: WIDTH - MARGIN.right + 6,
      y: (top + bottom) / 2 + 4,
      class: "evidence-chart__axis",
    });
    bandLabel.textContent = "typical";
    svg.append(bandLabel);
  }

  // First and last day on the x-axis.
  for (const [index, anchor] of [
    [0, "start"],
    [points.length - 1, "end"],
  ]) {
    const label = svgElement("text", {
      x: x(index),
      y: HEIGHT - 8,
      "text-anchor": points.length === 1 ? "middle" : anchor,
      class: "evidence-chart__axis",
    });
    label.textContent = shortDate(points[index].day);
    svg.append(label);
  }

  // Patient line and markers.
  svg.append(
    svgElement("polyline", {
      points: points.map((point, index) => `${x(index)},${y(point.value)}`).join(" "),
      class: "evidence-chart__line",
    }),
  );
  points.forEach((point, index) => {
    const outside = reference && (point.value < reference.p10 || point.value > reference.p90);
    const cx = x(index);
    const cy = y(point.value);
    svg.append(
      svgElement("circle", {
        cx,
        cy,
        r: MARKER_RADIUS,
        class: `evidence-chart__marker${outside ? " evidence-chart__marker--outside" : ""}`,
      }),
    );
    const hit = svgElement("circle", {
      cx,
      cy,
      r: HIT_RADIUS,
      class: "evidence-chart__hit",
      tabindex: 0,
      role: "img",
      "aria-label": `${shortDate(point.day)}: ${text.format(point.value)}${
        outside ? ", outside the typical range" : ""
      }`,
    });
    const show = () => {
      tooltip.textContent = `${shortDate(point.day)} · ${text.format(point.value)}${
        outside ? " · outside typical range" : ""
      }`;
      tooltip.hidden = false;
      const box = svg.getBoundingClientRect();
      // Keep the tooltip inside the viewport on narrow phones.
      const margin = tooltip.offsetWidth / 2 + 8;
      const left = Math.min(
        Math.max(box.left + (cx / WIDTH) * box.width, margin),
        document.documentElement.clientWidth - margin,
      );
      tooltip.style.left = `${left + window.scrollX}px`;
      tooltip.style.top = `${box.top + window.scrollY + (cy / HEIGHT) * box.height - 12}px`;
      tooltip.hidden = false;
    };
    const hide = () => {
      tooltip.hidden = true;
    };
    hit.addEventListener("mouseenter", show);
    hit.addEventListener("focus", show);
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("blur", hide);
    svg.append(hit);
  });

  figure.append(svg, renderTable(points, reference, text));
  return figure;
}

/**
 * Accessible table view with the same numbers as the chart.
 *
 * @param {Array<{day: string, value: number}>} points - Patient values.
 * @param {object | null} reference - Reference band.
 * @param {{format: (value: number) => string}} text - Metric formatting.
 * @returns {HTMLDetailsElement} Collapsed table.
 */
function renderTable(points, reference, text) {
  const details = document.createElement("details");
  details.className = "evidence-chart__table";
  const summary = document.createElement("summary");
  const outside = reference
    ? points.filter((point) => point.value < reference.p10 || point.value > reference.p90).length
    : 0;
  summary.textContent = reference
    ? `${outside} of ${points.length} days outside the typical range · show values`
    : `${points.length} days · show values`;
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  for (const label of ["Day", "Value"]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    head.append(cell);
  }
  const body = table.createTBody();
  for (const point of points) {
    const row = body.insertRow();
    row.insertCell().textContent = shortDate(point.day);
    row.insertCell().textContent = text.format(point.value);
  }
  details.append(summary, table);
  return details;
}
