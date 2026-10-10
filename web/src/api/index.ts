import { createContext, useContext } from "react";
import { DemoApi } from "./demo";
import { HttpApi } from "./http";
import type { SpeakQuestApi } from "./types";

export function createApi(env: { VITE_API_URL?: string; VITE_DEMO?: string } = import.meta.env): SpeakQuestApi {
  const base = env.VITE_API_URL?.trim();
  if (!base || env.VITE_DEMO === "1") return new DemoApi();
  return new HttpApi({ baseUrl: base });
}

export const ApiContext = createContext<SpeakQuestApi | null>(null);

export function useApi(): SpeakQuestApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi outside <ApiContext.Provider>");
  return api;
}
