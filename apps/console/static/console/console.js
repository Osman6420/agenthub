/*
 * Console progressive enhancement.
 *
 * Every openable row keeps a real <a> in its primary cell. Organization switching uses
 * ordinary server-authorized POST buttons and does not depend on JavaScript.
 * (the server re-authorizes and re-scopes every request regardless).
 */
(function () {
  "use strict";

  // Marker class enables row hover only when JavaScript is active.
  document.documentElement.classList.add("js-on");
  var formErrorSummary = document.querySelector("[data-form-error-summary]");
  if (formErrorSummary) formErrorSummary.focus();

  // A deep link must reveal its section even when it lives in a collapsed detail.
  function revealFragment() {
    var id;
    try { id = decodeURIComponent(window.location.hash.slice(1)); }
    catch (_) { return; }
    var target = document.getElementById(id);
    if (!target) return;
    var detail = target.closest("details");
    var changed = false;
    while (detail) {
      if (!detail.open) { detail.open = true; changed = true; }
      detail = detail.parentElement && detail.parentElement.closest("details");
    }
    if (changed) target.scrollIntoView();
  }
  window.addEventListener("hashchange", revealFragment);
  revealFragment();

  var menuToggle = document.querySelector(".mobile-nav-toggle");
  var primaryNavigation = document.getElementById("primary-navigation");
  if (menuToggle && primaryNavigation) {
    menuToggle.addEventListener("click", function () {
      var expanded = menuToggle.getAttribute("aria-expanded") !== "true";
      menuToggle.setAttribute("aria-expanded", String(expanded));
      primaryNavigation.classList.toggle("is-open", expanded);
    });
    primaryNavigation.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || menuToggle.getClientRects().length === 0) return;
      menuToggle.setAttribute("aria-expanded", "false");
      primaryNavigation.classList.remove("is-open");
      menuToggle.focus();
    });
  }

  // These are same-page section links, not tab panels. Keep location feedback
  // aligned with deep links and browser back/forward without hiding any forms.
  document.querySelectorAll(".task-tabs").forEach(function (navigation) {
    var links = Array.from(navigation.querySelectorAll('a[href^="#"]'));
    var initial = links.find(function (link) { return link.hasAttribute("aria-current"); }) || links[0];
    function updateSection() {
      var targetId;
      try { targetId = decodeURIComponent(window.location.hash.slice(1)); }
      catch (_) { targetId = ""; }
      var target = document.getElementById(targetId);
      var selected = links.find(function (link) {
        var section = document.getElementById(link.getAttribute("href").slice(1));
        return section && target && (section === target || section.contains(target));
      }) || initial;
      links.forEach(function (link) {
        if (link === selected) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    }
    window.addEventListener("hashchange", updateSection);
    updateSection();
  });

  // Row-level "click to open". A <tr data-href="..."> opens its target on click,
  //    but only for plain clicks that are not on a nested interactive control and not
  //    the end of a text selection. Keyboard and screen-reader users use the real
  //    anchor in the primary cell; this is a mouse convenience layer.
  var INTERACTIVE = "a, button, input, select, textarea, label, summary, [role='button']";

  function openRow(row, newTab) {
    var href = row.getAttribute("data-href");
    if (!href) return;
    if (newTab) {
      window.open(href, "_blank", "noopener");
    } else {
      window.location.href = href;
    }
  }

  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (event) {
      if (event.defaultPrevented) return;
      if (event.target.closest(INTERACTIVE)) return; // let real controls handle it
      var selection = window.getSelection && window.getSelection();
      if (selection && String(selection).length > 0) return; // user was selecting text
      openRow(row, event.metaKey || event.ctrlKey);
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var message = form.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

})();
