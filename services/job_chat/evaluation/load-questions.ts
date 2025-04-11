export type Question = {
  question?: string;
  adaptor?: string;
  code?: string;
  input?: string;
};

export const loadQuestions = async (
  path = "questions.md"
): Promise<Question[]> => {
  const foo = Bun.file(path);

  const questionsContent = await foo.text(); // contents as a string

  const lines = questionsContent.split("\n").filter((l) => l.length);

  const questions = [];

  let q: Question = {};
  let content: string[] = [];
  let key: keyof Question = "";
  while (lines.length) {
    const next = lines.shift();

    if (next?.startsWith("---")) {
      // start of a new question, so re-initialise
      for (const key in q) {
        q[key] = q[key].join("\n");
      }
      questions.push(q);
      q = {};
      continue;
    }

    if (next?.startsWith("#")) {
      // set a new content key
      key = next.replaceAll("#", "").trim();
      content = [];
      q[key] = content;
    } else {
      content.push(next?.trim());
    }
  }
  // Now add the last question
  for (const key in q) {
    q[key] = q[key].join("\n");
  }
  questions.push(q);

  return questions;
};
