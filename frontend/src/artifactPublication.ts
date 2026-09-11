import type { ArtifactPublishResult } from "./types";

export function announceArtifactPublished(
  published: ArtifactPublishResult,
  body: Record<string, unknown>,
) {
  if (!("BroadcastChannel" in window)) return;
  const artifactChannel = new BroadcastChannel("agenthub-artifact-authoring");
  artifactChannel.postMessage({
    kind: "artifact_published",
    artifactType: published.artifact_type,
    artifactVersionId: published.artifact_version_id,
    logicalId: published.logical_id,
    version: published.version,
    body,
  });
  artifactChannel.close();
}
