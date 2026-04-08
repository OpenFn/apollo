export default ({ request, set }: { request: Request; set: { status?: number | string } }) => {
  console.log(`${request.method} ${new URL(request.url).pathname} → ${set.status ?? 200}`);
};
