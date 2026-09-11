"""One lock order and attempt fence for generation mutations.

Call only inside a transaction with trusted singleton tenant context. Lock jobs
before generations; provider I/O must remain outside this boundary.
"""

from apps.ingestion.models import IndexVersion, StagedIndexBuildJob, StagedIndexBuildJobStatus


class GenerationFenced(RuntimeError):
    code = "BUILD_GENERATION_FENCED"

    def __init__(self):
        super().__init__(self.code)


def lock_build_request(index: IndexVersion, *, require_running: bool = True) -> None:
    # Re-read provenance rather than trusting a stale caller's unbound generation.
    lineage = IndexVersion.objects.only("build_request_id", "build_attempt").get(
        pk=index.pk,
        organization_id=index.organization_id,
    )
    if lineage.build_request_id:
        job = StagedIndexBuildJob.objects.select_for_update().get(
            pk=lineage.build_request_id,
            organization_id=index.organization_id,
        )
        if require_running and (
            job.status != StagedIndexBuildJobStatus.RUNNING or job.attempt != lineage.build_attempt
        ):
            raise GenerationFenced()


def lock_generation(index: IndexVersion, *, require_running: bool = True) -> IndexVersion:
    lock_build_request(index, require_running=require_running)
    return IndexVersion.objects.select_for_update().get(
        pk=index.pk,
        organization_id=index.organization_id,
    )
