// Calls the echo service repeatedly against a running server and logs timings
// Usage: APOLLO_ENDPOINT=http://localhost:3000 bun tools/capacity-test.js [iterations]
const endpoint = process.env.APOLLO_ENDPOINT ?? "http://localhost:3000";
const api_key = process.env.AI_ASSISTANT_API_KEY;
const iterations = process.argv[2] ? Number(process.argv[2]) : 100;

if (!Number.isInteger(iterations) || iterations < 1) {
  console.error(`invalid iteration count: ${process.argv[2]}`);
  process.exit(1);
}

if (!endpoint) {
  console.error("APOLLO_ENDPOINT is not set");
  process.exit(1);
}

const url = `${endpoint.replace(/\/$/, "")}/services/echo`;

const start = performance.now();

let succeeded = 0;

const call = async (i) => {
  const t = performance.now();
  let status;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ n: i, api_key }),
    });
    await res.text();
    status = res.status;
    if (res.ok) succeeded++;
  } catch (e) {
    status = `error (${e.message})`;
  }
  const ms = (performance.now() - t).toFixed(0);
  console.log(`#${i} ${ms}ms ${status}`);
};

await Promise.all(Array.from({ length: iterations }, (_, i) => call(i + 1)));

const total = ((performance.now() - start) / 1000).toFixed(2);
const pct = ((succeeded / iterations) * 100).toFixed(1);
console.log(`completed ${iterations} requests in ${total}s`);
console.log(`succeeded: ${succeeded}/${iterations} (${pct}%)`);
