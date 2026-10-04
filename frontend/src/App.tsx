import { useEffect, useRef, useState } from "react";

import { SentenceSpeech, SpeechControls } from "./SpeechControls";
import { useSpeech } from "./useSpeech";
import { VideoControls } from "./VideoControls";
import { useVideo } from "./useVideo";
import { useVisuals } from "./useVisuals";
import { useVisualSelections } from "./useVisualSelections";
import { BackgroundImageControls, SentenceIllustrationPicker } from "./VisualAssets";
import { ProjectCleanup, RetainedResources } from "./ProjectCleanup";
import { VisualLibraryCleanup } from "./VisualLibraryCleanup";
import type { ProjectCleanupResult } from "./cleanupApi";

import {
  getBackendHealth,
  getTextProviders,
  prepareText,
  TextApiError,
  type TextProposal,
  type TextProvider,
  type TextProviderId,
} from "./api";
import {
  createSentenceDocument,
  createSentenceDocumentFromProposal,
  deleteSentence,
  insertSentenceAfter,
  mergeWithPrevious,
  moveSentence,
  splitSentence,
  updateSentenceText,
  MAX_SOURCE_LENGTH,
  type SentenceDocument,
  type SentenceId,
} from "./domain/sentences";
import {
  createOpaqueToken,
  createProject,
  getProject,
  listProjects,
  ProjectApiError,
  saveProject,
  type ProjectDetail,
  type ProjectRecord,
  type ProjectSnapshot,
  type ProjectSubmissionContext,
  type ProjectSummary,
} from "./projectApi";
import {
  forgetPendingSubmission,
  getLastProjectId,
  pendingSubmissionsFor,
  rememberPendingSubmission,
  rememberProjectAssets,
  setLastProjectId,
} from "./projectCache";

type BackendState = "checking" | "online" | "offline";
type PreparationMode = "manual" | "ai";
type Replacement = { kind: "manual"; source: string } | { kind: "ai"; proposal: TextProposal };
type ProjectNavigation = { kind: "new" } | { kind: "open"; projectId: string };
type SaveStatus = "loading" | "unsaved" | "saving" | "saved" | "failed";
type AppPage = "create" | "resources";
type PendingCreate = { name: string; snapshot: ProjectSnapshot; key: string; operationToken: string };
type PendingSave = { projectId: string; name: string; snapshot: ProjectSnapshot; key: string; expectedRevision: number; operationToken: string };
const AI_REQUEST_TIMEOUT_MS = 120_000;

function projectStateKey(name: string, snapshot: ProjectSnapshot): string {
  return JSON.stringify({ name, snapshot });
}

export default function App() {
  const speech = useSpeech();
  const video = useVideo();
  const visuals = useVisuals();
  const visualSelectionState = useVisualSelections();
  const { backgroundAssetId, illustrationsBySentence } = visualSelectionState.selections;
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [sourceDraft, setSourceDraft] = useState("");
  const [sentenceDocument, setSentenceDocument] = useState(() => createSentenceDocument(""));
  const [hasPrepared, setHasPrepared] = useState(false);
  const [replacement, setReplacement] = useState<Replacement | null>(null);
  const [notice, setNotice] = useState("");
  const [mode, setMode] = useState<PreparationMode>("manual");
  const [providers, setProviders] = useState<TextProvider[]>([]);
  const [providerStatus, setProviderStatus] = useState<BackendState>("checking");
  const [selectedProvider, setSelectedProvider] = useState<TextProviderId | "">("");
  const [proposal, setProposal] = useState<TextProposal | null>(null);
  const [aiPending, setAiPending] = useState(false);
  const [aiError, setAiError] = useState("");
  const [documentId, setDocumentId] = useState(createOpaqueToken);
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectName, setProjectName] = useState("Untitled project");
  const [projectLoadState, setProjectLoadState] = useState<BackendState>("checking");
  const [projectError, setProjectError] = useState("");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("loading");
  const [saveError, setSaveError] = useState("");
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [generationPreparing, setGenerationPreparing] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<ProjectNavigation | null>(null);
  const [cleanupDialogOpen, setCleanupDialogOpen] = useState(false);
  const [imageCleanupDialogOpen, setImageCleanupDialogOpen] = useState(false);
  const [page, setPage] = useState<AppPage>("create");
  const [resourceRefreshSignal, setResourceRefreshSignal] = useState(0);
  const [lastProjectId, setLastProjectIdState] = useState<string | null>(getLastProjectId);
  const sentenceInputs = useRef(new Map<SentenceId, HTMLTextAreaElement>());
  const prepareButton = useRef<HTMLButtonElement>(null);
  const applyButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  const confirmationOrigin = useRef<PreparationMode>("manual");
  const activeRequest = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);
  const requestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeProject = useRef<ProjectRecord | null>(null);
  const detailRef = useRef<ProjectDetail | null>(null);
  const snapshotRef = useRef<ProjectSnapshot | null>(null);
  const projectNameRef = useRef(projectName);
  const lastAcknowledgedKey = useRef<string | null>(null);
  const pendingCreate = useRef<PendingCreate | null>(null);
  const pendingSave = useRef<PendingSave | null>(null);
  const saveQueue = useRef<Promise<unknown> | null>(null);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const projectLoadSequence = useRef(0);
  const hydrating = useRef(false);
  const latestSnapshot = {
    version: 1 as const,
    documentId,
    sourceDraft,
    document: sentenceDocument,
    hasPrepared,
    mode,
    voice: speech.selectedVoice || speech.capabilities?.defaultVoice || "Aiden",
    backgroundAssetId,
    illustrationsBySentence: illustrationsBySentence as Record<SentenceId, string>,
  } satisfies ProjectSnapshot;
  const latestKey = projectStateKey(projectName, latestSnapshot);
  snapshotRef.current = latestSnapshot;
  projectNameRef.current = projectName;

  function rememberRecord(record: ProjectRecord) {
    activeProject.current = record;
    setProject(record);
    setProjectName(record.name);
    projectNameRef.current = record.name;
    setProjects((current) => [record, ...current.filter((item) => item.id !== record.id)]
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)));
    setLastProjectId(record.id);
    setLastProjectIdState(record.id);
  }

  function rememberDetail(detail: ProjectDetail) {
    detailRef.current = detail;
    setProjectDetail(detail);
  }

  function updateKnownRevision(projectId: string, revision: number) {
    setProjects((current) => current.map((item) => item.id === projectId ? { ...item, revision } : item));
    const current = activeProject.current;
    if (current?.id === projectId && revision >= current.revision) {
      const updated = { ...current, revision };
      activeProject.current = updated;
      setProject(updated);
    }
  }

  async function refreshProjectDetail(projectId: string) {
    try {
      const detail = await getProject(projectId);
      setProjects((current) => current.map((item) => item.id === projectId ? detail : item));
      if (activeProject.current?.id === projectId) {
        updateKnownRevision(projectId, detail.revision);
        rememberDetail(detail);
      }
    } catch (error: unknown) {
      if (activeProject.current?.id === projectId) {
        setProjectError(error instanceof ProjectApiError ? error.message : "The saved project history could not be refreshed.");
      }
    }
  }

  function applyProjectDetail(detail: ProjectDetail) {
    hydrating.current = true;
    const snapshot = detail.snapshot;
    const record: ProjectRecord = { id: detail.id, name: detail.name, revision: detail.revision,
      createdAt: detail.createdAt, updatedAt: detail.updatedAt, snapshot };
    rememberRecord(record);
    rememberDetail(detail);
    setDocumentId(snapshot.documentId);
    setSourceDraft(snapshot.sourceDraft);
    setSentenceDocument(snapshot.document);
    setHasPrepared(snapshot.hasPrepared);
    setMode(snapshot.mode);
    setProposal(null);
    setReplacement(null);
    visualSelectionState.replaceSelections({ backgroundAssetId: snapshot.backgroundAssetId,
      illustrationsBySentence: snapshot.illustrationsBySentence });
    speech.resetSelection();
    speech.restoreProjectAudio(detail.audio, snapshot.voice);
    video.resetDocument();
    lastAcknowledgedKey.current = projectStateKey(detail.name, snapshot);
    pendingCreate.current = null;
    pendingSave.current = null;
    setSaveError("");
    setSaveStatus("saved");
    setProjectError(detail.warnings.length ? detail.warnings.join(" ") : "");
    rememberProjectAssets({ projectId: detail.id, documentId: snapshot.documentId,
      audioBySentence: Object.fromEntries(detail.audio.map((item) => [item.id, item.assetId])),
      backgroundAssetId: snapshot.backgroundAssetId,
      illustrationsBySentence: snapshot.illustrationsBySentence });
    const pending = pendingSubmissionsFor(detail.id)[0];
    if (pending) {
      const context: ProjectSubmissionContext = {
        projectId: detail.id,
        projectName: detail.name,
        documentId: pending.documentId,
        revision: detail.revision,
        name: detail.name,
        snapshot,
        submissionToken: pending.submissionToken,
        onAccepted: (revision) => updateKnownRevision(detail.id, revision),
        onFinished: () => {
          forgetPendingSubmission(detail.id, pending.submissionToken);
          void refreshProjectDetail(detail.id);
        },
      };
      if (pending.kind === "speech") speech.restorePendingSubmission(context);
      else video.restorePendingSubmission(context);
    }
    setNotice(detail.warnings.length ? "Project opened with unavailable resources. Review the warnings before generating." : "Project opened. Saved audio and video history are ready to review.");
  }

  function currentContentExists(snapshot: ProjectSnapshot, name: string) {
    return snapshot.sourceDraft.length > 0 || snapshot.hasPrepared || snapshot.document.sentences.length > 0
      || snapshot.mode !== "manual" || snapshot.backgroundAssetId !== null
      || Object.keys(snapshot.illustrationsBySentence).length > 0 || name !== "Untitled project";
  }

  async function flushSave(forceCreate = false): Promise<ProjectRecord | null> {
    const currentProject = activeProject.current;
    const currentSnapshot = snapshotRef.current;
    if (!currentSnapshot) throw new Error("Project state is not ready to save.");
    const currentName = projectNameRef.current;
    const currentKey = projectStateKey(currentName, currentSnapshot);
    if (saveQueue.current) {
      await saveQueue.current;
      if (lastAcknowledgedKey.current === currentKey) return activeProject.current;
      return flushSave(forceCreate);
    }
    if (currentProject && lastAcknowledgedKey.current === currentKey && !pendingCreate.current && !pendingSave.current) return currentProject;
    if (!currentProject && !pendingCreate.current && !forceCreate && !currentContentExists(currentSnapshot, currentName)) return null;

    const run = (async () => {
      try {
        while (true) {
          if (!activeProject.current) {
            let operation = pendingCreate.current;
            if (!operation) {
              const snapshot = snapshotRef.current ?? currentSnapshot;
              const name = projectNameRef.current;
              operation = { name, snapshot, key: projectStateKey(name, snapshot), operationToken: createOpaqueToken() };
              pendingCreate.current = operation;
            }
            setSaveStatus("saving");
            const created = await createProject(operation.name, operation.snapshot, operation.operationToken);
            rememberRecord(created);
            lastAcknowledgedKey.current = operation.key;
            pendingCreate.current = null;
            const latest = snapshotRef.current;
            const latestName = projectNameRef.current;
            if (latest && projectStateKey(latestName, latest) === operation.key) {
              setSaveStatus("saved");
              setSaveError("");
              return created;
            }
            continue;
          }

          const base = activeProject.current;
          let operation = pendingSave.current;
          if (!operation) {
            const snapshot = snapshotRef.current ?? currentSnapshot;
            const name = projectNameRef.current;
            operation = { projectId: base.id, name, snapshot, key: projectStateKey(name, snapshot),
              expectedRevision: base.revision, operationToken: createOpaqueToken() };
            pendingSave.current = operation;
          }
          if (operation.projectId !== base.id) throw new Error("The pending save belongs to a different project. Retry it before switching projects.");
          setSaveStatus("saving");
          setSaveError("");
          const saved = await saveProject(operation.projectId, operation.name, operation.snapshot,
            operation.expectedRevision, operation.operationToken);
          rememberRecord(saved);
          if (detailRef.current?.id === saved.id) rememberDetail({ ...detailRef.current, ...saved });
          lastAcknowledgedKey.current = operation.key;
          pendingSave.current = null;
          const latest = snapshotRef.current;
          const latestName = projectNameRef.current;
          const latestKeyNow = latest ? projectStateKey(latestName, latest) : "";
          if (latestKeyNow === operation.key) {
            setSaveStatus("saved");
            setSaveError("");
            return saved;
          }
        }
      } catch (error: unknown) {
        if (error instanceof ProjectApiError && (error.status === 400 || error.status === 422)) {
          pendingCreate.current = null;
          pendingSave.current = null;
        }
        setSaveStatus("failed");
        setSaveError(error instanceof ProjectApiError ? error.message : "The project could not be saved. Retry before switching projects.");
        throw error;
      }
    })();
    saveQueue.current = run;
    try {
      return await run;
    } finally {
      if (saveQueue.current === run) saveQueue.current = null;
    }
  }

  function resetToNewProject() {
    projectLoadSequence.current += 1;
    activeProject.current = null;
    setProject(null);
    detailRef.current = null;
    setProjectDetail(null);
    setProjectName("Untitled project");
    projectNameRef.current = "Untitled project";
    setDocumentId(createOpaqueToken());
    setSourceDraft("");
    setSentenceDocument(createSentenceDocument(""));
    setHasPrepared(false);
    setMode("manual");
    setProposal(null);
    setReplacement(null);
    visualSelectionState.replaceSelections({ backgroundAssetId: null, illustrationsBySentence: {} });
    speech.resetSelection();
    speech.resetProjectState();
    video.resetDocument();
    lastAcknowledgedKey.current = null;
    pendingCreate.current = null;
    pendingSave.current = null;
    setSaveError("");
    setSaveStatus("unsaved");
    setProjectError("");
    setNotice("New project. Save when you are ready; generation also saves the project automatically.");
  }

  async function openProject(projectId: string) {
    const sequence = ++projectLoadSequence.current;
    const detail = await getProject(projectId);
    if (sequence !== projectLoadSequence.current) return;
    applyProjectDetail(detail);
  }

  function handleProjectRemoved(projectId: string, result: ProjectCleanupResult) {
    setResourceRefreshSignal((value) => value + 1);
    setProjects((current) => current.filter((item) => item.id !== projectId));
    if (lastProjectId === projectId) {
      setLastProjectId(null);
      setLastProjectIdState(null);
    }
    if (activeProject.current?.id === projectId) {
      if (autosaveTimer.current !== null) clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
      resetToNewProject();
      setNotice(result.status === "partial"
        ? `Project “${result.projectName}” was removed with ${result.failedFiles} file cleanup failures. Review Retained resources and retry the cleanup there.`
        : result.status === "pending"
          ? `Cleanup for “${result.projectName}” is pending. The project is closed to editing; check Retained resources and retry the same cleanup there.`
          : `Project “${result.projectName}” was removed. Any retained media is available below.`);
    }
  }

  async function refreshAfterUnconfirmedCleanup(projectId: string) {
    try {
      const currentProjects = await listProjects();
      setProjects(currentProjects);
      if (!currentProjects.some((item) => item.id === projectId)) {
        if (lastProjectId === projectId) {
          setLastProjectId(null);
          setLastProjectIdState(null);
        }
        if (activeProject.current?.id === projectId) {
          resetToNewProject();
          setNotice("This project is no longer in the saved project list. Check Retained resources for cleanup results.");
        }
        return;
      }
      if (activeProject.current?.id === projectId) applyProjectDetail(await getProject(projectId));
    } catch (error: unknown) {
      setProjectError(error instanceof ProjectApiError ? error.message : "Project status could not be refreshed after cleanup.");
    }
  }

  async function performNavigation(navigation: ProjectNavigation, discard = false) {
    if (speech.waiting || video.waiting || aiPending) return;
    if (!discard) {
      try {
          await flushSave();
      } catch {
        setPendingNavigation(navigation);
        return;
      }
    } else if (activeProject.current) {
      try {
        const saved = await getProject(activeProject.current.id);
        applyProjectDetail(saved);
      } catch (error: unknown) {
        setProjectError(error instanceof ProjectApiError ? error.message : "The last saved version could not be reopened.");
        return;
      }
    } else {
      resetToNewProject();
    }
    setPendingNavigation(null);
    if (navigation.kind === "new") resetToNewProject();
    else {
      try { await openProject(navigation.projectId); }
      catch (error: unknown) {
        setProjectError(error instanceof ProjectApiError ? error.message : "The selected project could not be opened.");
      }
    }
  }

  async function generateSpeech(sentences: readonly { id: string; text: string }[], force = false) {
    if (generationPreparing || speech.outstanding || video.outstanding || aiPending) return;
    setGenerationPreparing(true);
    try {
      await flushSave();
      let record = activeProject.current;
      if (!record) throw new Error("Save the project before generating speech.");
      const snapshot = snapshotRef.current;
      if (!snapshot) throw new Error("Project state is not ready to generate speech.");
      const token = createOpaqueToken();
      const key = projectStateKey(projectNameRef.current, snapshot);
      const context: ProjectSubmissionContext = {
        projectId: record.id, projectName: record.name, documentId: snapshot.documentId,
        revision: record.revision, name: projectNameRef.current, snapshot, submissionToken: token,
        onAccepted: (revision) => {
          updateKnownRevision(record!.id, revision);
          if (snapshotRef.current && projectStateKey(projectNameRef.current, snapshotRef.current) === key) {
            lastAcknowledgedKey.current = key;
            setSaveStatus("saved");
          }
        },
        onFinished: () => {
          forgetPendingSubmission(record!.id, token);
          void refreshProjectDetail(record!.id);
        },
      };
      rememberPendingSubmission({ projectId: record.id, projectName: record.name, documentId: snapshot.documentId,
        submissionToken: token, kind: "speech" });
      await speech.generate(sentences, force, context);
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "The project must be saved before speech can start.");
    } finally {
      setGenerationPreparing(false);
    }
  }

  async function generateVideo(sentences: Parameters<typeof video.generate>[0]) {
    if (generationPreparing || speech.outstanding || video.outstanding || aiPending || !speech.binding) return;
    setGenerationPreparing(true);
    try {
      await flushSave();
      const record = activeProject.current;
      const snapshot = snapshotRef.current;
      if (!record || !snapshot) throw new Error("Save the project before generating video.");
      const token = createOpaqueToken();
      const key = projectStateKey(projectNameRef.current, snapshot);
      const context: ProjectSubmissionContext = {
        projectId: record.id, projectName: record.name, documentId: snapshot.documentId,
        revision: record.revision, name: projectNameRef.current, snapshot, submissionToken: token,
        onAccepted: (revision) => {
          updateKnownRevision(record.id, revision);
          if (snapshotRef.current && projectStateKey(projectNameRef.current, snapshotRef.current) === key) {
            lastAcknowledgedKey.current = key;
            setSaveStatus("saved");
          }
        },
        onFinished: () => {
          forgetPendingSubmission(record.id, token);
          void refreshProjectDetail(record.id);
        },
      };
      rememberPendingSubmission({ projectId: record.id, projectName: record.name, documentId: snapshot.documentId,
        submissionToken: token, kind: "video" });
      await video.generate(sentences, speech.binding, snapshot.backgroundAssetId, context);
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "The project must be saved before video generation can start.");
    } finally {
      setGenerationPreparing(false);
    }
  }

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    getBackendHealth()
      .then(() => {
        if (active) setBackendState("online");
      })
      .catch(() => {
        if (active) setBackendState("offline");
      });
    getTextProviders(controller.signal)
      .then((availableProviders) => {
        if (!active) return;
        setProviders(availableProviders);
        setProviderStatus("online");
      })
      .catch(() => {
        if (active) setProviderStatus("offline");
      });
    return () => {
      active = false;
      controller.abort();
      requestSequence.current += 1;
      activeRequest.current?.abort();
      if (requestTimer.current !== null) clearTimeout(requestTimer.current);
    };
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    listProjects(controller.signal).then((items) => {
      if (!active) return;
      setProjects(items);
      setProjectLoadState("online");
      const lastId = getLastProjectId();
      setLastProjectIdState(lastId && items.some((item) => item.id === lastId) ? lastId : null);
    }).catch((error: unknown) => {
      if (!active) return;
      setProjectLoadState("offline");
      setProjectError(error instanceof ProjectApiError ? error.message : "Saved projects could not be loaded. Editing remains available.");
    }).finally(() => {
      if (active) {
        setWorkspaceReady(true);
        setSaveStatus("unsaved");
      }
    });
    return () => { active = false; controller.abort(); };
  }, []);

  useEffect(() => {
    if (replacement !== null) cancelButton.current?.focus();
    else if (wasConfirming.current) {
      if (confirmationOrigin.current === "ai" && applyButton.current) applyButton.current.focus();
      else prepareButton.current?.focus();
    }
    wasConfirming.current = replacement !== null;
  }, [replacement]);

  useEffect(() => {
    if (!hydrating.current) return;
    const active = activeProject.current;
    if (active && lastAcknowledgedKey.current === latestKey
      && projectStateKey(active.name, latestSnapshot) === latestKey) hydrating.current = false;
  }, [latestKey, latestSnapshot, project]);

  const hasUnsavedWork = project
    ? lastAcknowledgedKey.current !== latestKey
    : currentContentExists(latestSnapshot, projectName);

  useEffect(() => {
    if (!workspaceReady || hydrating.current) return;
    if (!project) {
      setSaveStatus((current) => current === "saving" ? current : "unsaved");
      return;
    }
    if (lastAcknowledgedKey.current === latestKey || saveStatus === "failed") {
      if (lastAcknowledgedKey.current === latestKey) setSaveStatus("saved");
      return;
    }
    if (autosaveTimer.current !== null) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      autosaveTimer.current = null;
      void flushSave().catch(() => undefined);
    }, 2_000);
    return () => {
      if (autosaveTimer.current !== null) clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    };
  }, [workspaceReady, project, latestKey, saveStatus]);

  useEffect(() => {
    if (!workspaceReady || !hasUnsavedWork) return;
    const warnOnLeave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnOnLeave);
    return () => window.removeEventListener("beforeunload", warnOnLeave);
  }, [workspaceReady, hasUnsavedWork]);

  function prepareSentences(source: string) {
    const prepared = createSentenceDocument(source);
    setDocumentId(createOpaqueToken());
    setSentenceDocument(prepared);
    visualSelectionState.clearSentenceIllustrations();
    speech.resetSelection();
    video.resetDocument();
    setHasPrepared(true);
    setReplacement(null);
    setNotice(`Prepared ${prepared.sentences.length} sentences. Your source snapshot is saved below.`);
  }

  function requestPreparation() {
    if (hasPrepared || sentenceDocument.sentences.length > 0) {
      confirmationOrigin.current = "manual";
      setReplacement({ kind: "manual", source: sourceDraft });
      return;
    }
    prepareSentences(sourceDraft);
  }

  function stopWaiting(timedOut = false) {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    if (requestTimer.current !== null) clearTimeout(requestTimer.current);
    requestTimer.current = null;
    setAiPending(false);
    if (timedOut) setAiError("AI preparation timed out. Your source and current edits are preserved.");
    else setNotice("Stopped waiting for the AI result. The provider may still be running; your current work is preserved.");
  }

  async function requestAiPreparation() {
    const provider = providers.find((item) => item.id === selectedProvider && item.available);
    if (!provider || aiPending || proposal || !sourceDraft.trim() || sourceDraft.length > MAX_SOURCE_LENGTH) return;
    const controller = new AbortController();
    const sequence = ++requestSequence.current;
    activeRequest.current = controller;
    setAiError("");
    setNotice("");
    setAiPending(true);
    requestTimer.current = setTimeout(() => stopWaiting(true), AI_REQUEST_TIMEOUT_MS);
    try {
      const result = await prepareText(provider.id, sourceDraft, controller.signal);
      if (sequence !== requestSequence.current || controller.signal.aborted) return;
      setProposal(result);
      setNotice("AI proposal ready for review. Your current sentence list has not changed.");
    } catch (error: unknown) {
      if (sequence !== requestSequence.current || controller.signal.aborted) return;
      setAiError(error instanceof TextApiError ? error.message : "AI preparation failed. Your source and current edits are preserved.");
    } finally {
      if (sequence === requestSequence.current) {
        if (requestTimer.current !== null) clearTimeout(requestTimer.current);
        requestTimer.current = null;
        activeRequest.current = null;
        setAiPending(false);
      }
    }
  }

  function applyProposal(reviewed: TextProposal) {
    const accepted = createSentenceDocumentFromProposal(reviewed.sourceText, reviewed.sentences);
    setDocumentId(createOpaqueToken());
    setSentenceDocument(accepted);
    visualSelectionState.clearSentenceIllustrations();
    speech.resetSelection();
    video.resetDocument();
    setHasPrepared(true);
    setProposal(null);
    setReplacement(null);
    setNotice(`Applied ${accepted.sentences.length} reviewed sentences. Use the manual tools to make corrections.`);
  }

  function requestProposalApplication() {
    if (!proposal) return;
    if (hasPrepared || sentenceDocument.sentences.length > 0) {
      confirmationOrigin.current = "ai";
      setReplacement({ kind: "ai", proposal });
      return;
    }
    applyProposal(proposal);
  }

  function applyOperation(operation: (current: SentenceDocument) => SentenceDocument, message: string) {
    setSentenceDocument(operation);
    setNotice(message);
  }

  function splitAtCursor(id: SentenceId, position: number) {
    const input = sentenceInputs.current.get(id);
    if (!input) return;

    if (input.selectionStart !== input.selectionEnd) {
      setNotice("Collapse the selection to a single cursor position before splitting.");
      input.focus();
      return;
    }

    const updated = splitSentence(sentenceDocument, id, input.selectionStart);
    if (updated === sentenceDocument) {
      setNotice("Place the cursor between two non-empty parts of the sentence, then choose Split at cursor.");
      input.focus();
      return;
    }

    setSentenceDocument(updated);
    setNotice(illustrationsBySentence[id]
      ? `Split sentence ${position}. Its illustration stays with the first part; the new sentence has no illustration.`
      : `Split sentence ${position} into two sentences. The new sentence has no illustration.`);
  }

  function mergeSentenceWithPrevious(id: SentenceId, position: number) {
    const index = sentenceDocument.sentences.findIndex((sentence) => sentence.id === id);
    if (index <= 0) return;
    const previous = sentenceDocument.sentences[index - 1];
    const removedAssetId = illustrationsBySentence[id];
    const retainedAssetId = illustrationsBySentence[previous.id];
    if (removedAssetId && removedAssetId !== retainedAssetId) {
      const removedAsset = visuals.assets.find((asset) => asset.id === removedAssetId);
      const retainedAsset = visuals.assets.find((asset) => asset.id === retainedAssetId);
      const removedName = removedAsset?.name ?? "an assigned illustration";
      const retainedName = retainedAsset?.name ?? "no illustration";
      if (!window.confirm(`Sentence ${position} uses “${removedName}”, while the sentence above uses “${retainedName}”. Merging removes sentence ${position}'s assignment and keeps the sentence above's illustration. Continue?`)) return;
    }
    setSentenceDocument((current) => mergeWithPrevious(current, id));
    visualSelectionState.removeSentenceIllustration(id);
    setNotice(removedAssetId && removedAssetId !== retainedAssetId
      ? `Merged sentence ${position}; the previous sentence's illustration was kept.`
      : `Merged sentence ${position} with the previous sentence.`);
  }

  function deleteSentenceWithIllustration(id: SentenceId, position: number) {
    setSentenceDocument((current) => deleteSentence(current, id));
    visualSelectionState.removeSentenceIllustration(id);
    setNotice(`Deleted sentence ${position}. Its illustration assignment was removed; the image remains in the library.`);
  }

  const preparingAgain = replacement !== null;
  const mediaWorkBusy = preparingAgain || aiPending || generationPreparing || speech.waiting || video.waiting
    || speech.outstanding || video.outstanding;
  const projectSwitchBlocked = preparingAgain || aiPending || speech.waiting || video.waiting || generationPreparing || cleanupDialogOpen || imageCleanupDialogOpen;
  const editingLocked = preparingAgain || aiPending || speech.waiting || video.waiting || generationPreparing || cleanupDialogOpen || imageCleanupDialogOpen;
  const cleanupBlocked = !workspaceReady || projectLoadState !== "online" || projectSwitchBlocked || speech.outstanding || video.outstanding
    || saveStatus === "saving" || (!!project && pendingSubmissionsFor(project.id).length > 0);
  const imageCleanupBlocked = mediaWorkBusy || cleanupDialogOpen || imageCleanupDialogOpen;
  const sourceLocked = editingLocked || proposal !== null;
  const providerAvailable = providers.some((item) => item.id === selectedProvider && item.available);
  const sourceOverLimit = mode === "ai" && sourceDraft.length > MAX_SOURCE_LENGTH;
  const sentenceCount = sentenceDocument.sentences.length;
  const visualProblem = visuals.selectionProblem([
    ...(backgroundAssetId ? [{ id: backgroundAssetId, kind: "background" as const }] : []),
    ...Object.entries(illustrationsBySentence)
      .filter(([sentenceId]) => sentenceDocument.sentences.some((sentence) => sentence.id === sentenceId))
      .map(([, id]) => ({ id, kind: "illustration" as const })),
  ]);
  const outstanding = speech.outstandingInfo ?? video.outstandingInfo;
  const activeHistory = projectDetail && projectDetail.id === project?.id ? projectDetail.history : [];
  const selectedVisualAssetIds = new Set([backgroundAssetId, ...Object.values(illustrationsBySentence)].filter((id): id is string => id !== null));

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Shadowing Video Studio</p>
          <h1>Prepare your dialogue</h1>
          <p className="description">Shape your English dialogue into the sentences you want to practise.</p>
        </div>
        <p className="service-status" data-state={backendState} role="status">
          <span className="status-dot" aria-hidden="true" />
          {backendState === "checking" && "Checking local service…"}
          {backendState === "online" && "Local service connected"}
          {backendState === "offline" && "Local service unavailable · Editing still works"}
        </p>
      </header>

      <nav className="app-page-nav" aria-label="Studio pages">
        <button type="button" aria-current={page === "create" ? "page" : undefined}
          disabled={cleanupDialogOpen || imageCleanupDialogOpen} onClick={() => setPage("create")}>Create video</button>
        <button type="button" aria-current={page === "resources" ? "page" : undefined}
          disabled={cleanupDialogOpen || imageCleanupDialogOpen} onClick={() => setPage("resources")}>Resource manager</button>
      </nav>
      {outstanding && <p className="project-outstanding" role="status">
        A {speech.outstandingInfo ? "speech" : "video"} submission for <strong>{outstanding.projectName}</strong> remains outstanding. Switching pages does not cancel it.
      </p>}

      <section className="app-page create-video-page" aria-label="Create video" hidden={page !== "create"}>

      <section className="project-toolbar" aria-label="Project controls">
        <div className="project-name-field">
          <label htmlFor="project-name">Project name</label>
          <input id="project-name" value={projectName} maxLength={120} disabled={projectSwitchBlocked}
            onChange={(event) => setProjectName(event.target.value)} />
        </div>
        <button type="button" disabled={!workspaceReady || projectSwitchBlocked}
          onClick={() => { void performNavigation({ kind: "new" }); }}>New project</button>
        <div className="project-open-field">
          <label htmlFor="open-project">Open project</label>
          <select id="open-project" value="" disabled={!workspaceReady || projectSwitchBlocked || projectLoadState !== "online"}
            onChange={(event) => { const selectedId = event.target.value; if (selectedId) void performNavigation({ kind: "open", projectId: selectedId }); }}>
            <option value="">{projectLoadState === "checking" ? "Loading projects…" : "Choose a saved project"}</option>
            {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
        {lastProjectId && projects.some((item) => item.id === lastProjectId) && (
          <button type="button" disabled={projectSwitchBlocked} onClick={() => { void performNavigation({ kind: "open", projectId: lastProjectId }); }}>
            Open last project
          </button>
        )}
        <button type="button" className="primary-button" disabled={!workspaceReady || saveStatus === "saving" || projectSwitchBlocked}
          onClick={() => { void flushSave(true).catch((error: unknown) => {
            setProjectError(error instanceof Error ? error.message : "The project could not be saved.");
          }); }}>Save</button>
        <span className="save-status" data-state={saveStatus} role="status">
          {saveStatus === "loading" && "Loading projects…"}
          {saveStatus === "unsaved" && (project ? "Unsaved" : "Unsaved draft")}
          {saveStatus === "saving" && "Saving…"}
          {saveStatus === "saved" && "Saved"}
          {saveStatus === "failed" && "Save failed"}
        </span>
      </section>
      <ProjectCleanup activeProject={project} disabled={cleanupBlocked} flushSave={flushSave}
        onDialogOpenChange={setCleanupDialogOpen} onProjectRemoved={handleProjectRemoved}
        onRefreshProject={refreshAfterUnconfirmedCleanup} />
      {projectLoadState === "offline" && <p className="input-error" role="status">Saved project storage is unavailable. You can keep editing this draft; save status will update when the local service is available.</p>}
      {saveError && <p className="input-error" role="alert">{saveError}</p>}
      {projectError && <p className="input-error" role="alert">{projectError}</p>}

      {pendingNavigation && (
        <section className="confirmation" role="alertdialog" aria-labelledby="save-before-switch-title">
          <div>
            <h2 id="save-before-switch-title">Save this project before switching?</h2>
            <p>The save failed. Your current draft is still open. Retry the exact pending save, cancel the switch, or explicitly discard this draft and continue.</p>
          </div>
          <div className="confirmation-actions">
            <button type="button" onClick={() => setPendingNavigation(null)}>Cancel switch</button>
            <button type="button" onClick={() => { void performNavigation(pendingNavigation); }}>Retry save</button>
            <button type="button" className="delete-button" onClick={() => { void performNavigation(pendingNavigation, true); }}>Discard and continue</button>
          </div>
        </section>
      )}

      {replacement !== null && (
        <section
          className="confirmation"
          role="alertdialog"
          aria-labelledby="replace-title"
          aria-describedby="replace-description"
          onKeyDown={(event) => {
            if (event.key === "Escape") setReplacement(null);
          }}
        >
          <div>
            <h2 id="replace-title">Replace the current sentence list?</h2>
            <p id="replace-description">
              {replacement.kind === "manual"
                ? "Preparing again replaces all current sentence edits and the original source snapshot with your source dialogue draft. Cancel to keep your current work and draft."
                : "Applying this reviewed AI proposal replaces all current sentence edits and the original source snapshot with the proposal's source. Cancel to keep your current work and the proposal."}
            </p>
          </div>
          <div className="confirmation-actions">
            <button
              ref={cancelButton}
              type="button"
              onClick={() => setReplacement(null)}
            >Cancel</button>
            <button
              type="button"
              className="primary-button"
              onClick={() => {
                if (replacement.kind === "manual") prepareSentences(replacement.source);
                else applyProposal(replacement.proposal);
              }}
            >{replacement.kind === "manual" ? "Replace and prepare" : "Replace and apply"}</button>
          </div>
        </section>
      )}

      <div className="workspace">
        <section className="panel source-panel" aria-labelledby="source-title">
          <div className="panel-heading">
            <span className="step-number" aria-hidden="true">01</span>
            <div><h2 id="source-title">Source dialogue</h2><p>Start with the original English text.</p></div>
          </div>
          <fieldset className="preparation-mode" disabled={sourceLocked}>
            <legend>Preparation mode</legend>
            <label>
              <input type="radio" name="preparation-mode" value="manual" checked={mode === "manual"}
                onChange={() => { setMode("manual"); setAiError(""); }} />
              Manual
            </label>
            <label>
              <input type="radio" name="preparation-mode" value="ai" checked={mode === "ai"}
                onChange={() => { setMode("ai"); setAiError(""); }} />
              AI-assisted
            </label>
          </fieldset>
          {mode === "ai" && (
            <div className="provider-field">
              <label htmlFor="ai-provider">AI provider</label>
              <select id="ai-provider" value={selectedProvider} disabled={sourceLocked || providerStatus !== "online"}
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "" || value === "deepseek" || value === "codex") setSelectedProvider(value);
                  setAiError("");
                }}>
                <option value="">Choose a provider</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id} disabled={!provider.available}>
                    {provider.label}{!provider.available ? " · Unavailable" : ""}
                  </option>
                ))}
              </select>
              {providerStatus === "checking" && <p className="field-help">Checking provider availability…</p>}
              {providerStatus === "offline" && <p className="field-help">Provider availability could not be loaded. Check the local service; manual editing still works.</p>}
              {providers.filter((provider) => !provider.available).map((provider) => (
                <p key={provider.id} className="field-help">{provider.reason}</p>
              ))}
              <p className="field-help">Prepare sends this dialogue to the selected provider. Review its proposal before applying it. No audio or video is generated.</p>
            </div>
          )}
          <label htmlFor="source-dialogue">Source dialogue</label>
          <textarea
            id="source-dialogue"
            className="source-input"
            rows={11}
            value={sourceDraft}
            disabled={sourceLocked}
            placeholder={"Hello there. How are you?\nI’m doing well, thank you."}
            aria-describedby="source-help"
            onChange={(event) => setSourceDraft(event.target.value)}
          />
          <p className="field-help" id="source-help">
            {mode === "manual"
              ? "Sentences are prepared locally from punctuation and line breaks. Review and adjust the result."
              : "Your source is preserved exactly. AI preparation accepts up to 20,000 characters."}
          </p>
          {sourceOverLimit && <p className="input-error" role="alert">This dialogue has {sourceDraft.length.toLocaleString("en-US")} characters. Shorten it to 20,000 or fewer for AI preparation; the full draft is preserved.</p>}
          <button
            ref={prepareButton}
            type="button"
            className="primary-button prepare-button"
            disabled={!sourceDraft.trim() || sourceLocked || sourceOverLimit || (mode === "ai" && !providerAvailable)}
            onClick={mode === "manual" ? requestPreparation : requestAiPreparation}
          >{mode === "manual" ? "Prepare sentences" : aiPending ? "Preparing AI proposal…" : "Prepare AI proposal"}</button>
          {aiPending && (
            <div className="pending-preparation" role="status">
              <p className="field-help">Preparing a proposal. Your source and current edits are protected while waiting.</p>
              <button type="button" onClick={() => stopWaiting()}>Stop waiting</button>
            </div>
          )}
          {aiError && <p className="input-error" role="alert">{aiError}</p>}
          {proposal && <p className="field-help">Apply or discard the proposal before changing the source or preparing again.</p>}

          {hasPrepared && (
            <details className="source-snapshot">
              <summary>Original source snapshot</summary>
              <p className="field-help">Saved when this list was prepared. Sentence edits do not change it.</p>
              <pre>{sentenceDocument.sourceText}</pre>
            </details>
          )}
          <p className="session-note">Save this project to keep the source draft and edits after closing the browser. Unsaved changes are kept in this tab until it closes.</p>
        </section>

        <section className="panel editor-panel" aria-labelledby="editor-title">
          <div className="panel-heading editor-heading">
            <span className="step-number" aria-hidden="true">02</span>
            <div>
              <h2 id="editor-title">Sentence editor</h2>
              <p>{sentenceCount} {sentenceCount === 1 ? "sentence" : "sentences"} · Manual mode</p>
            </div>
            <button
              type="button"
              disabled={editingLocked}
              onClick={() => applyOperation((current) => insertSentenceAfter(current, null), "Added a sentence at the end.")}
            >Add sentence</button>
          </div>

          {proposal && (
            <section className="proposal-review" aria-labelledby="proposal-title">
              <h3 id="proposal-title">Review AI proposal</h3>
              <p className="field-help">{proposal.provider === "deepseek" ? "DeepSeek" : "Codex CLI"} proposed {proposal.sentences.length} sentences. Check the wording and order. This proposal has not been applied and generates no media.</p>
              <ol className="proposal-list" aria-label="Proposed sentences">
                {proposal.sentences.map((text, index) => <li key={index}>{text}</li>)}
              </ol>
              <div className="proposal-actions">
                <button ref={applyButton} type="button" className="primary-button" disabled={preparingAgain}
                  onClick={requestProposalApplication}>Apply reviewed sentences</button>
                <button type="button" disabled={preparingAgain} onClick={() => {
                  setProposal(null);
                  setNotice("Discarded the AI proposal. Your source and current sentence edits are preserved.");
                }}>Discard proposal</button>
              </div>
            </section>
          )}

          <p className="editor-notice" role="status" aria-live="polite">{notice}</p>

          <BackgroundImageControls visuals={visuals} value={backgroundAssetId}
            onChange={visualSelectionState.setBackgroundAssetId} disabled={editingLocked} />
          {visualSelectionState.storageWarning && <p className="input-error" role="status">{visualSelectionState.storageWarning}</p>}

          <SpeechControls speech={speech} sentences={sentenceDocument.sentences}
            locked={editingLocked || speech.outstanding || video.outstanding || proposal !== null}
            onGenerate={() => { void generateSpeech(sentenceDocument.sentences); }} />

          {sentenceCount === 0 ? (
            <div className="empty-state">
              <h3>Your sentence list starts here</h3>
              <p>Paste dialogue and prepare it, or add your first sentence.</p>
            </div>
          ) : (
            <>
              <p className="field-help split-help" id="split-help">
                To split, place the text cursor where the new sentence should begin, then choose Split at cursor.
              </p>
              <ol className="sentence-list">
                {sentenceDocument.sentences.map((sentence, index) => {
                  const position = index + 1;
                  return (
                    <li key={sentence.id} className="sentence-card" data-testid={`sentence-card-${position}`} data-sentence-id={sentence.id}>
                      <label htmlFor={`input-${sentence.id}`}>Sentence {position}</label>
                      <textarea
                        id={`input-${sentence.id}`}
                        rows={3}
                        value={sentence.text}
                        disabled={editingLocked}
                        aria-describedby="split-help"
                        ref={(input) => {
                          if (input) sentenceInputs.current.set(sentence.id, input);
                          else sentenceInputs.current.delete(sentence.id);
                        }}
                        onChange={(event) => setSentenceDocument((current) => updateSentenceText(current, sentence.id, event.target.value))}
                      />
                      <div className="sentence-actions" role="group" aria-label={`Actions for sentence ${position}`}>
                        <button type="button" disabled={editingLocked} aria-label={`Split sentence ${position} at cursor`} onClick={() => splitAtCursor(sentence.id, position)}>Split at cursor</button>
                        <button type="button" disabled={index === 0 || editingLocked} aria-label={`Merge sentence ${position} with previous`} onClick={() => mergeSentenceWithPrevious(sentence.id, position)}>Merge above</button>
                        <button type="button" disabled={editingLocked} aria-label={`Add after sentence ${position}`} onClick={() => applyOperation((current) => insertSentenceAfter(current, sentence.id), `Added a sentence after sentence ${position}.`)}>Add below</button>
                        <button type="button" disabled={index === 0 || editingLocked} aria-label={`Move sentence ${position} up`} onClick={() => applyOperation((current) => moveSentence(current, sentence.id, "up"), `Moved sentence ${position} up.`)}>Move up</button>
                        <button type="button" disabled={index === sentenceCount - 1 || editingLocked} aria-label={`Move sentence ${position} down`} onClick={() => applyOperation((current) => moveSentence(current, sentence.id, "down"), `Moved sentence ${position} down.`)}>Move down</button>
                        <button type="button" className="delete-button" disabled={editingLocked} aria-label={`Delete sentence ${position}`} onClick={() => deleteSentenceWithIllustration(sentence.id, position)}>Delete</button>
                      </div>
                      <SentenceIllustrationPicker visuals={visuals} sentenceId={sentence.id} position={position}
                        value={illustrationsBySentence[sentence.id] ?? null}
                        onChange={(assetId) => visualSelectionState.setSentenceIllustration(sentence.id, assetId)}
                        disabled={editingLocked} />
                      <SentenceSpeech sentence={sentence} position={position} selection={speech.selection} job={speech.job}
                        binding={speech.binding}
                        disabled={editingLocked || speech.outstanding || video.outstanding || proposal !== null || !speech.readiness?.available || !speech.capabilities?.available}
                        regenerate={() => { void generateSpeech([sentence], true); }} />
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </section>
      </div>
      <VideoControls video={video} sentences={sentenceDocument.sentences} selection={speech.selection} binding={speech.binding}
        locked={editingLocked || speech.outstanding || proposal !== null} backgroundAssetId={backgroundAssetId}
        illustrationsBySentence={illustrationsBySentence} visualProblem={visualProblem} history={activeHistory}
        onGenerate={(sentences) => { void generateVideo(sentences); }} />
      </section>

      <section className="app-page resource-manager-page" aria-label="Resource manager" hidden={page !== "resources"}>
        <RetainedResources refreshSignal={resourceRefreshSignal} disabled={mediaWorkBusy} />
        <VisualLibraryCleanup visuals={visuals} selectedAssetIds={selectedVisualAssetIds}
          projectName={projectName} busy={imageCleanupBlocked} onDialogOpenChange={setImageCleanupDialogOpen} />
      </section>
    </main>
  );
}
