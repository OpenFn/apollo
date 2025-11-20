import { installAndGen } from "@openfn/adaptor-apis";

const safeInstallAndGen = async (adaptor: string) => {
  return new Promise<any>(async (resolve, reject) => {
    try {
      const result = await installAndGen(adaptor);
      resolve(result);
    } catch (error) {
      reject(error);
    }
  });
};

export default async (port: number, payload: any) => {
  try {
    // TODO: would be neat to check and use the database first
    // (if an option is passed)

    const result: any = {
      docs: {},
      errors: [],
    };

    for (const adaptor of payload.adaptors) {
      try {
        const { docs } = await safeInstallAndGen(adaptor);
        result.docs[adaptor] = docs;
      } catch (e) {
        console.error(`Error fetching adaptor ${adaptor}:`, e);
        result.errors.push(adaptor);
      }
    }

    return result;
  } catch (error) {
    // Catch any critical errors that escape the inner try/catch
    console.error('Critical error in adaptor_apis service:', error);
    return {
      docs: {},
      errors: payload.adaptors,
      message: error instanceof Error ? error.message : String(error),
    };
  }
};
