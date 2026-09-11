"""Explicit review of legacy scenario data-selection changes."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.console.scoping import scoped_scenarios
from apps.releases.compiler import CompileError
from apps.releases.publication import PublicationError
from apps.releases.runtime_transition import enable_runtime_snapshot, preview_runtime_transition
from apps.workflows.compiler import WorkflowCompileError


@login_required
@require_http_methods(["GET", "POST"])
def review(request, public_id):
    scenario = get_object_or_404(scoped_scenarios(request.user), public_id=public_id)
    error = ""
    state = None
    try:
        if request.method == "POST":
            if (
                request.FILES
                or set(request.POST) - {"csrfmiddlewaretoken", "review"}
                or len(request.POST.getlist("review")) != 1
                or len(request.POST.get("review", "")) > 2048
            ):
                raise PublicationError("RUNTIME_TRANSITION_REVIEW_INVALID")
            enable_runtime_snapshot(
                actor=request.user,
                scenario=scenario,
                review=request.POST["review"],
                request_id=getattr(request, "request_id", ""),
            )
            messages.success(
                request,
                "Ayar kaydedildi. Değişikliği kullanıma almak için senaryoyu test edip yayınlayın.",
            )
            return redirect("console:scenario_detail_public", public_id=scenario.public_id)
        state = preview_runtime_transition(actor=request.user, scenario=scenario)
    except (PublicationError, CompileError, WorkflowCompileError) as exc:
        error = (
            "Bu senaryoda belirli bir arama indeksine bağlı ayar var. Önce bu bağı gözden geçirin."
            if getattr(exc, "code", "") == "RUNTIME_TRANSITION_PINNED_INDEX"
            else (
                "Ayarlar değişmiş veya gözden geçirme süresi dolmuş olabilir. "
                "Akış ayarlarını kontrol edip sayfayı yeniden açın."
            )
        )
    return render(
        request,
        "console/runtime_transition.html",
        {
            "scenario": scenario,
            "transition": state,
            "error": error,
        },
        status=400 if error else 200,
    )
