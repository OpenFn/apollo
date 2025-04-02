import { loadQuestions } from "./load-questions";

const questions = await loadQuestions();

console.log(`Asking ${questions.length} questions...`);
const results = [];

for (const q of questions) {
  const payload = {
    content: q.question ?? q.message,
    history: [],
    context: {
      adaptor: q.adaptor,
      input: q.input ?? {},
      expression: q.code,
    },
    api_key: process.env.ANTHROPIC_API_KEY,
  };
  console.log("Q:", payload.content);
  console.log();
  const response = await fetch({
    url: "http://localhost:3000/services/job_chat",
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "content-type": "application/json",
    },
  });
  const result = await response.json();

  if (!result.response) {
    console.error("Error in response!!");
    console.error(result);
  } else {
    console.log(result.response);
    results.push({
      q: q.question,
      a: result.response,
    });
    console.log();
    console.log();
  }
}

const output = [];
for (const { q, a } of results) {
  output.push(`> **${q}

${a}`);
}

console.log(`Writing  ${output.length} answers to output.md`);
Bun.write("output.md", output.join("\n---\n"));
