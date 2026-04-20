export default ({
  request,
  set,
  start,
}: {
  request: Request;
  set: { status?: number | string };
  start: number;
}) => {
  const duration = Date.now() - start;
  const path = new URL(request.url).pathname;
  if (path !== "/") {
    console.log(
      `http: ${request.method} ${new URL(request.url).pathname} → ${
        set.status ?? 200
      } in ${duration}ms`
    );
  }
};
