const $ = (selector, root = document) => root.querySelector(selector);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function api(path, consumer, options = {}) {
  const headers = { "X-Demo-Consumer": consumer, ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(`/proxy${path}`, { ...options, headers });
  const text = await response.text();
  let body;
  try { body = JSON.parse(text); } catch { body = { raw: text }; }
  if (!response.ok) throw Object.assign(new Error(`HTTP ${response.status}`), { status: response.status, body });
  return { body, runId: response.headers.get("X-AgentHub-Run-Id") };
}

function render(result, elapsed) {
  const answer = result?.output?.answer ?? result?.body?.output?.answer ?? result?.choices?.[0]?.message?.content ?? result?.output?.[0]?.content?.[0]?.text ?? result?.output_text;
  const sources = result?.output?.sources ?? result?.body?.output?.sources ?? [];
  const compact = answer ? { answer, sources, status: result.status || result.body?.status } : result;
  return `${JSON.stringify(compact, null, 2)}\n\n${elapsed} ms`;
}

async function pollRun(runId, consumer) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const { body } = await api(`/v1/runs/${runId}`, consumer);
    if (["completed", "failed", "cancelled", "timed_out", "waiting_approval"].includes(body.status)) return body;
    await sleep(750);
  }
  throw new Error("Run polling timeout");
}

async function runCard(card) {
  const button = $(".run", card);
  const result = $(".result", card);
  const latency = $(".latency", card);
  const consumer = card.dataset.consumer;
  const model = card.dataset.model;
  const background = card.dataset.background === "true";
  const query = $("textarea", card).value.trim();
  button.disabled = true;
  card.classList.add("running");
  result.textContent = "İstek gönderiliyor…";
  const started = performance.now();
  try {
    const request = await api("/v1/responses", consumer, {
      method: "POST",
      headers: { "Idempotency-Key": `demo-${model}-${crypto.randomUUID()}` },
      body: JSON.stringify({ model, input: query, background }),
    });
    let body = request.body;
    const runId = request.runId || body?.metadata?.run_id;
    if (background && runId) {
      result.textContent = `Run ${runId}\nDurum izleniyor…`;
      body = await pollRun(runId, consumer);
    } else if (runId) {
      body = (await api(`/v1/runs/${runId}`, consumer)).body;
    }
    const elapsed = Math.round(performance.now() - started);
    result.textContent = render(body, elapsed);
    latency.textContent = `${elapsed} ms`;
    card.classList.add("success");
  } catch (error) {
    const elapsed = Math.round(performance.now() - started);
    result.textContent = JSON.stringify(error.body || { error: error.message }, null, 2);
    latency.textContent = `${elapsed} ms`;
    card.classList.add("failed");
  } finally {
    button.disabled = false;
    card.classList.remove("running");
  }
}

document.querySelectorAll(".scenario .run").forEach((button) => button.addEventListener("click", () => runCard(button.closest(".scenario"))));
$("#run-all").addEventListener("click", async () => {
  for (const card of document.querySelectorAll(".scenario")) await runCard(card);
});
$("#deny-test").addEventListener("click", async () => {
  const target = $("#deny-result");
  try {
    await api("/v1/responses", "operations", { method: "POST", body: JSON.stringify({ model: "wikipedia-qa", input: "İstanbul nedir?", background: false }) });
    target.textContent = "HATA: çağrı beklenmedik şekilde kabul edildi.";
  } catch (error) {
    target.textContent = error.status === 403 ? `PASS · HTTP 403\n${JSON.stringify(error.body, null, 2)}` : JSON.stringify(error.body || { error: error.message }, null, 2);
  }
});

fetch("/demo-config").then((response) => response.json()).then((config) => {
  $("#gateway-status").textContent = `${Object.keys(config.consumers).length} consumer hazır · ${config.wikipedia?.language || "tr"}.wikipedia`;
}).catch(() => { $("#gateway-status").textContent = "Demo yapılandırması okunamadı"; });
