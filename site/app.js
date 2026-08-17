const SVG_NS = "http://www.w3.org/2000/svg";
const TOTAL_WORKLOAD = "All workloads (total)";

const metricMetadata = {
  total_time_ms: { label: "Total time", unit: "ms" },
  startup_ms: { label: "Startup", unit: "ms" },
  average_response_ms: { label: "Average response", unit: "ms" },
  max_residency_mb: { label: "Max residency", unit: "MB" },
  allocated_mb: { label: "Allocated memory", unit: "MB" },
};

const elements = {
  latestCommit: document.querySelector("#latest-commit"),
  latestTime: document.querySelector("#latest-time"),
  commitCount: document.querySelector("#commit-count"),
  runCount: document.querySelector("#run-count"),
  successRate: document.querySelector("#success-rate"),
  example: document.querySelector("#example-select"),
  ghc: document.querySelector("#ghc-select"),
  benchmark: document.querySelector("#benchmark-select"),
  metric: document.querySelector("#metric-select"),
  pointCount: document.querySelector("#point-count"),
  chart: document.querySelector("#chart"),
  emptyChart: document.querySelector("#empty-chart"),
  comparisonCommits: document.querySelector("#comparison-commits"),
  regressionCards: document.querySelector("#regression-cards"),
  recentRuns: document.querySelector("#recent-runs"),
};

let rows = [];

function unique(values) {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
}

function aggregateWorkloads(results) {
  const samples = results.reduce((total, result) => total + result.samples, 0);
  const successfulCases = results.filter((result) => result.success).length;
  return {
    benchmark: TOTAL_WORKLOAD,
    success: successfulCases === results.length,
    successfulCases,
    totalCases: results.length,
    samples,
    startup_ms: results.reduce((total, result) => total + result.startup_ms, 0),
    average_response_ms: samples === 0 ? 0 : results.reduce(
      (total, result) => total + result.average_response_ms * result.samples,
      0,
    ) / samples,
    total_time_ms: results.reduce((total, result) => total + result.total_time_ms, 0),
    max_residency_mb: Math.max(...results.map((result) => result.max_residency_mb)),
    allocated_mb: results.reduce((total, result) => total + result.allocated_mb, 0),
    isAggregate: true,
  };
}

function flatten(history) {
  return history.measurements.flatMap((entry) => {
    const context = {
      id: entry.id,
      measuredAt: entry.measurement.timestamp,
      ghc: entry.measurement.ghc,
      example: entry.measurement.example,
      commit: entry.upstream.commit,
      commitUrl: entry.upstream.commit_url,
      runUrl: entry.workflow.run_url,
    };
    return [
      { ...aggregateWorkloads(entry.results), ...context },
      ...entry.results.map((result) => ({ ...result, ...context, isAggregate: false })),
    ];
  });
}

function setOptions(select, values) {
  const previous = select.value;
  select.replaceChildren(...values.map((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    return option;
  }));
  select.value = values.includes(previous) ? previous : (values[0] || "");
}

function refreshDependentControls(origin) {
  if (origin === "initial") {
    setOptions(elements.example, unique(rows.map((row) => row.example)));
  }
  if (origin === "initial" || origin === "example") {
    setOptions(elements.ghc, unique(rows.filter((row) => row.example === elements.example.value).map((row) => row.ghc)));
  }
  if (["initial", "example", "ghc"].includes(origin)) {
    setOptions(
      elements.benchmark,
      unique(rows
        .filter((row) => row.example === elements.example.value && row.ghc === elements.ghc.value)
        .map((row) => row.benchmark)),
    );
  }
  renderSelection();
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function formatMetric(value, field) {
  if (!Number.isFinite(value)) return "—";
  const digits = Math.abs(value) >= 100 ? 0 : 1;
  return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })} ${metricMetadata[field].unit}`;
}

function shortSha(commit) {
  return commit.slice(0, 8);
}

function selectionRows() {
  return rows
    .filter((row) => (
      row.example === elements.example.value
      && row.ghc === elements.ghc.value
      && row.benchmark === elements.benchmark.value
    ))
    .sort((left, right) => new Date(left.measuredAt) - new Date(right.measuredAt));
}

function svgNode(name, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  if (text) node.textContent = text;
  return node;
}

function drawChart(selected) {
  const field = elements.metric.value;
  const points = selected.filter(
    (row) => (row.success || row.isAggregate) && Number.isFinite(row[field]),
  );
  elements.pointCount.textContent = `${points.length} point${points.length === 1 ? "" : "s"}`;
  elements.chart.replaceChildren();
  elements.chart.hidden = points.length === 0;
  elements.emptyChart.hidden = points.length !== 0;
  if (!points.length) return;

  const width = 960;
  const height = 360;
  const margin = { top: 24, right: 26, bottom: 54, left: 78 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = points.map((point) => point[field]);
  let min = Math.min(...values);
  let max = Math.max(...values);
  const padding = Math.max((max - min) * 0.12, Math.abs(max || 1) * 0.03);
  min = Math.max(0, min - padding);
  max += padding;
  if (max === min) max = min + 1;

  const times = points.map((point) => new Date(point.measuredAt).getTime());
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const x = (index) => margin.left + (
    maxTime === minTime ? plotWidth / 2 : (times[index] - minTime) * plotWidth / (maxTime - minTime)
  );
  const y = (value) => margin.top + (max - value) * plotHeight / (max - min);

  const defs = svgNode("defs");
  const gradient = svgNode("linearGradient", { id: "area-gradient", x1: "0", y1: "0", x2: "0", y2: "1" });
  gradient.append(svgNode("stop", { offset: "0%", "stop-color": "#62e3b4", "stop-opacity": "0.22" }));
  gradient.append(svgNode("stop", { offset: "100%", "stop-color": "#62e3b4", "stop-opacity": "0" }));
  defs.append(gradient);
  elements.chart.append(defs);

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = max - tick * (max - min) / 4;
    const yPosition = y(value);
    elements.chart.append(svgNode("line", {
      x1: margin.left, x2: width - margin.right, y1: yPosition, y2: yPosition, class: "grid-line",
    }));
    elements.chart.append(svgNode("text", {
      x: margin.left - 12, y: yPosition + 4, "text-anchor": "end", class: "axis-label",
    }, formatMetric(value, field)));
  }

  const path = points.map((point, index) => `${index ? "L" : "M"}${x(index)},${y(point[field])}`).join(" ");
  const area = `${path} L${x(points.length - 1)},${height - margin.bottom} L${x(0)},${height - margin.bottom} Z`;
  elements.chart.append(svgNode("path", { d: area, class: "chart-area" }));
  elements.chart.append(svgNode("path", { d: path, class: "chart-line" }));

  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])]
    .sort((left, right) => left - right);
  labelIndexes.forEach((index) => {
    elements.chart.append(svgNode("text", {
      x: x(index), y: height - 20, "text-anchor": index === 0 ? "start" : (index === points.length - 1 ? "end" : "middle"), class: "axis-label",
    }, new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(points[index].measuredAt))));
  });

  points.forEach((point, index) => {
    const partial = point.isAggregate && !point.success;
    const circle = svgNode("circle", {
      cx: x(index),
      cy: y(point[field]),
      r: 5,
      class: `chart-point${partial ? " chart-point-partial" : ""}`,
    });
    const coverage = point.isAggregate
      ? ` · ${point.successfulCases}/${point.totalCases} workloads passed`
      : "";
    circle.append(svgNode(
      "title",
      {},
      `${shortSha(point.commit)} · ${formatMetric(point[field], field)} · ${formatDate(point.measuredAt)}${coverage}`,
    ));
    elements.chart.append(circle);
  });
}

function latestDistinctCommits(selected) {
  const latestByCommit = new Map();
  selected.forEach((row) => latestByCommit.set(row.commit, row));
  return [...latestByCommit.values()].sort((left, right) => new Date(right.measuredAt) - new Date(left.measuredAt)).slice(0, 2);
}

function renderRegressions(selected) {
  const [latest, previous] = latestDistinctCommits(
    selected.filter((row) => row.success || row.isAggregate),
  );
  elements.regressionCards.replaceChildren();
  if (!latest || !previous) {
    elements.comparisonCommits.textContent = "Not enough distinct commits";
    ["Startup", "Total time", "Max residency"].forEach((label) => {
      const card = document.createElement("div");
      card.className = "regression-card";
      const caption = document.createElement("span");
      caption.textContent = label;
      const value = document.createElement("strong");
      value.textContent = "—";
      card.append(caption, value);
      elements.regressionCards.append(card);
    });
    return;
  }

  const partial = [latest, previous].some((row) => row.isAggregate && !row.success);
  elements.comparisonCommits.textContent = (
    `${shortSha(latest.commit)} vs ${shortSha(previous.commit)}`
    + `${partial ? " · partial pass coverage" : ""}`
  );
  [
    ["startup_ms", "Startup"],
    ["total_time_ms", "Total time"],
    ["max_residency_mb", "Max residency"],
  ].forEach(([field, label]) => {
    const delta = previous[field] === 0 ? NaN : (latest[field] / previous[field] - 1) * 100;
    const card = document.createElement("div");
    const classification = !Number.isFinite(delta) ? "" : delta <= -5 ? "good" : delta >= 5 ? "bad" : "warn";
    card.className = `regression-card ${classification}`;
    const caption = document.createElement("span");
    caption.textContent = label;
    const value = document.createElement("strong");
    value.textContent = Number.isFinite(delta) ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%` : "—";
    const detail = document.createElement("span");
    detail.textContent = `${formatMetric(latest[field], field)} now`;
    card.append(caption, value, detail);
    elements.regressionCards.append(card);
  });
}

function renderTable(selected) {
  const field = elements.metric.value;
  elements.recentRuns.replaceChildren();
  [...selected].reverse().slice(0, 12).forEach((row) => {
    const tr = document.createElement("tr");
    const date = document.createElement("td");
    date.textContent = formatDate(row.measuredAt);
    const commitCell = document.createElement("td");
    const commitLink = document.createElement("a");
    commitLink.href = row.commitUrl;
    const code = document.createElement("code");
    code.textContent = shortSha(row.commit);
    commitLink.append(code);
    commitCell.append(commitLink);
    const value = document.createElement("td");
    value.textContent = formatMetric(row[field], field);
    const result = document.createElement("td");
    if (row.isAggregate) {
      result.className = row.success ? "result-good" : "result-warn";
      result.textContent = `${row.successfulCases}/${row.totalCases} passed`;
    } else {
      result.className = row.success ? "result-good" : "result-bad";
      result.textContent = row.success ? "Passed" : "Failed";
    }
    const run = document.createElement("td");
    const runLink = document.createElement("a");
    runLink.href = row.runUrl;
    runLink.textContent = "Actions ↗";
    run.append(runLink);
    tr.append(date, commitCell, value, result, run);
    elements.recentRuns.append(tr);
  });
}

function renderSelection() {
  const selected = selectionRows();
  drawChart(selected);
  renderRegressions(selected);
  renderTable(selected);
}

function renderOverview(history) {
  const measurements = [...history.measurements].sort(
    (left, right) => new Date(right.measurement.timestamp) - new Date(left.measurement.timestamp),
  );
  const latest = measurements[0];
  if (latest) {
    elements.latestCommit.textContent = shortSha(latest.upstream.commit);
    elements.latestCommit.href = latest.upstream.commit_url;
    elements.latestTime.textContent = `${formatDate(latest.measurement.timestamp)} · ${latest.upstream.ref}`;
  }
  elements.commitCount.textContent = new Set(measurements.map((item) => item.upstream.commit)).size;
  elements.runCount.textContent = new Set(measurements.map((item) => [
    item.workflow.repository,
    item.workflow.run_id,
    item.workflow.run_attempt,
  ].join(":"))).size;
  const cases = measurements.flatMap((item) => item.results);
  const successes = cases.filter((item) => item.success).length;
  elements.successRate.textContent = cases.length ? `${(successes / cases.length * 100).toFixed(1)}%` : "—";
}

async function start() {
  try {
    const response = await fetch("data/history.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`history request failed: ${response.status}`);
    const history = await response.json();
    if (history.schema_version !== 1 || !Array.isArray(history.measurements)) {
      throw new Error("unsupported history schema");
    }
    rows = flatten(history);
    renderOverview(history);
    refreshDependentControls("initial");
  } catch (error) {
    console.error(error);
    elements.emptyChart.hidden = false;
    elements.emptyChart.textContent = "The benchmark history could not be loaded.";
  }
}

elements.example.addEventListener("change", () => refreshDependentControls("example"));
elements.ghc.addEventListener("change", () => refreshDependentControls("ghc"));
elements.benchmark.addEventListener("change", renderSelection);
elements.metric.addEventListener("change", renderSelection);

start();
