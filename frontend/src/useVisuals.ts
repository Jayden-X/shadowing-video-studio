import { useEffect, useRef, useState } from "react";
import {
  getVisualAssets,
  getVisualStatus,
  uploadVisualAsset,
  VisualApiError,
  type VisualAsset,
  type VisualKind,
  type VisualStatus,
} from "./visualApi";

const STATUS_LIMIT_MS = 15_000;
const DEFAULT_ERROR = "The local image library could not be loaded. Refresh to retry.";

export function useVisuals() {
  const [status, setStatus] = useState<VisualStatus | null>(null);
  const [assets, setAssets] = useState<VisualAsset[]>([]);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearTimer() {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }

  function refresh() {
    controller.current?.abort();
    clearTimer();
    const request = new AbortController();
    controller.current = request;
    const token = ++sequence.current;
    setChecking(true);
    setError("");
    timer.current = setTimeout(() => {
      if (mounted.current && token === sequence.current) {
        setError("Image library check timed out. Refresh to retry; current selections are preserved.");
      }
      request.abort();
    }, STATUS_LIMIT_MS);
    getVisualStatus(request.signal).then(async (result) => {
      if (!mounted.current || token !== sequence.current || request.signal.aborted) return;
      setStatus(result);
      const library = await getVisualAssets(request.signal);
      if (mounted.current && token === sequence.current && !request.signal.aborted) setAssets(library);
    }).catch((value: unknown) => {
      if (!mounted.current || token !== sequence.current || request.signal.aborted) return;
      setError(value instanceof VisualApiError ? value.message : DEFAULT_ERROR);
    }).finally(() => {
      if (token !== sequence.current) return;
      clearTimer();
      controller.current = null;
      if (mounted.current) setChecking(false);
    });
  }

  useEffect(() => {
    mounted.current = true;
    refresh();
    return () => {
      mounted.current = false;
      sequence.current += 1;
      controller.current?.abort();
      clearTimer();
    };
  }, []);

  async function upload(file: File, kind: VisualKind, signal?: AbortSignal): Promise<VisualAsset> {
    if (!status?.available || checking || error) {
      throw new VisualApiError("The local image library is not ready. Refresh it before uploading.");
    }
    if (!status.formats.includes(file.type as VisualStatus["formats"][number])) {
      throw new VisualApiError(`Choose a supported image: ${status.formats.join(", ")}.`);
    }
    if (file.size > status.maxUploadBytes) {
      throw new VisualApiError(`Choose an image smaller than ${(status.maxUploadBytes / (1024 * 1024)).toFixed(0)} MiB.`);
    }
    const asset = await uploadVisualAsset(file, kind, signal);
    if (mounted.current) {
      setAssets((current) => [asset, ...current.filter((item) => item.id !== asset.id)]);
    }
    return asset;
  }

  function selectionProblem(selections: readonly { id: string; kind: VisualKind }[]): string | null {
    if (selections.length === 0) return null;
    if (checking) return "Checking the selected image library. Wait for it to finish before rendering.";
    if (!status) return error || "The selected image library could not be checked. Refresh before rendering.";
    if (error) return error;
    for (const selection of selections) {
      const asset = assets.find((item) => item.id === selection.id);
      if (!asset) return "A selected image is missing from the library. Refresh, then re-upload it or choose another image.";
      if (asset.kind !== selection.kind) return "A selected image is assigned to the wrong visual role. Choose a matching library image.";
      if (!asset.available) return asset.reason ?? `“${asset.name}” is unavailable. Re-upload it or choose another image.`;
    }
    return null;
  }

  return { status, assets, checking, error, refresh, upload, selectionProblem };
}
