import { readFile, readdir } from "node:fs/promises"; // no bun api yet

export type ModuleDescription = {
  name: string;
  type: "py" | "ts";

  handler?: (
    port: number,
    payload: any,
    onLog?: (str: string) => void
  ) => Promise<any>;
  summary?: string;
  readme?: string;
};

export default async (location: string): Promise<ModuleDescription[]> => {
  const dirs = await readdir(location, { withFileTypes: true });
  const services = dirs.filter(
    (dirent) => dirent.isDirectory() && !dirent.name.startsWith("_")
  );

  const result: ModuleDescription[] = [];
  for (const srv of services) {
    let type: "py" | "ts";
    let handler;

    const hasPyIndex = await Bun.file(
      `${location}/${srv.name}/${srv.name}.py`
    ).exists();
    if (hasPyIndex) {
      type = "py";
    } else {
      const hasTsIndex = await Bun.file(
        `${location}/${srv.name}/${srv.name}.ts`
      ).exists();
      if (hasTsIndex) {
        type = "ts";
        const mod = await import(`${location}/${srv.name}/${srv.name}.ts`);
        handler = mod.default;
      } else {
        console.warn("WARNING: no index file found for ", srv.name);
        continue;
      }
    }

    // if no index file, skip it with a warning
    const s: ModuleDescription = {
      name: srv.name,
      // is this a python or js service?
      type,
      handler,
    };

    try {
      const rm = await readFile(`${location}/${srv.name}/README.md`, "utf8");

      const lines = rm.split("\n");
      // for a summary, find the first non-empty, non-title line
      let summary = "";
      for (const l of lines) {
        if (l.length && !l.startsWith("#")) {
          summary += " " + l;
        } else if (summary) {
          break;
        }
      }

      s.readme = rm;
      s.summary = summary;
    } catch (e) {
      s.readme = "No readme file found for this service";
      s.summary = "Service description not available";
    }

    result.push(s);
  }

  return result.sort((a, b) => {
    if (a.name > b.name) {
      return 1;
    }
    if (a.name < b.name) {
      return -1;
    }
    return 0;
  });
};
