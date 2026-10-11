import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { ApiContext, createApi } from "./api";
import { ApiError } from "./api/errors";
import type { SpeakQuestApi } from "./api/types";
import { Layout } from "./components/Layout";
import { Loading } from "./components/States";
import { ChallengeIndex } from "./pages/ChallengeIndex";

const CuePage = lazy(() => import("./pages/CuePage"));
const TakePage = lazy(() => import("./pages/TakePage"));
const MePage = lazy(() => import("./pages/MePage"));

export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

function NotFound() {
  return (
    <section className="px-[var(--gutter)] py-16">
      <h1 className="display text-xl">Dead air.</h1>
      <p className="mt-4">There's nothing on this channel.</p>
      <Link className="btn mt-6" to="/">
        Back to the scripts
      </Link>
    </section>
  );
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => (error instanceof ApiError ? error.retryable && count < 2 : count < 2),
      },
    },
  });
}

export function App({ api: injected, router = true }: { api?: SpeakQuestApi; router?: boolean }) {
  const [api] = useState(() => injected ?? createApi());
  const [client] = useState(makeQueryClient);
  const routes = (
    <Layout>
      <Suspense fallback={<Loading what="the page" />}>
        <Routes>
          <Route path="/" element={<ChallengeIndex />} />
          <Route path="/c/:id" element={<CuePage />} />
          <Route path="/take/:analysisId" element={<TakePage />} />
          <Route path="/me" element={<MePage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  );
  return (
    <ApiContext.Provider value={api}>
      <QueryClientProvider client={client}>
        {router ? <BrowserRouter future={ROUTER_FUTURE}>{routes}</BrowserRouter> : routes}
      </QueryClientProvider>
    </ApiContext.Provider>
  );
}
