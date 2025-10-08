const url = "http://localhost:3000/services/job_chat/stream";
console.log("Starting HTTP stream request...");

const payload = {
  content: "what are collections?",
  history: [],
  context: {
    expression: "// write your job code here",
    adaptor: "@openfn/language-salesforce@4.6.10",
    input: null,
    output: null,
    log: null,
  },
  api_key: process.env.AI_ASSISTANT_API_KEY,
};

fetch(url, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify(payload),
})
  .then((response) => {
    console.log("Connected!");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    function readStream() {
      reader.read().then(({ done, value }) => {
        if (done) {
          console.log("Stream closed");
          return;
        }

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        let eventType;
        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.substring(6).trim();
            continue;
          }

          if (line.startsWith("data:")) {
            const data = line.substring(5).trim();

            try {
              const parsed = JSON.parse(data);

              console.log(`${eventType}:`, parsed);
            } catch (e) {
              // Skip empty or malformed data lines
            }
          }
        }

        readStream();
      });
    }

    readStream();
  })
  .catch((error) => {
    console.error("Connection failed:", error);
  });
