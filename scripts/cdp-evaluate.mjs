import process from "node:process";

const [, , wsUrl, ...expressionParts] = process.argv;

if (!wsUrl || expressionParts.length === 0) {
  console.error("Usage: node scripts/cdp-evaluate.mjs <ws-url> <expression>");
  process.exit(1);
}

const expression = expressionParts.join(" ");
const socket = new WebSocket(wsUrl);

const result = await new Promise((resolve, reject) => {
  const timer = setTimeout(() => {
    reject(new Error("Timed out waiting for CDP response"));
  }, 15000);

  socket.addEventListener("open", () => {
    socket.send(
      JSON.stringify({
        id: 1,
        method: "Runtime.evaluate",
        params: {
          expression,
          awaitPromise: true,
          returnByValue: true,
        },
      }),
    );
  });

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.id !== 1) {
      return;
    }

    clearTimeout(timer);
    resolve(payload);
  });

  socket.addEventListener("error", (event) => {
    clearTimeout(timer);
    reject(event.error ?? new Error("WebSocket error"));
  });
});

socket.close();
console.log(JSON.stringify(result));
