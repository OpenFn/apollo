import { loadQuestions } from "./load-questions";

const questions = await loadQuestions();
console.log(questions);
process.exit(0);
const results = [];

for (const q of questions) {
  console.log(q);

  const payload = {
    content: q.question,
    history: [],
    context: {
      adaptor: q.adaptor,
      input: q.input ?? {},
      expression: q.code,
    },
    api_key: process.env.ANTHROPIC_API_KEY,
  };
  const response = await fetch({
    url: "http://localhost:3000/services/job_chat",
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "content-type": "application/json",
    },
  });
  const result = await response.json();

  results.push({
    q: q.question,
    a: result.response,
  });
}

const output = [];
for (const { q, a } of results) {
  output.push(`> ${q}

${a}`);
}
Bun.write("output.md", output.join("\n---\n"));
