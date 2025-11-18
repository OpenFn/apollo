import { installAndGen } from "@openfn/adaptor-apis";

export default async (port: number, payload: any) => {
  // TODO: would be neat to check and use the database first
  // (if an option is passed)

  const result: any = {
    docs: {},
    errors: [],
  };
  for (const adaptor of payload.adaptors) {
    try {
      const { docs } = await installAndGen(adaptor);
      result.docs[adaptor] = docs;
    } catch (e) {
      console.log(e);
      result.errors.push(adaptor);
    }
  }
  return result;
};
