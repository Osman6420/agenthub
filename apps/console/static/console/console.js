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

  document.querySelectorAll("select[data-capability-presets]").forEach(function (select) {
    var presets;
    try {
      presets = JSON.parse(select.getAttribute("data-capability-presets") || "{}");
    } catch (_error) {
      return;
    }
    select.addEventListener("change", function () {
      var selected = presets[select.value];
      if (!Array.isArray(selected)) return;
      var form = select.closest("form");
      if (!form) return;
      form.querySelectorAll('input[name="capabilities"]').forEach(function (checkbox) {
        checkbox.checked = selected.indexOf(checkbox.value) !== -1;
      });
    });
  });
})();
