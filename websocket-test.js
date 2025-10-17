const socket = new WebSocket("ws://localhost:3000/services/echo");
console.log("connecting");

socket.addEventListener("message", ({ type, data }) => {
  const evt = JSON.parse(data);

  if (evt.event === "complete") {
    console.log("done!");
    console.log(evt.data);
  } else if (evt.event === "log") {
    console.log(" >> ", evt.data);
  }
});

socket.addEventListener("open", (event) => {
  console.log("socket open!");

  socket.send(
    JSON.stringify({
      event: "start",
      data: { a: 22 },
    })
  );
});
