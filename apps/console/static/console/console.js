/*
 * Console progressive enhancement.
 *
 * The console is fully usable without JavaScript: the organization selector has a
 * visible submit button and every openable row keeps a real <a> in its primary cell.
 * This script only *enhances* those flows — it never becomes the access boundary
 * (the server re-authorizes and re-scopes every request regardless).
 */
(function () {
  "use strict";

  // Marker class lets CSS hide the now-redundant submit button and enable row hover
  // only when JS is active, so the no-JS experience stays complete.
  document.documentElement.classList.add("js-on");

  // 1) Auto-submit the active-organization selector on change.
  document.querySelectorAll("form[data-autosubmit] select").forEach(function (select) {
    select.addEventListener("change", function () {
      var form = select.form;
      if (!form) return;
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  });

  // 2) Row-level "click to open". A <tr data-href="..."> opens its target on click,
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
})();
